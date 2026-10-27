#!/usr/bin/env python3
"""Warm, authenticated Serverless GPU trainer and job-scoped LoRA inference.

Start once before a session. Training and generation share one model and lock;
every request explicitly selects a job's adapter (or the unchanged base).
"""
import contextlib, hashlib, hmac, json, math, os, queue, re, threading, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MODEL = 'Qwen/Qwen3-0.6B'
REVISION = 'c1899de289a04d12100db370d81485cdf75e47ca'
ROOT = Path(os.environ.get('TRAINING_DATA_DIR', '/mnt/data/warm-caretaker'))
TOKEN = os.environ.get('CARETAKER_WORKER_TOKEN', '')
LOCK = threading.RLock()
JOBS_LOCK = threading.RLock()
JOBS = {}
PENDING = queue.Queue(maxsize=8)
READY = False
LOADED = set()
CURRENT_JOB = None

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
    with JOBS_LOCK:
        if identifier in JOBS:
            if JOBS[identifier]['data_hash'] != data_hash: raise ValueError('This request ID already belongs to another pack.')
            return JOBS[identifier]
        if PENDING.full(): raise ValueError('The training worker queue is full. No job submitted; try again shortly.')
        job = {'id': identifier, 'status': 'queued', 'stage': 'Waiting for the warm GPU',
               'provider': 'serverless', 'model': MODEL, 'base_revision': REVISION,
               'created_at': time.time(), 'data_hash': data_hash,
               'train_sha256': digest(train), 'validation_sha256': digest(valid),
               'counts': {'train': len(train), 'validation': len(valid)}, 'epochs': 20,
               'progress': 0, 'queue_ahead': PENDING.qsize() + int(CURRENT_JOB is not None)}
        path = folder(identifier); path.mkdir(parents=True, exist_ok=True)
        (path / 'data.json').write_text(json.dumps({'train': train, 'validation': valid}))
        store(job); PENDING.put(identifier)
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
    if not job or job['status'] != 'succeeded': raise ValueError('This training job has no completed checkpoint.')
    if identifier not in LOADED:
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

def generation(body):
    msgs = body.get('messages')
    if not isinstance(msgs, list) or len(msgs) != 2 or [m.get('role') for m in msgs] != ['system', 'user'] or any(not isinstance(m.get('content'), str) or len(m['content']) > 8000 for m in msgs):
        raise ValueError('Send one system instruction and one report.')
    temperature = float(body.get('temperature', 0)); maximum = int(body.get('max_tokens', 128))
    if not math.isfinite(temperature) or not 0 <= temperature <= 2 or not 16 <= maximum <= 512: raise ValueError('Invalid generation settings.')
    identifier = body.get('job_id')
    # Inference waits only briefly instead of hiding a training queue in a request timeout.
    if not LOCK.acquire(timeout=2): raise ValueError('The GPU is training another caretaker. Retry inference when it finishes.')
    try:
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
    finally: LOCK.release()

class Handler(BaseHTTPRequestHandler):
    def send(self, data, status=200):
        raw = json.dumps(data).encode(); self.send_response(status); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def authorized(self):
        return bool(TOKEN and hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer '+TOKEN))
    def do_GET(self):
        if not self.authorized(): self.send({'error':'Unauthorized'},401); return
        if self.path == '/healthz': self.send({'ready': READY, 'model': MODEL, 'base_revision': REVISION, 'queued': PENDING.qsize(), 'provider': 'Nebius Serverless AI'}); return
        if self.path.startswith('/jobs/'):
            job = JOBS.get(self.path.removeprefix('/jobs/'))
            self.send(job if job else {'error':'Job not found'}, 200 if job else 404); return
        self.send({'error':'Not found'},404)
    def do_POST(self):
        if not self.authorized(): self.send({'error':'Unauthorized'},401); return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 2_000_000: raise ValueError('Send a small training pack or inference request.')
            body = json.loads(self.rfile.read(length))
            if self.path == '/jobs': self.send(submit(body),202)
            elif self.path == '/v1/chat/completions': self.send(generation(body))
            elif self.path == '/load':
                with LOCK: job = load_adapter(body['job_id'])
                self.send({**{k:job[k] for k in ('id','model','artifact_hash','checkpoint_id','train_sha256','validation_sha256')}, 'ready':True})
            else: self.send({'error':'Not found'},404)
        except (ValueError, KeyError, TypeError) as error: self.send({'error':str(error)},400)
        except Exception: self.send({'error':'GPU worker request failed. Inspect the worker logs.'},500)
    def log_message(self,*args): pass

def lora_config():
    return LoraConfig(r=16, lora_alpha=32, lora_dropout=0, bias='none', task_type='CAUSAL_LM', target_modules=['q_proj','k_proj','v_proj','o_proj','gate_proj','up_proj','down_proj'])

def main():
    global torch, tokenizer, model, LoraConfig, set_seed, READY
    if not TOKEN: raise SystemExit('Set CARETAKER_WORKER_TOKEN before starting the worker.')
    from peft import LoraConfig, get_peft_model
    from transformers import AutoTokenizer, AutoModelForCausalLM, set_seed
    import torch
    ROOT.mkdir(parents=True, exist_ok=True)
    for path in ROOT.glob('train-*/job.json'):
        try:
            job = json.loads(path.read_text())
            if job['status'] in ('queued','running'): job.update(status='failed',stage='Worker restarted before training finished; start a new training request.')
            JOBS[job['id']] = job
        except (OSError,ValueError,KeyError): continue
    server = ThreadingHTTPServer(('0.0.0.0',8000),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    torch.set_num_threads(8); assert torch.cuda.is_available(), 'Start this worker on a GPU.'
    tokenizer = AutoTokenizer.from_pretrained(MODEL,revision=REVISION,trust_remote_code=False); tokenizer.pad_token=tokenizer.eos_token
    base = AutoModelForCausalLM.from_pretrained(MODEL,revision=REVISION,torch_dtype=torch.bfloat16,trust_remote_code=False,attn_implementation='sdpa').to('cuda')
    model = get_peft_model(base,lora_config(),adapter_name='reserved')
    for p in model.parameters(): p.requires_grad_(False)
    READY = True
    print(json.dumps({'event':'warm-worker-ready','model':MODEL,'device':torch.cuda.get_device_name()}),flush=True)
    while True:
        identifier = PENDING.get()
        train_job(identifier); PENDING.task_done()

if __name__ == '__main__': main()
