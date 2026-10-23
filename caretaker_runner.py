#!/usr/bin/env python3
"""Optional local serving for a real Token Factory LoRA checkpoint. No API key needed here."""
import argparse,json,threading,time,contextlib,hashlib
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

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--receipt',required=True);parser.add_argument('--port',type=int,default=8770);args=parser.parse_args()
 receipt=json.loads(Path(args.receipt).read_text())
 for item in receipt['files']:
  path=Path(receipt['adapter_dir'])/item['name']
  if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Checkpoint file changed since validation: '+item['name'])
 import torch
 from transformers import AutoTokenizer,AutoModelForCausalLM
 torch.set_num_threads(4);device='mps' if torch.backends.mps.is_available() else 'cpu'
 tokenizer=AutoTokenizer.from_pretrained(receipt['base_dir'],local_files_only=True)
 base=AutoModelForCausalLM.from_pretrained(receipt['base_dir'],local_files_only=True,dtype=torch.float16 if device=='mps' else torch.float32).to(device).eval()
 model=load_checked_adapter(base,receipt['adapter_dir']).to(device).eval();lock=threading.Lock()
 # Hash the files actually loaded, not a label supplied by the game browser.
 hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(receipt['adapter_dir']).glob('adapter*') if p.is_file()}
 artifact_hash=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
 health={k:receipt[k] for k in ('job_id','model','training_file','validation_file','checkpoint_id','recipe_hash')};health.update(ready=True,device=device,artifact_hash=artifact_hash)
 class Handler(BaseHTTPRequestHandler):
  def send(self,obj,status=200):
   data=json.dumps(obj).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
  def do_GET(self):self.send(health) if self.path=='/health' else self.send({'error':'Not found'},404)
  def do_POST(self):
   if self.path!='/v1/chat/completions':self.send({'error':'Not found'},404);return
   try:
    size=int(self.headers.get('Content-Length',0))
    if size>20000:raise ValueError('Request too large')
    body=json.loads(self.rfile.read(size));messages=body['messages'];limit=int(body.get('max_tokens',64));temp=float(body.get('temperature',0));use_adapter=body.get('use_adapter',True)
    if not 1<=limit<=512 or not 0<=temp<=2 or type(use_adapter) is not bool:raise ValueError('Invalid generation settings')
    text=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True,enable_thinking=False)
    with lock,torch.inference_mode(),(contextlib.nullcontext() if use_adapter else model.disable_adapter()):
     inputs=tokenizer(text,return_tensors='pt').to(device);kwargs={'max_new_tokens':limit,'do_sample':temp>0,'pad_token_id':tokenizer.eos_token_id}
     if temp>0:kwargs['temperature']=temp
     output=model.generate(**inputs,**kwargs);tokens=output[0,inputs['input_ids'].shape[1]:];reply=tokenizer.decode(tokens,skip_special_tokens=True).strip()
    eos=tokenizer.eos_token_id;finished=len(tokens)<limit or int(tokens[-1]) in ([eos] if isinstance(eos,int) else eos)
    self.send({'id':'local-'+str(time.time_ns()),'model':receipt['model']+(' + Token Factory LoRA' if use_adapter else ' · base weights'),'choices':[{'message':{'role':'assistant','content':reply},'finish_reason':'stop' if finished else 'length'}],'usage':{'prompt_tokens':int(inputs['input_ids'].shape[1]),'completion_tokens':len(tokens)},'artifact_hash':artifact_hash,'use_adapter':use_adapter})
   except Exception as error:self.send({'error':type(error).__name__+': '+str(error)[:200]},400)
  def log_message(self,*args):pass
 print('Caretaker runner: http://127.0.0.1:'+str(args.port)+' · '+receipt['model']+' · '+device,flush=True)
 ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
if __name__=='__main__':main()
