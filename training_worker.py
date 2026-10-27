#!/usr/bin/env python3
"""Warm, authenticated Serverless GPU trainer and job-scoped LoRA inference.

Independent model processes share the GPU. Training and inference use separate
bounded pools; every request explicitly selects its own job adapter.
"""
import contextlib, hashlib, hmac, json, math, multiprocessing, os, queue, re, subprocess, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MODEL = 'Qwen/Qwen3-0.6B'
REVISION = 'c1899de289a04d12100db370d81485cdf75e47ca'
ROOT = Path(os.environ.get('TRAINING_DATA_DIR', '/mnt/data/warm-caretaker'))
TOKEN = os.environ.get('CARETAKER_WORKER_TOKEN', '')
LOCK = threading.RLock()
JOBS_LOCK = threading.RLock()
JOBS = {}
PENDING = queue.Queue(maxsize=64)
TRAIN_PENDING = queue.Queue(maxsize=64)
TRAINING_WORKERS = int(os.environ.get("CARETAKER_TRAINING_WORKERS", "2"))
INFERENCE_WORKERS = int(os.environ.get("CARETAKER_INFERENCE_WORKERS", "4"))
ACTIVE_TRAINING = set()
PEAK_TRAINING = 0
PEAK_INFERENCE = 0
STATUS_PIPE = None
RUNTIMES = []
READY = False
LOADED = set()
CURRENT_JOB = None
SLOTS = {}
SLOTS_LOCK = threading.RLock()
ACTIVE_SLOT = None
SLOT_TTL = 90
ADMISSION_LOCK = threading.RLock()

def ahead(item):
    with PENDING.mutex:
        pending = list(PENDING.queue)
    try: return pending.index(item) + sum(s["status"] == "active" for s in SLOTS.values())
    except ValueError: return 0

def training_ahead(identifier):
    with TRAIN_PENDING.mutex:
        pending = list(TRAIN_PENDING.queue)
    try: return pending.index(identifier) + len(ACTIVE_TRAINING)
    except ValueError: return 0

def slot_info(identifier, renew=False):
    with SLOTS_LOCK:
        slot = SLOTS.get(identifier)
        if not slot: raise ValueError('GPU queue task was not found. Retry this operation.')
        if renew: slot['touched'] = time.monotonic()
        result = {k: slot[k] for k in ('id', 'status', 'job_id', 'label')}
    result['queue_ahead'] = ahead(('slot', identifier)) if result['status'] == 'queued' else 0
    return result

def reserve(body):
    if not READY: raise ValueError('The GPU worker is still warming its base model.')
    identifier = 'slot-' + str(uuid.UUID(body['request_id'])).replace('-', '')
    job = body.get('job_id')
    if job is not None: folder(job)
    with ADMISSION_LOCK, SLOTS_LOCK:
        previous = SLOTS.get(identifier)
        if previous:
            if previous['job_id'] != job: raise ValueError('This GPU task belongs to another checkpoint.')
            return slot_info(identifier, renew=True)
        if PENDING.full(): raise ValueError('The GPU queue is full. No task submitted; try again shortly.')
        SLOTS[identifier] = {'id': identifier, 'job_id': job, 'label': str(body.get('label', 'Caretaker request'))[:80],
                             'status': 'queued', 'touched': time.monotonic(), 'released': threading.Event()}
        try: PENDING.put_nowait(('slot', identifier))
        except queue.Full:
            del SLOTS[identifier]
            raise ValueError('The GPU queue is full. No task submitted; try again shortly.') from None
        return slot_info(identifier)

def release_slot(identifier):
    with SLOTS_LOCK:
        slot = SLOTS.get(identifier)
        if not slot: return
        if slot['status'] == 'queued': slot['status'] = 'cancelled'
        slot['released'].set()

