#!/usr/bin/env python3
"""Real Token Factory workflow. No automatic or implicit cloud mutations.
Commands train/deploy/cancel/delete perform exactly the named API operation.
Custom-weight registration is account-dependent and is performed in the console.
"""
import argparse, hashlib, json, os, sys, time, urllib.error, urllib.parse, urllib.request, uuid
from pathlib import Path
import content
ROOT=Path(__file__).resolve().parent; RT=ROOT/'.runtime'; RT.mkdir(exist_ok=True)
CONTROL='https://api.tokenfactory.nebius.com'

def write(name,data):
    p=RT/name;p.write_text(json.dumps(data,indent=2)+'\n');return p

def key():
    value=os.environ.get('NEBIUS_API_KEY') or os.environ.get('NEBIUS_TOKEN_FACTORY_KEY')
    if not value: raise ValueError('Set NEBIUS_API_KEY in your terminal. Do not paste it into the browser.')
    return value

class TokenFactoryError(ValueError):
    def __init__(self,status,message):
        self.status=status
        super().__init__(message)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def api(path,method='GET',payload=None,base=CONTROL,raw=None,content_type='application/json'):
    if urllib.parse.urlparse(base).scheme!='https' or urllib.parse.urlparse(base).hostname not in ('api.tokenfactory.nebius.com','api.tokenfactory.eu-west1.nebius.com','api.tokenfactory.us-central1.nebius.com'): raise ValueError('Use an official Token Factory HTTPS API base URL.')
    body=raw if raw is not None else json.dumps(payload).encode() if payload is not None else None
    req=urllib.request.Request(base.rstrip('/')+path,data=body,method=method,headers={'Authorization':'Bearer '+key(),'Content-Type':content_type,'Accept':'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=90) as r:
            data=r.read();return json.loads(data) if data else {}
    except urllib.error.HTTPError as e:
        # Do not echo response bodies: upstream responses may contain integration secrets.
        raise TokenFactoryError(e.code,f'Token Factory HTTP {e.code} for {method} {path}. Check account access, model/template compatibility and request fields. No automatic retry.') from None

def upload(file):
    boundary='----haunted'+uuid.uuid4().hex
    data=(f'--{boundary}\r\nContent-Disposition: form-data; name="purpose"\r\n\r\nfine-tune\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file.name}"\r\nContent-Type: application/jsonl\r\n\r\n').encode()+file.read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
    return api('/v1/files','POST',raw=data,content_type='multipart/form-data; boundary='+boundary)['id']

def safe_job(job):
    return {k:job.get(k) for k in ('id','status','model','trained_steps','total_steps','training_file','validation_file','created_at','finished_at')}

def items(data):
    if isinstance(data,list): return data
    for k in ('endpoints','data','items','models'):
        if isinstance(data.get(k),list): return data[k]
    raise ValueError('Unrecognized endpoint list response; inspect the API reference.')

def get_endpoint(identifier):
    # The current OpenAPI exposes GET list and PATCH/DELETE by ID, not GET by ID.
    for e in items(api('/v0/dedicated_endpoints')):
        if e.get('id',e.get('endpoint_id'))==identifier:return e
    raise ValueError('Endpoint ID was not returned by the account endpoint list.')

def prepare(source=None):
    if source: text=Path(source).read_text()
    elif (RT/'state.json').exists(): text=json.loads((RT/'state.json').read_text())['sources']['dataset']
    else: text=(ROOT/'data'/'seed-damaged.jsonl').read_text()
    counts=content.write_datasets(text)
    # The evaluation set is never uploaded or used for dataset expansion.
    prompts=lambda p:{json.loads(l)['messages'][1]['content'] for l in p.read_text().splitlines()}
    train=prompts(ROOT/'data'/'train.jsonl');valid=prompts(ROOT/'data'/'validation.jsonl');test={c['prompt'] for c in content.eval_cases()}
    if train&valid or train&test or valid&test:raise ValueError('Dataset split leakage detected.')
    return counts

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def run_train(args):
    prepare(args.seed)
    train=ROOT/'data'/'train.jsonl';valid=ROOT/'data'/'validation.jsonl'
    receipt={'created_at':time.time(),'model':args.model,'train_sha256':digest(train),'validation_sha256':digest(valid),'status':'uploading'}
    receipt_path=write('training-pending.json',receipt)
    receipt['training_file']=upload(train);write('training-pending.json',receipt)
    receipt['validation_file']=upload(valid);write('training-pending.json',receipt)
    payload={'model':args.model,'training_file':receipt['training_file'],'validation_file':receipt['validation_file'],'suffix':'night-operator','seed':42,'hyperparameters':{'n_epochs':args.epochs,'batch_size':16,'learning_rate':args.learning_rate,'lora':True,'lora_r':16,'lora_alpha':16,'lora_dropout':0.05,'context_length':8192,'packing':True}}
    job=api('/v1/fine_tuning/jobs','POST',payload)
    receipt.update({'job_id':job['id'],'status':job['status'],'request':payload});write('training-'+job['id']+'.json',receipt)
    return safe_job(job)

def run_deploy(args):
    job=api('/v1/fine_tuning/jobs/'+urllib.parse.quote(args.job,safe=''))
    if job['status']!='succeeded':raise ValueError('A succeeded fine-tuning job is required.')
    plan=json.loads(Path(args.plan).read_text())
    for f in ('name','model_name','flavor_name','gpu_type','gpu_count','region','scaling','custom_weights_id'):
        if not plan.get(f):raise ValueError('Endpoint plan needs '+f)
    if plan['model_name']!=job['model']:raise ValueError('Endpoint base model must match the trained base model.')
    # Registration is manual. This links the declared weight ID to the job for review;
    # it cannot prove artifact lineage through the public API.
    response=api('/v0/dedicated_endpoints','POST',plan)
    endpoint=response.get('endpoint',response)
    identifier=endpoint.get('id',endpoint.get('endpoint_id'))
    if not identifier:raise ValueError('Create response omitted endpoint ID. Inspect the console before retrying.')
    receipt={'job_id':args.job,'endpoint_id':identifier,'custom_weights_id':plan['custom_weights_id'],'model':job['model'],'region':endpoint.get('region'),'created_at':time.time(),'provenance':'Host must verify registered weights came from this job; not independently verified by API.'}
    write('deployment-'+identifier+'.json',receipt)
    return {**receipt,'routing_key':endpoint.get('routing_key'),'deployment':endpoint.get('deployment')}

def infer(base,model,prompt):
    r=api('/chat/completions','POST',{'model':model,'messages':[{'role':'system','content':content.SYSTEM},{'role':'user','content':prompt}],'temperature':0,'max_tokens':100},base=base)
    return r['choices'][0]['message']['content']

def parse_output(output):
    # Exact structured result: prose and Markdown fences fail the contract.
    try: return json.loads(output)
    except (ValueError,TypeError):return None

def evaluate_cases(base,model,cases):
    results=[]
    for i,c in enumerate(cases,1):
        output=infer(base,model,c['prompt']); parsed=parse_output(output)
        results.append({'prompt':c['prompt'],'expected':c['expected'],'output':output,'passed':parsed==c['expected']})
        print(f'{model}: {i}/{len(cases)}',file=sys.stderr)
    return {'score':sum(r['passed'] for r in results),'total':len(results),'results':results}

def run_evaluate(args):
    job=api('/v1/fine_tuning/jobs/'+urllib.parse.quote(args.job,safe=''))
    if job['status']!='succeeded':raise ValueError('Training job must have succeeded.')
    if job['model']!=args.base_model:raise ValueError('Baseline model must be the same model used for training.')
    endpoint=get_endpoint(args.endpoint)
    receipt_path=RT/('deployment-'+args.endpoint+'.json')
    if not receipt_path.exists():raise ValueError('Missing deployment receipt. Use deploy, or document the console deployment in a receipt as described in README.')
    receipt=json.loads(receipt_path.read_text())
    if receipt['job_id']!=args.job or not endpoint.get('custom_weights_id') or endpoint['custom_weights_id']!=receipt['custom_weights_id']:raise ValueError('Job/registered-weight/endpoint metadata mismatch.')
    if endpoint['model_name']!=job['model']:raise ValueError('Dedicated endpoint base model differs from the trained base model.')
    if not endpoint.get('enabled') or endpoint.get('deployment',{}).get('ready_replicas',0)<1:raise ValueError('Dedicated endpoint has no ready replicas yet. Retry evaluation when ready.')
    routing=endpoint['routing_key']
    if not routing.startswith('dedicated/'):raise ValueError('Evaluation must use a dedicated routing key.')
    region=endpoint.get('region');default_bases={'eu-north1':CONTROL+'/v1','eu-west1':'https://api.tokenfactory.eu-west1.nebius.com/v1','us-central1':'https://api.tokenfactory.us-central1.nebius.com/v1'}
    inference_base=args.inference_base or default_bases.get(region)
    if not inference_base:raise ValueError('Pass --inference-base for this region, using the console-provided HTTPS API URL.')
    # Clear stale success before making requests so a failed new run cannot retain an old pass.
    write('live-report.json',{'passed':False,'status':'evaluation in progress','job_id':args.job,'endpoint_id':args.endpoint})
    cases=content.eval_cases()
    baseline=evaluate_cases(args.baseline_base,args.base_model,cases);write('baseline-'+args.job+'.json',baseline)
    tuned=evaluate_cases(inference_base,routing,cases);write('tuned-'+args.job+'.json',tuned)
    report={'passed':tuned['score']>=24 and tuned['score']-baseline['score']>=4,'score':tuned['score'],'total':len(cases),'baseline_score':baseline['score'],'improvement':tuned['score']-baseline['score'],'job_id':args.job,'endpoint_id':args.endpoint,'custom_weights_id':endpoint['custom_weights_id'],'routing_key':routing,'model':args.base_model,'checked_at':time.time(),'provenance':'Job success and endpoint weight ID checked via API. Host must verify weight registration links to the job checkpoint.','evaluation_scope':'27 novel phrasings of 9 known intents; small teaching benchmark, not a broad capability evaluation.'}
    write('live-report.json',report);return report

def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True)
    q=s.add_parser('prepare',help='Validate repaired browser seeds and write train/validation files');q.add_argument('--seed')
    s.add_parser('templates',help='Read available dedicated endpoint templates')
    q=s.add_parser('train',help='Upload dataset files and submit a real, billed fine-tuning job');q.add_argument('--model',required=True);q.add_argument('--seed');q.add_argument('--epochs',type=int,default=3);q.add_argument('--learning-rate',type=float,default=1e-5)
    q=s.add_parser('status',help='Read training status and checkpoints');q.add_argument('--job',required=True)
    q=s.add_parser('deploy',help='Create a real, billed dedicated endpoint with registered custom weights');q.add_argument('--job',required=True);q.add_argument('--plan',required=True)
    q=s.add_parser('endpoint',help='Read an endpoint from the account endpoint list');q.add_argument('--endpoint',required=True)
    q=s.add_parser('evaluate',help='Make 54 real inference requests and produce a measured comparison');q.add_argument('--job',required=True);q.add_argument('--endpoint',required=True);q.add_argument('--base-model',required=True);q.add_argument('--inference-base');q.add_argument('--baseline-base',default=CONTROL+'/v1')
    q=s.add_parser('cancel',help='Cancel the specified training job');q.add_argument('--job',required=True)
    q=s.add_parser('delete',help='Delete the specified dedicated endpoint');q.add_argument('--endpoint',required=True)
    args=p.parse_args()
    if args.command=='prepare':result=prepare(args.seed)
    elif args.command=='templates':result=api('/v0/dedicated_endpoints/templates')
    elif args.command=='train':result=run_train(args)
    elif args.command=='status':
        path='/v1/fine_tuning/jobs/'+urllib.parse.quote(args.job,safe='');job=api(path);result=safe_job(job)
        if job['status']=='succeeded':result['checkpoints']=api(path+'/checkpoints')
    elif args.command=='deploy':result=run_deploy(args)
    elif args.command=='endpoint':result=get_endpoint(args.endpoint)
    elif args.command=='evaluate':result=run_evaluate(args)
    elif args.command=='cancel':result=safe_job(api('/v1/fine_tuning/jobs/'+urllib.parse.quote(args.job,safe='')+'/cancel','POST'))
    else:result=api('/v0/dedicated_endpoints/'+urllib.parse.quote(args.endpoint,safe=''),'DELETE')
    print(json.dumps(result,indent=2))
if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,OSError,urllib.error.URLError) as e:print(str(e),file=sys.stderr);sys.exit(1)
