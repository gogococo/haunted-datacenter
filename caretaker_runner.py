#!/usr/bin/env python3
"""Optional local serving for a real Token Factory LoRA checkpoint. No API key needed here."""
import argparse,json,threading,time,contextlib,hashlib,secrets,os
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler

def load_checked_adapter(base,adapter_dir):
 """Load Token Factory's unwrapped tensor names and reject partial adapters."""
 import torch
 from peft import LoraConfig,get_peft_model
 from peft.utils.save_and_load import set_peft_model_state_dict
 from safetensors.torch import load_file
 config=LoraConfig.from_pretrained(adapter_dir,local_files_only=True)
 model=get_peft_model(base,config)
 raw=load_file(str(Path(adapter_dir)/'adapter_model.safetensors'),device='cpu')
 if not raw or any('.lora_' not in key for key in raw):raise ValueError('Expected a LoRA-only checkpoint.')
 weights={('base_model.model.'+key if key.startswith('model.') else key):value for key,value in raw.items()}
 result=set_peft_model_state_dict(model,weights)
 missing=[key for key in result.missing_keys if '.lora_' in key]
 if missing or result.unexpected_keys:raise ValueError('Adapter weights did not fully load: '+str(len(missing))+' missing, '+str(len(result.unexpected_keys))+' unexpected.')
 parameters=dict(model.named_parameters());loaded=set()
 for key,tensor in weights.items():
  name=key.replace('.lora_A.weight','.lora_A.default.weight').replace('.lora_B.weight','.lora_B.default.weight')
  parameter=parameters.get(name)
  if parameter is None or not torch.equal(parameter.detach().cpu(),tensor.to(parameter.dtype)):raise ValueError('Loaded adapter differs from checkpoint tensor '+key)
  loaded.add(name)
 if loaded!={name for name in parameters if '.lora_' in name}:raise ValueError('Checkpoint does not cover every adapter parameter.')
 return model.eval()

def verified_receipt(path):
 receipt=json.loads(Path(path).read_text())
 if {x['name'] for x in receipt['files']}!={'adapter_model.safetensors','adapter_config.json'}:raise ValueError('Unexpected checkpoint files.')
 for item in receipt['files']:
  file=Path(receipt['adapter_dir'])/item['name']
  if hashlib.sha256(file.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Checkpoint changed since preparation.')
 return receipt

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--receipt');parser.add_argument('--base-dir');parser.add_argument('--model',default='Qwen/Qwen3-0.6B');parser.add_argument('--runtime',default=str(Path(__file__).resolve().parent/'.runtime'));parser.add_argument('--port',type=int,default=8770);args=parser.parse_args()
 receipt=verified_receipt(args.receipt) if args.receipt else None
 if not receipt and not args.base_dir:parser.error('Provide --base-dir for a fresh caretaker, or --receipt for a prepared checkpoint.')
 base_dir=str(Path(receipt['base_dir'] if receipt else args.base_dir).resolve());model_id=receipt['model'] if receipt else args.model
 runtime=Path(args.runtime).resolve();control_dir=runtime/'caretaker';control_dir.mkdir(parents=True,exist_ok=True)
 token=secrets.token_urlsafe(32);control=control_dir/'runner-control.json'
 control.write_text(json.dumps({'token':token,'model':model_id,'base_dir':base_dir}));os.chmod(control,0o600)
 import torch
 from transformers import AutoTokenizer,AutoModelForCausalLM
 torch.set_num_threads(4);device='mps' if torch.backends.mps.is_available() else 'cpu'
 tokenizer=AutoTokenizer.from_pretrained(base_dir,local_files_only=True)
 def load(receipt=None):
  base=AutoModelForCausalLM.from_pretrained(base_dir,local_files_only=True,dtype=torch.float16 if device=='mps' else torch.float32).to(device).eval()
  if not receipt:return base,{'ready':True,'model':model_id,'device':device,'artifact_hash':'base:'+model_id,'has_adapter':False}
  model=load_checked_adapter(base,receipt['adapter_dir']).to(device).eval()
  hashes={x['name']:x['sha256'] for x in receipt['files']}
  health={k:receipt[k] for k in ('job_id','model','training_file','validation_file','checkpoint_id','recipe_hash')}
  health.update(ready=True,device=device,artifact_hash=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest(),has_adapter=True)
  return model,health
 model,health=load(receipt);lock=threading.Lock()
 class Handler(BaseHTTPRequestHandler):
  def send(self,obj,status=200):
   data=json.dumps(obj).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
  def do_GET(self):
   with lock:self.send(health) if self.path=='/health' else self.send({'error':'Not found'},404)
  def do_POST(self):
   nonlocal model,health
   if self.path not in ('/v1/chat/completions','/v1/checkpoints/load'):self.send({'error':'Not found'},404);return
   try:
    size=int(self.headers.get('Content-Length',0))
    if not 0<=size<=20000:raise ValueError('Request too large')
    body=json.loads(self.rfile.read(size))
    if self.path=='/v1/checkpoints/load':
     if not secrets.compare_digest(self.headers.get('X-Runner-Token',''),token):self.send({'error':'Runner control token required'},403);return
     path=Path(body['receipt']).resolve()
     try:path.relative_to(runtime)
     except ValueError:raise ValueError('Checkpoint receipts must be inside the configured runtime folder.')
     candidate=verified_receipt(path)
     if candidate['model']!=model_id or str(Path(candidate['base_dir']).resolve())!=base_dir:raise ValueError('Checkpoint uses a different base model.')
     with lock:
      replacement,new_health=load(candidate)
      model,health=replacement,new_health
      if device=='mps':torch.mps.empty_cache()
      self.send(health)
     return
    messages=body['messages'];limit=int(body.get('max_tokens',64));temp=float(body.get('temperature',0));use_adapter=body.get('use_adapter',True)
    if not 1<=limit<=512 or not 0<=temp<=2 or type(use_adapter) is not bool:raise ValueError('Invalid generation settings')
    text=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True,enable_thinking=False)
    with lock,torch.inference_mode():
     if use_adapter and not health['has_adapter']:raise ValueError('Load your completed training checkpoint first.')
     context=model.disable_adapter() if health['has_adapter'] and not use_adapter else contextlib.nullcontext()
     with context:
      inputs=tokenizer(text,return_tensors='pt').to(device);kwargs={'max_new_tokens':limit,'do_sample':temp>0,'pad_token_id':tokenizer.eos_token_id}
      if temp>0:kwargs['temperature']=temp
      output=model.generate(**inputs,**kwargs);tokens=output[0,inputs['input_ids'].shape[1]:];reply=tokenizer.decode(tokens,skip_special_tokens=True).strip()
     identity=dict(health)
    eos=tokenizer.eos_token_id;finished=len(tokens)<limit or int(tokens[-1]) in ([eos] if isinstance(eos,int) else eos)
    self.send({'id':'local-'+str(time.time_ns()),'model':model_id+(' + Token Factory LoRA' if use_adapter else ' · base weights'),'choices':[{'message':{'role':'assistant','content':reply},'finish_reason':'stop' if finished else 'length'}],'usage':{'prompt_tokens':int(inputs['input_ids'].shape[1]),'completion_tokens':len(tokens)},'artifact_hash':identity['artifact_hash'],'use_adapter':use_adapter})
   except Exception as error:self.send({'error':'Checkpoint or inference request failed ('+type(error).__name__+'). Check the runner log.'},400)
  def log_message(self,*args):pass
 print('Caretaker runner: http://127.0.0.1:'+str(args.port)+' · '+model_id+' · '+device,flush=True)
 ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
if __name__=='__main__':main()