def serve_slot(identifier, runtime=None):
    global PEAK_INFERENCE
    with SLOTS_LOCK:
        slot = SLOTS[identifier]
        if slot['status'] == 'cancelled' or time.monotonic() - slot['touched'] > SLOT_TTL:
            slot['status'] = 'expired' if slot['status'] != 'cancelled' else 'cancelled'
            return
        slot['runtime'] = runtime
        slot['lock'] = threading.RLock()
        slot['status'] = 'active'
        PEAK_INFERENCE = max(PEAK_INFERENCE, sum(s['status'] == 'active' for s in SLOTS.values()))
    while not slot['released'].wait(.25):
        with SLOTS_LOCK:
            if time.monotonic() - slot['touched'] > SLOT_TTL: break
    # A lane remains owned until its in-flight request has really finished.
    with slot['lock'], SLOTS_LOCK:
        slot['status'] = 'released' if slot['released'].is_set() else 'expired'
        slot.pop('runtime', None)

@contextlib.contextmanager
def gpu_access(body):
    identifier = body.get('slot_id'); temporary = identifier is None
    if temporary:
        identifier = reserve({'request_id': str(uuid.uuid4()), 'job_id': body.get('job_id')})['id']
    try:
        if temporary:
            while slot_info(identifier, renew=True)['status'] == 'queued': time.sleep(.25)
        with SLOTS_LOCK:
            slot = SLOTS.get(identifier)
            if not slot or slot['status'] != 'active':
                raise ValueError('This GPU queue task is no longer active. Retry this operation.')
            lane_lock = slot['lock']
        with lane_lock:
            with SLOTS_LOCK:
                if slot['status'] != 'active':
                    raise ValueError('This GPU queue task is no longer active. Retry this operation.')
                if slot['job_id'] != body.get('job_id'): raise ValueError('GPU queue task does not match this checkpoint.')
                slot['touched'] = time.monotonic()
            yield slot.get('runtime')
    finally:
        if temporary: release_slot(identifier)

def process_next(runtime=None):
    kind, identifier = PENDING.get()
    try:
        if kind == 'train': train_job(identifier)  # Earlier local/test callers.
        else: serve_slot(identifier, runtime)
    finally: PENDING.task_done()

def training_next(runtime):
    global PEAK_TRAINING
    identifier = TRAIN_PENDING.get()
    with JOBS_LOCK:
        ACTIVE_TRAINING.add(identifier)
        PEAK_TRAINING = max(PEAK_TRAINING, len(ACTIVE_TRAINING))
    try:
        runtime.call('train', JOBS[identifier].copy())
    except Exception as error:
        job = JOBS[identifier].copy()
        job.update(status='failed', stage='Training worker failed', error=str(error)[:400], finished_at=time.time())
        store(job)
    finally:
        with JOBS_LOCK: ACTIVE_TRAINING.discard(identifier)
        TRAIN_PENDING.task_done()

def training_loop(runtime):
    while True: training_next(runtime)

def inference_loop(runtime):
    while True: process_next(runtime)

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def folder(identifier):
    if not re.fullmatch(r'train-[a-f0-9]{32}', identifier):
        raise ValueError('Invalid training job.')
    return ROOT / identifier

def store(job):
    path = folder(job['id']); path.mkdir(parents=True, exist_ok=True)
    # copyfile/write_text rather than chmod/rename: Object Storage is not POSIX.
    (path / 'job.json').write_text(json.dumps(job))
    with JOBS_LOCK: JOBS[job['id']] = job.copy()
    if STATUS_PIPE is not None: STATUS_PIPE.send(('progress', job.copy()))

def records(value):
    if not isinstance(value, list) or not 3 <= len(value) <= 400:
        raise ValueError('Send 3–400 chat training records.')
    for row in value:
        msgs = row.get('messages') if isinstance(row, dict) else None
        if not isinstance(msgs, list) or [m.get('role') for m in msgs] != ['system', 'user', 'assistant']:
            raise ValueError('Records need system, user and assistant messages.')
        if any(not isinstance(m.get('content'), str) or not 0 < len(m['content']) <= 4000 for m in msgs):
            raise ValueError('Keep each message between 1 and 4000 characters.')
        answer = json.loads(msgs[-1]['content'])
        if not isinstance(answer, dict) or set(answer) != {'action', 'equipment'} or any(not isinstance(v, str) for v in answer.values()):
            raise ValueError('Assistant examples need action and equipment JSON.')
    return value

