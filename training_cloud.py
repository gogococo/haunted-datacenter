"""Server-side client for a warm Serverless trainer. No credentials in saves."""
import hashlib,json,os,urllib.request,urllib.error,urllib.parse,uuid
from tokenfactory import NoRedirect

def configured(): return bool(os.environ.get('CARETAKER_WORKER_URL') and os.environ.get('CARETAKER_WORKER_TOKEN'))

def api(path, body=None):
    base=os.environ.get('CARETAKER_WORKER_URL','').rstrip('/'); parsed=urllib.parse.urlparse(base)
    if parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith('.nebius.cloud') or parsed.username or parsed.password:
        raise ValueError('Configure the warm caretaker worker HTTPS endpoint before the shift.')
    req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Authorization':'Bearer '+os.environ.get('CARETAKER_WORKER_TOKEN',''),'Content-Type':'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=75 if path.endswith('completions') else 20) as response:return json.load(response)
    except urllib.error.HTTPError as error:
        try: message=json.load(error).get('error','Worker request failed.')
        except (ValueError,AttributeError): message='Worker request failed. Check its readiness and logs.'
        raise ValueError(str(message)[:500]) from None
    except OSError:raise ValueError('The training GPU is not answering. Check the warm worker before retrying.') from None

def digest(rows):return hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def submit(n, folder, pack_hash):
    train,valid=([json.loads(line) for line in (folder/(name+'.jsonl')).read_text().splitlines() if line.strip()] for name in ('train','validation'))
    request=n.setdefault('worker_request',str(uuid.uuid4()))
    job=api('/jobs',{'request_id':request,'train':train,'validation':valid})
    if job.get('train_sha256')!=digest(train) or job.get('validation_sha256')!=digest(valid):raise ValueError('The training worker receipt does not match this pack.')
    return {**job,'provider':'serverless','pack_hash':pack_hash}

def refresh(n):
    current=n['submission'];job=api('/jobs/'+urllib.parse.quote(current['id'],safe=''))
    if any(job.get(k)!=current.get(k) for k in ('id','train_sha256','validation_sha256')):raise ValueError('The worker returned another training job.')
    current.update(job)
    return job

def load(n):
    job=refresh(n)
    if job['status']!='succeeded':raise ValueError('Wait for your training job to finish before loading its checkpoint.')
    receipt=api('/load',{'job_id':job['id']})
    if receipt.get('id')!=job['id'] or receipt.get('artifact_hash')!=job.get('artifact_hash'):raise ValueError('The serving worker did not verify this job’s checkpoint.')
    n['job']=job.copy();n['runner']={**receipt,'active':True,'provider':'serverless','job_id':job['id']};n['route']='finetuned';n['report']=None;n.pop('final',None)
    n['config']['base_model']=job['model']
    return 'Your new adapter is loaded on the warm GPU. Run the Mac mini practical exam.'

def completion(n,prompt,baseline=False):
    active=not baseline and n.get('route')=='finetuned' and (n.get('runner') or {}).get('active')
    job=n.get('submission') or {};cfg=n['config']
    result=api('/v1/chat/completions',{'messages':[{'role':'system','content':cfg['system']},{'role':'user','content':prompt}], 'temperature':cfg['temperature'],'max_tokens':cfg['max_tokens'],'job_id':job.get('id') if active else None})
    if active and (result.get('job_id')!=job['id'] or result.get('artifact_hash')!=n['runner']['artifact_hash']):raise ValueError('The response did not use your verified checkpoint.')
    choice=result['choices'][0]
    return {'output':choice['message']['content'],'finish_reason':choice['finish_reason'],'model':result['model']+(' · your Serverless adapter' if active else ' · base weights'),'request_id':result['id']}