def submit(body):
    if not READY: raise ValueError('The GPU worker is still warming its base model.')
    request = str(uuid.UUID(body['request_id'])).replace('-', '')
    identifier = 'train-' + request
    train, valid = records(body['train']), records(body['validation'])
    prompts = lambda rows: {r['messages'][1]['content'] for r in rows}
    if prompts(train) & prompts(valid): raise ValueError('Training and validation prompts must be separate.')
    data_hash = digest({'train': train, 'validation': valid})
    with ADMISSION_LOCK, JOBS_LOCK:
        if identifier in JOBS:
            if JOBS[identifier]['data_hash'] != data_hash: raise ValueError('This request ID already belongs to another pack.')
            return JOBS[identifier]
        if TRAIN_PENDING.full(): raise ValueError('The training worker queue is full. No job submitted; try again shortly.')
        job = {'id': identifier, 'status': 'queued', 'stage': 'Waiting for the warm GPU',
               'provider': 'serverless', 'model': MODEL, 'base_revision': REVISION,
               'created_at': time.time(), 'data_hash': data_hash,
               'train_sha256': digest(train), 'validation_sha256': digest(valid),
               'counts': {'train': len(train), 'validation': len(valid)}, 'epochs': 20,
               'progress': 0, 'queue_ahead': TRAIN_PENDING.qsize() + len(ACTIVE_TRAINING)}
        path = folder(identifier); path.mkdir(parents=True, exist_ok=True)
        (path / 'data.json').write_text(json.dumps({'train': train, 'validation': valid}))
        store(job); TRAIN_PENDING.put_nowait(identifier)
        return job.copy()

def prefix(messages):
    return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)

def encode(row):
    messages = row['messages']
    start = tokenizer(prefix(messages[:-1]), add_special_tokens=False)['input_ids']
    end = tokenizer(messages[-1]['content'] + tokenizer.eos_token, add_special_tokens=False)['input_ids']
    if len(start) + len(end) > 512: raise ValueError('A training example exceeds 512 tokens; shorten the report.')
    return {'input_ids': start + end, 'attention_mask': [1] * (len(start) + len(end)), 'labels': [-100] * len(start) + end}

def batch(rows):
    width = ((max(len(r['input_ids']) for r in rows) + 7) // 8) * 8
    return {k: torch.tensor([r[k] + [(-100 if k == 'labels' else tokenizer.pad_token_id if k == 'input_ids' else 0)] * (width - len(r[k])) for r in rows], device='cuda') for k in ('input_ids', 'attention_mask', 'labels')}

def load_adapter(identifier):
    job = JOBS.get(identifier)
    if not job:
        try: job = json.loads((folder(identifier) / 'job.json').read_text()); JOBS[identifier] = job
        except (OSError, ValueError): pass
    if not job or job['status'] != 'succeeded': raise ValueError('This training job has no completed checkpoint.')
    if identifier not in LOADED:
        clear_adapters()
        model.load_adapter(str(folder(identifier) / 'adapter'), adapter_name=identifier)
        LOADED.add(identifier)
    return job

def train_job(identifier):
    global CURRENT_JOB
    job = JOBS[identifier].copy()
    with LOCK:
        CURRENT_JOB = identifier
        try:
            data = json.loads((folder(identifier) / 'data.json').read_text())
            train, valid = [encode(r) for r in data['train']], [encode(r) for r in data['validation']]
            set_seed(42)
            clear_adapters()
            model.add_adapter(identifier, lora_config())
            LOADED.add(identifier); model.set_adapter(identifier); model.train(); model.config.use_cache = False
            params = [p for p in model.parameters() if p.requires_grad]
            optimizer = torch.optim.AdamW(params, lr=4e-4, weight_decay=0)
            steps = math.ceil(len(train) / 16) * job['epochs']; step = 0
            started = time.monotonic(); job.update(status='running', stage='Training your LoRA adapter', started_at=time.time()); store(job)
            import random
            for epoch in range(job['epochs']):
                random.shuffle(train)
                for i in range(0, len(train), 16):
                    optimizer.zero_grad(set_to_none=True)
                    loss = model(**batch(train[i:i+16])).loss
                    loss.backward(); torch.nn.utils.clip_grad_norm_(params, 1)
                    optimizer.step(); step += 1
                    lr = 4e-4 * (0.25 + 0.75 * (1 + math.cos(math.pi * step / steps)) / 2)
                    for group in optimizer.param_groups: group['lr'] = lr
                job.update(progress=round(100 * step / steps), epoch=epoch+1, loss=round(float(loss.detach()), 6)); store(job)
            model.eval()
            with torch.inference_mode():
                losses = [float(model(**batch(valid[i:i+16])).loss) for i in range(0, len(valid), 16)]
            model.config.use_cache = True
            local = Path('/tmp/caretaker-adapters') / identifier; local.mkdir(parents=True, exist_ok=True)
            model.save_pretrained(str(local), selected_adapters=[identifier], safe_serialization=True)
            source = local / identifier
            target = folder(identifier) / 'adapter'; target.mkdir(exist_ok=True)
            import shutil
            for name in ('adapter_config.json', 'adapter_model.safetensors'): shutil.copyfile(source / name, target / name)
            artifact = hashlib.sha256((target / 'adapter_model.safetensors').read_bytes()).hexdigest()
            job.update(status='succeeded', stage='Checkpoint ready to load', checkpoint_id=identifier,
                       artifact_hash=artifact, validation_loss=sum(losses)/len(losses),
                       training_seconds=round(time.monotonic()-started, 3), finished_at=time.time(), progress=100)
            store(job)
        except Exception as error:
            job.update(status='failed', stage='Training failed', error=str(error)[:400], finished_at=time.time()); store(job)
            print(json.dumps({'event': 'training-failed', 'id': identifier, 'type': type(error).__name__}), flush=True)
        finally:
            model.eval(); model.config.use_cache = True
            for p in model.parameters(): p.requires_grad_(False)
            torch.cuda.empty_cache()
            CURRENT_JOB = None

def model_generation(body):
    msgs = body.get('messages')
    if not isinstance(msgs, list) or len(msgs) != 2 or [m.get('role') for m in msgs] != ['system', 'user'] or any(not isinstance(m.get('content'), str) or len(m['content']) > 8000 for m in msgs):
        raise ValueError('Send one system instruction and one report.')
    temperature = float(body.get('temperature', 0)); maximum = int(body.get('max_tokens', 128))
    if not math.isfinite(temperature) or not 0 <= temperature <= 2 or not 16 <= maximum <= 512: raise ValueError('Invalid generation settings.')
    identifier = body.get('job_id')
    job = load_adapter(identifier) if identifier else None
    if job: model.set_adapter(identifier)
    model.eval(); tokenizer.padding_side = 'left'
    inputs = tokenizer(prefix(msgs), return_tensors='pt', add_special_tokens=False).to('cuda')
    if inputs['input_ids'].shape[1] > 768: raise ValueError('Keep the report and instructions short.')
    sampling = {'do_sample': temperature > 0}
    if temperature > 0: sampling.update(temperature=temperature, top_p=1.0, top_k=0)
    with (contextlib.nullcontext() if job else model.disable_adapter()), torch.inference_mode():
        output = model.generate(**inputs, max_new_tokens=maximum, pad_token_id=tokenizer.pad_token_id, **sampling)
    tokens = output[0, inputs['input_ids'].shape[1]:]
    text = tokenizer.decode(tokens, skip_special_tokens=True).strip()
    stopped = bool(len(tokens) and int(tokens[-1]) in model.generation_config.eos_token_id) if isinstance(model.generation_config.eos_token_id, list) else bool(len(tokens) and int(tokens[-1]) == tokenizer.eos_token_id)
    return {'id': 'inference-'+uuid.uuid4().hex, 'model': MODEL, 'job_id': identifier,
            'artifact_hash': job['artifact_hash'] if job else 'base:'+MODEL,
            'choices': [{'message': {'content': text}, 'finish_reason': 'stop' if stopped else 'length'}]}

def clear_adapters():
    # Bound VRAM use across long sessions instead of retaining every player's LoRA.
    model.set_adapter('reserved')
    for identifier in list(LOADED):
        model.delete_adapter(identifier)
        LOADED.remove(identifier)

def generation(body):
    with gpu_access(body) as runtime:
        return runtime.call('generate', body)

def initialize_model():
    global torch, tokenizer, model, LoraConfig, set_seed
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoTokenizer, AutoModelForCausalLM, set_seed
    torch.set_num_threads(1)
    assert torch.cuda.is_available(), 'Start this worker on a GPU.'
    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION, trust_remote_code=False)
    tokenizer.pad_token = tokenizer.eos_token
    base = AutoModelForCausalLM.from_pretrained(MODEL, revision=REVISION, torch_dtype=torch.bfloat16,
             trust_remote_code=False, attn_implementation='sdpa').to('cuda')
    model = get_peft_model(base, lora_config(), adapter_name='reserved')
    for parameter in model.parameters(): parameter.requires_grad_(False)

def model_process(connection, role):
    global STATUS_PIPE
    try:
        initialize_model()
        connection.send(('ready', {'role': role}))
    except Exception as error:
        connection.send(('error', 'Model initialization failed: '+str(error)[:300])); return
    while True:
        try: action, body = connection.recv()
        except EOFError: return
        try:
            if action == 'train':
                JOBS[body['id']] = body
                STATUS_PIPE = connection
                train_job(body['id'])
                STATUS_PIPE = None
                result = JOBS[body['id']]
            elif action == 'load':
                job = load_adapter(body)
                result = {k: job[k] for k in ('id','model','artifact_hash','checkpoint_id','train_sha256','validation_sha256')}
            elif action == 'generate': result = model_generation(body)
            else: raise ValueError('Unknown model operation.')
            connection.send(('result', result))
        except Exception as error:
            STATUS_PIPE = None
            connection.send(('error', str(error)[:400]))

class ModelProcess:
    """One private model, tokenizer, RNG and CUDA context per worker process."""
    def __init__(self, role):
        self.role = role
        self.lock = threading.RLock()
        self.process = None
        self.start()
    def start(self):
        context = multiprocessing.get_context('spawn')
        parent, child = context.Pipe()
        self.connection = parent
        self.process = context.Process(target=model_process, args=(child, self.role), daemon=True)
        self.process.start(); child.close()
        if not parent.poll(180):
            self.process.terminate(); raise RuntimeError('GPU model initialization timed out.')
        status, result = parent.recv()
        if status != 'ready': raise RuntimeError(result)
    def call(self, action, body):
        with self.lock:
            if not self.process.is_alive(): self.start()
            self.connection.send((action, body))
            deadline = time.monotonic() + (600 if action == 'train' else 120)
            while time.monotonic() < deadline:
                if not self.connection.poll(.25):
                    if not self.process.is_alive(): raise ValueError('An isolated GPU worker stopped; retry this operation.')
                    continue
                status, result = self.connection.recv()
                if status == 'progress':
                    with JOBS_LOCK: JOBS[result['id']] = result.copy()
                elif status == 'error': raise ValueError(result)
                else: return result
            self.process.terminate(); self.process.join(5)
            raise ValueError('An isolated GPU operation timed out; retry this operation.')

def gpu_memory():
    # nvidia-smi observes all model processes without creating another CUDA context.
    try:
        result = subprocess.run(['nvidia-smi', '--query-gpu=memory.total,memory.used,utilization.gpu',
                 '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=2)
        total, used, utilization = (int(v.strip()) for v in result.stdout.splitlines()[0].split(','))
        return {'total_mib': total, 'used_mib': used, 'utilization_percent': utilization}
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired): return {}

def health():
    with SLOTS_LOCK: active = sum(s['status'] == 'active' for s in SLOTS.values())
    return {'ready': READY, 'model': MODEL, 'base_revision': REVISION, 'queue_version': 2,
            'queued': PENDING.qsize() + TRAIN_PENDING.qsize(), 'provider': 'Nebius Serverless AI',
            'capacity': {'training': TRAINING_WORKERS, 'inference': INFERENCE_WORKERS},
            'active': {'training': len(ACTIVE_TRAINING), 'inference': active},
            'peak': {'training': PEAK_TRAINING, 'inference': PEAK_INFERENCE}, 'gpu': gpu_memory()}

class Handler(BaseHTTPRequestHandler):
    def send(self, data, status=200):
        raw = json.dumps(data).encode(); self.send_response(status); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def authorized(self):
        return bool(TOKEN and hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer '+TOKEN))
    def do_GET(self):
        if not self.authorized(): self.send({'error':'Unauthorized'},401); return
        if self.path == '/healthz': self.send(health()); return
        if self.path.startswith('/slots/'):
            try: self.send(slot_info(self.path.removeprefix('/slots/'), renew=True))
            except ValueError as error: self.send({'error': str(error)},404)
            return
        if self.path.startswith('/jobs/'):
            job = JOBS.get(self.path.removeprefix('/jobs/'))
            if job and job['status'] == 'queued': job = {**job, 'queue_ahead': training_ahead(job['id'])}
            self.send(job if job else {'error':'Job not found'}, 200 if job else 404); return
        self.send({'error':'Not found'},404)
    def do_POST(self):
        if not self.authorized(): self.send({'error':'Unauthorized'},401); return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 2_000_000: raise ValueError('Send a small training pack or inference request.')
            body = json.loads(self.rfile.read(length))
            if self.path == '/jobs': self.send(submit(body),202)
            elif self.path == '/slots': self.send(reserve(body),202)
            elif self.path == '/slots/release':
                release_slot(body['slot_id']); self.send({'released':True})
            elif self.path == '/v1/chat/completions': self.send(generation(body))
            elif self.path == '/load':
                with gpu_access(body) as runtime: job = runtime.call('load', body['job_id'])
                self.send({**job, 'ready':True})
            else: self.send({'error':'Not found'},404)
        except (ValueError, KeyError, TypeError) as error: self.send({'error':str(error)},400)
        except Exception: self.send({'error':'GPU worker request failed. Inspect the worker logs.'},500)
    def log_message(self,*args): pass

def lora_config():
    return LoraConfig(r=16, lora_alpha=32, lora_dropout=0, bias='none', task_type='CAUSAL_LM', target_modules=['q_proj','k_proj','v_proj','o_proj','gate_proj','up_proj','down_proj'])

def main():
    global READY
    if not TOKEN: raise SystemExit('Set CARETAKER_WORKER_TOKEN before starting the worker.')
    if not 1 <= TRAINING_WORKERS <= 8 or not 1 <= INFERENCE_WORKERS <= 12:
        raise SystemExit('Configure 1–8 training workers and 1–12 inference workers for available GPU memory.')
    ROOT.mkdir(parents=True, exist_ok=True)
    for path in ROOT.glob('train-*/job.json'):
        try:
            job = json.loads(path.read_text())
            if job['status'] in ('queued','running'): job.update(status='failed',stage='Worker restarted before training finished; start a new training request.')
            JOBS[job['id']] = job
        except (OSError,ValueError,KeyError): continue
    server = ThreadingHTTPServer(('0.0.0.0',8000),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    # Load sequentially to avoid multiplying temporary CPU RAM during model startup.
    for role, count, loop in (('training', TRAINING_WORKERS, training_loop), ('inference', INFERENCE_WORKERS, inference_loop)):
        for _ in range(count):
            runtime = ModelProcess(role); RUNTIMES.append(runtime)
            threading.Thread(target=loop,args=(runtime,),daemon=True).start()
    READY = True
    print(json.dumps({'event':'warm-worker-ready','model':MODEL,'capacity':health()['capacity']}),flush=True)
    threading.Event().wait()

if __name__ == '__main__': main()
