"""Room 2: real Token Factory operations and a small measured assessment.
No credential is serialized into game state. No simulated score unlocks this room.
"""
import base64,copy,hashlib,json,math,os,re,time,urllib.parse,urllib.request,threading
from pathlib import Path
import content,lessons,checkpoint_flow,training_cloud,tokenfactory as tf
ROOT=Path(__file__).resolve().parent
VERSION='noc-v4'
CAMERAS=[
 {'id':'west','title':'Camera 01 · GPU rack','equipment':'gpu_rack','fault':'fan_failure','expected':{'action':'restart_fans','equipment':'gpu_rack'}},
 {'id':'east','title':'Camera 02 · Cooling loop','equipment':'cooling_loop','fault':'coolant_leak','expected':{'action':'stop_pump','equipment':'cooling_loop'}},
 {'id':'healthy','title':'Camera 02 · Healthy GPU rack','equipment':'gpu_rack','fault':'healthy','expected':{'action':'leave_alone','equipment':'gpu_rack'}},
 {'id':'crypt','title':'Camera 03 · Exit door','equipment':'exit_door','fault':'locked_door','expected':{'action':'release_latch','equipment':'exit_door'}},
]
BASE='Qwen/Qwen3-30B-A3B-Instruct-2507'
DEFAULT_PROMPT=content.SYSTEM
LIVE_CASES=[
 {'prompt':'The GPU rack is getting hotter and its cooling fans are no longer turning.','expected':{'action':'restart_fans','equipment':'gpu_rack'}},
 {'prompt':'Liquid is escaping from the coolant pipe while the circulation pump keeps pushing more out.','expected':{'action':'stop_pump','equipment':'cooling_loop'}},
 {'prompt':'The emergency door cannot swing open because its locking latch is jammed shut.','expected':{'action':'release_latch','equipment':'exit_door'}},
]

def initial():
 return {'version':VERSION,'flow_version':3,'personality':None,'dialogue':None,'revision':0,'route':'untrained','config':{'temperature':1.2,'max_tokens':16,'system':DEFAULT_PROMPT,'base_model':BASE,'vision_model':''},'connection':None,'runner':None,'observations':{},'job':None,'endpoint':None,'report':None,'baseline':None,'operation':None,'probe':None,'probes':{},'lessons':{},'maintenance':{},'demonstrations':{},'submission':None}

def runner_call(path,payload=None,control_token=None):
 base=os.environ.get('CARETAKER_RUNNER_URL','http://127.0.0.1:8770').rstrip('/');u=urllib.parse.urlparse(base)
 if u.scheme!='http' or u.hostname not in ('127.0.0.1','localhost') or u.username or u.password:raise ValueError('The caretaker runner must use a local loopback HTTP URL.')
 request=urllib.request.Request(base+path,data=json.dumps(payload).encode() if payload is not None else None,headers={'Content-Type':'application/json',**({'X-Runner-Token':control_token} if control_token else {})})
 try:
  with urllib.request.build_opener(tf.NoRedirect).open(request,timeout=90 if path=='/v1/checkpoints/load' else 45 if payload is not None else 2) as response:return json.load(response)
 except urllib.error.HTTPError:raise ValueError('The caretaker runner rejected this checkpoint or inference request. Check the runner log.') from None
 except OSError:raise ValueError('The local caretaker runner is offline. Start caretaker_runner.py with the downloaded Token Factory checkpoint.') from None

def serving_id(n):
 if n.get('route')=='prompt':return n.get('prompt_model',BASE)
 if (n.get('runner') or {}).get('active'):return n['runner']['artifact_hash']
 return (n.get('endpoint') or {}).get('id')

def settings(values,old):
 out=old.copy()
 try:t=float(values.get('temperature',old['temperature']));m=int(values.get('max_tokens',old['max_tokens']))
 except (ValueError,TypeError):raise ValueError('Use a number for temperature and a whole number for the token limit.')
 if not math.isfinite(t) or not 0<=t<=2 or not 16<=m<=512:raise ValueError('Temperature must be 0–2 and the token limit 16–512.')
 system=str(values.get('system',old['system'])).strip()
 if not 1<=len(system)<=2000:raise ValueError('Keep caretaker instructions between 1 and 2,000 characters.')
 out.update(temperature=t,max_tokens=m,system=system)
 for key in ('base_model','vision_model'):
  if key in values:
   value=str(values[key]).strip()
   if len(value)>200:raise ValueError('Model identifier is too long.')
   out[key]=value
 return out

def base_for(endpoint=None):
 region=(endpoint or {}).get('region','eu-north1')
 hosts={'eu-north1':'https://api.tokenfactory.nebius.com/v1','eu-west1':'https://api.tokenfactory.eu-west1.nebius.com/v1','us-central1':'https://api.tokenfactory.us-central1.nebius.com/v1'}
 if region not in hosts:raise ValueError('This POC supports inference in eu-north1, eu-west1 and us-central1. Choose a supported region.')
 return hosts[region]

def completion(model,messages,temperature,max_tokens,endpoint=None):
 r=tf.api('/chat/completions','POST',{'model':model,'messages':messages,'temperature':temperature,'max_tokens':max_tokens},base=base_for(endpoint))
 c=r['choices'][0]
 return {'output':c['message'].get('content') or '', 'finish_reason':c.get('finish_reason'),'model':r.get('model',model),'request_id':r.get('id'),'usage':r.get('usage',{})}

def endpoint_summary(e):return {k:e.get(k) for k in ('id','name','model_name','routing_key','region','enabled','custom_weights_id','deployment')}

def connect(n):
 models=tf.items(tf.api('/v1/models'));eps=[endpoint_summary(e) for e in tf.items(tf.api('/v0/dedicated_endpoints'))]
 templates=tf.items(tf.api('/v0/dedicated_endpoints/templates'))
 ids=[m['id'] for m in models]
 vision=[e['routing_key'] for e in eps if any(t in e['model_name'].lower() for t in ('-vl','vision','minicpm')) and e.get('enabled')]
 vision += [m for m in ids if any(t in m.lower() for t in ('-vl','vision','minicpm','qwen3.5')) and m not in vision]
 n['connection']={'models':ids,'vision_models':vision,'endpoints':eps,'templates':templates,'checked_at':time.time()}
 if not n['config']['vision_model'] and vision:n['config']['vision_model']=vision[0]
 if training_cloud.configured():
  health=training_cloud.api('/healthz')
  if not health.get('ready'):raise ValueError('The training GPU is still warming up. Ask the host to finish its preflight.')
  n['training_provider']='serverless';n['config']['base_model']=health['model']
  return 'Token Factory cameras connected. Warm Serverless training GPU ready.'
 try:
  health=runner_call('/health');active=bool((n.get('runner') or {}).get('active') and n['runner'].get('artifact_hash')==health['artifact_hash'])
  n['runner']={**health,'active':True} if active else {**{k:health[k] for k in ('ready','model','device') if k in health},'active':False,'has_adapter':False,'artifact_hash':'base:'+health['model']}
  n['config']['base_model']=health['model'];n.pop('runner_problem',None)
 except ValueError as error:n['runner_problem']=str(error)
 return 'Connected to Token Factory. Camera and caretaker models are available.'

def camera_request(equipment,fault,allow_unknown=False):
 if equipment not in (*content.ZONES,'unknown') or fault not in (*content.VERBS,'healthy','unknown'):raise ValueError('Choose the equipment label and visible fault from the camera report.')
 if not allow_unknown and 'unknown' in (equipment,fault):raise ValueError('Check the image and identify the equipment and fault before asking the caretaker.')
 return 'Equipment: '+content.EQUIPMENT.get(equipment,'Unknown')+'. Observation: '+('Healthy; no repair required' if fault=='healthy' else content.FAULTS.get(fault,'Unknown fault'))+'.'

def vision(n,camera_id):
 camera=next((c for c in CAMERAS if c['id']==camera_id),None)
 if not camera:raise ValueError('Unknown camera.')
 model=n['config']['vision_model']
 if not model:raise ValueError('Connect Token Factory at the deployment rack first, then choose a vision model.')
 ep=next((e for e in (n.get('connection') or {}).get('endpoints',[]) if e['routing_key']==model),None)
 image=base64.b64encode((ROOT/'web'/'cameras'/(camera_id+'.png')).read_bytes()).decode()
 r=completion(model,[{'role':'system','content':'Inspect the equipment and physical fault in the image. Return only JSON with exactly three string keys: equipment (gpu_rack, cooling_loop, exit_door, or unknown), fault (fan_failure, coolant_leak, locked_door, healthy, or unknown), observation (one short sentence describing the visible evidence). A fan fault warning and heat indicate fan_failure. Water escaping from a cooling pipe indicates coolant_leak. A locked exit latch indicates locked_door. A green FANS RUNNING status and normal temperature indicate healthy. Do not prescribe a repair.'},{'role':'user','content':[{'type':'text','text':'Identify the equipment and visible fault. Describe the visual evidence.'},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+image}}]}],0,220,ep)
 try:
  text=r['output'].strip();text=re.sub(r'^```(?:json)?\s*|\s*```$','',text);parsed=json.loads(text)
  if set(parsed)!={'equipment','fault','observation'} or any(not isinstance(v,str) or not v.strip() or len(v)>700 for v in parsed.values()):raise ValueError()
  parsed['equipment']=parsed['equipment'].strip().lower();parsed['fault']=parsed['fault'].strip().lower()
  camera_request(parsed['equipment'],parsed['fault'],allow_unknown=True)
  request=camera_request(parsed['equipment'],parsed['fault'],allow_unknown=True)+' Visible evidence: '+parsed['observation']
 except (ValueError,TypeError):raise ValueError('The vision model did not return a readable camera report. Try inspection again or choose another vision model.')
 n.get('probes',{}).pop(camera_id,None)
 n.get('demonstrations',{}).pop(camera_id,None)
 n['observations'][camera_id]={**parsed,'request':request,'original_request':request,'reviewed':False,'camera':camera_id,'inference':r,'at':time.time()}
 return 'Token Factory vision read the camera. Compare its evidence with Alex’s old advice.'

def text_call(n,prompt,baseline=False):
 if n.get('training_provider')=='serverless' or (n.get('submission') or {}).get('provider')=='serverless':return training_cloud.completion(n,prompt,baseline)
 if n.get('route')=='prompt':return completion(n.get('prompt_model',BASE),[{'role':'system','content':n['config']['system']},{'role':'user','content':prompt}],n['config']['temperature'],n['config']['max_tokens'])
 if n.get('runner'):
  c=n['config'];r=runner_call('/v1/chat/completions',{'messages':[{'role':'system','content':c['system']},{'role':'user','content':prompt}],'temperature':c['temperature'],'max_tokens':c['max_tokens'],'use_adapter':bool(n['runner'].get('active') and not baseline)})

  if n['runner'].get('active') and not baseline and r.get('artifact_hash')!=n['runner'].get('artifact_hash'):raise ValueError('The serving checkpoint changed. Load your model and run its tests again.')
  choice=r['choices'][0];return {'output':choice['message'].get('content') or '', 'finish_reason':choice.get('finish_reason'),'model':r['model'],'request_id':r['id'],'usage':r.get('usage',{})}
 c=n['config'];ep=None if baseline else n.get('endpoint');model=ep['routing_key'] if ep else c['base_model']
 return completion(model,[{'role':'system','content':c['system']},{'role':'user','content':prompt}],c['temperature'],c['max_tokens'],ep)

def checks(response,expected):
 output=response['output'];parsed=tf.parse_output(output)
 shape=isinstance(parsed,dict) and set(parsed)=={'action','equipment'} and all(isinstance(v,str) for v in parsed.values())
 return {'brief':len(re.findall(r'\b\w+\b',output))<=30,'complete':response.get('finish_reason')=='stop','structured':shape,'correct':shape and parsed==expected}

def assess(n,progress=lambda x:None):
 if not n['connection']:raise ValueError('Connect Token Factory at the deployment rack first.')
 results=[]
 # Genuinely different reports, not the training reports with new prefixes.
 cases=LIVE_CASES+([{'prompt':'The GPU cooling fans are turning normally, the rack is cool, and every status light is green.','expected':{'action':'leave_alone','equipment':'gpu_rack'}}] if n.get('flow_version',2)>=3 else [])
 for i,c in enumerate(cases):
  group=[]
  for repeat in range(3):
   progress(f'Mac mini: request {i*3+repeat+1}/{len(cases)*3}')
   r=text_call(n,c['prompt']);item={'prompt':c['prompt'],'expected':c['expected'],**r,'checks':checks(r,c['expected'])};results.append(item);group.append(tf.parse_output(r['output']))
  consistent=all(isinstance(v,dict) for v in group) and all(v==group[0] for v in group)
  for item in results[-3:]:item['checks']['consistent']=consistent
 summary={k:all(x['checks'][k] for x in results) for k in ('brief','complete','structured','correct','consistent')}
 report={'results':results,'checks':summary,'passed':all(summary.values()),'at':time.time(),'route':n.get('route','untrained'),'config':copy.deepcopy(n['config']),'endpoint_id':(n.get('endpoint') or {}).get('id'),'serving_id':serving_id(n),'scope':f'{len(results)} real requests: {len(cases)} fresh reports repeated three times. A small teaching assessment, not a reliability guarantee.'}
 if n.get('baseline') is None or (not n.get('submission') and n.get('route')=='untrained'):n['baseline']=copy.deepcopy(report)
 n['report']=report;n.pop('final',None)
 return 'Mac mini finished. '+('Behavior checks passed.' if report['passed'] else 'Some checks need attention. Inspect the actual replies.')

def activate_backup(n,source):
 require_submission(n,source)
 if n.get('host_override',{}).get('kind')!='backup':raise ValueError('Alex’s earlier checkpoint is a host-only fallback.')
 if not n.get('baseline'):raise ValueError('Run the Mac mini on the base model first so you can compare the trained backup.')
 recipe=content.recipe_hash(source);health=runner_call('/health')
 if health.get('recipe_hash')!=recipe:raise ValueError('The repaired examples do not match this backup’s training recipe.')
 job=tf.api('/v1/fine_tuning/jobs/'+urllib.parse.quote(health['job_id'],safe=''))
 if job.get('status')!='succeeded' or job.get('model')!=health['model'] or job.get('training_file')!=health['training_file'] or job.get('validation_file')!=health['validation_file']:raise ValueError('Token Factory could not verify this backup’s completed training job.')
 checkpoints=tf.api('/v1/fine_tuning/jobs/'+urllib.parse.quote(health['job_id'],safe='')+'/checkpoints')['data']
 if not any(row['id']==health['checkpoint_id'] for row in checkpoints):raise ValueError('The backup checkpoint was not returned by this training job.')
 n['job']={**tf.safe_job(job),'restored':True,'recipe_hash':recipe};n['runner']={**health,'active':True};n['route']='finetuned';n['endpoint']=None;n['report']=None;n.pop('final',None)
 n['config']['base_model']=health['model'];n['config']['system']=content.SYSTEM
 return 'Real Token Factory checkpoint restored. This training ran before the episode; the next tests use its learned adapter live.'

def activate_prompt_route(n,source):
 require_submission(n,source)
 if n.get('host_override',{}).get('kind')!='prompt':raise ValueError('Prompting is a host-only comparison experiment.')
 if not n.get('baseline'):raise ValueError('Run the Mac mini baseline first, then compare the prompt profile.')
 rows,errors=content.validate_seed(source)
 if errors:raise ValueError('Repair the maintenance examples first.')
 examples='\n'.join(r['messages'][1]['content']+' → '+r['messages'][2]['content'] for r in [rows[0],rows[3],rows[6]])
 n['config']['system']=content.SYSTEM+' Use only these exact command pairs: restart_fans → gpu_rack; stop_pump → cooling_loop; release_latch → exit_door. A split cooling pipe belongs to cooling_loop. An emergency exit belongs to exit_door.\nMaintenance checklist examples:\n'+examples
 if n.get('runner'):n['runner']['active']=False
 n['route']='prompt';n['prompt_model']=BASE;n['config']['base_model']=BASE;n['report']=None;n.pop('final',None)
 return 'Prompt comparison profile restored. This route uses real Token Factory inference and does not use fine-tuned weights.'

def require_submission(n,source):
 submission=n.get('submission') or {}
 if not submission.get('id'):raise ValueError('Submit the real Token Factory training job at the desk first. Your trained model will be loaded at the generator-room terminal.')
 if submission.get('pack_hash')!=lessons.packet_hash(n,source):raise ValueError('The submitted training job belongs to a different training pack.')

def train(n,source,runtime):
 if n.get('flow_version',2)>=3 and not n.get('personality'):raise ValueError('Restore a personality cartridge before training the caretaker.')
 if n.get('training_submission_unknown'):raise ValueError('A training submission had an uncertain outcome. Check Token Factory before submitting another job.')
 if n.get('submission'):raise ValueError('This incident already submitted a training job. Refresh its status instead of submitting a duplicate.')
 if not n.get('baseline'):raise ValueError('Record the Mac mini baseline before training.')
 if n.get('flow_version',2)>=3 and (not n['baseline'].get('checks',{}).get('complete') or n['baseline'].get('config')!=n['config']):raise ValueError('Give the base model enough output tokens and measure it again with the current settings before training. Then compare learned weights using the same settings.')
 folder=runtime/'noc-training';folder.mkdir(exist_ok=True)
 counts=lessons.write_pack(n,source,folder)
 if n.get('training_provider')=='serverless':
  n['submission']=training_cloud.submit(n,folder,lessons.packet_hash(n,source))
  n['submission']['counts']=counts
  return 'Your real LoRA job is on the warm Serverless GPU. Check its progress, then load its checkpoint.'
 model=(n.get('runner') or {}).get('model') or 'Qwen/Qwen3-0.6B'
 files={name:tf.upload(folder/(name+'.jsonl')) for name in ('train','validation')}
 payload={'model':model,'training_file':files['train'],'validation_file':files['validation'],'suffix':'haunted-rehearsals','seed':42,
          'hyperparameters':{'n_epochs':10,'batch_size':16,'learning_rate':0.0002,'lora':True,'lora_r':16,'lora_alpha':32,'lora_dropout':0,'context_length':8192,'packing':True}}
 n['training_submission_unknown']=True;n['training_files']=files
 try:job=tf.api('/v1/fine_tuning/jobs','POST',payload)
 except tf.TokenFactoryError as e:
  if e.status in (400,401,403,404,422):n['training_submission_unknown']=False
  raise
 if not job.get('id'):raise ValueError('Training returned no job ID. Check Token Factory before retrying.')
 n['training_submission_unknown']=False
 n['submission']={**tf.safe_job(job),'counts':counts,'pack_hash':lessons.packet_hash(n,source)}
 return 'Real LoRA training submitted. Your three demonstrations are in the uploaded pack. Take the maintenance terminal to the generator room while it trains.'

def activate_own_checkpoint(n,source,runtime,progress,uploaded=None):
 if (n.get('submission') or {}).get('provider')=='serverless':
  require_submission(n,source)
  return training_cloud.load(n)
 require_submission(n,source)
 if not n.get('baseline'):raise ValueError('Measure the base caretaker before loading trained weights.')
 prepared=checkpoint_flow.prepare(n,source,runtime,progress,uploaded)
 if not prepared:return n['checkpoint_download']['message']
 receipt,job=prepared
 progress('Loading the adapter learned by your training job…')
 health=checkpoint_flow.reload_runner(runtime,receipt,runner_call)
 if health.get('model')!=job['model'] or health.get('checkpoint_id')!=json.loads(Path(receipt).read_text())['checkpoint_id'] or health.get('job_id')!=n['submission']['id'] or health.get('training_file')!=n['submission']['training_file'] or health.get('validation_file')!=n['submission']['validation_file']:raise ValueError('The loaded checkpoint does not belong to your submitted training job.')
 n['job']={**tf.safe_job(job),'recipe_hash':content.recipe_hash(source)};n['runner']={**health,'active':True};n['route']='finetuned';n['endpoint']=None;n['report']=None;n.pop('final',None);n.pop('host_override',None)
 n['config']['base_model']=health['model'];n['config']['system']=content.SYSTEM
 return 'Your submitted job’s trained checkpoint is active. Run the safety checks on the portable terminal.'

def require_own_model(n):
 override=n.get('host_override') or {}
 if override.get('kind')=='prompt' and n.get('route')=='prompt':return
 if override.get('kind')=='backup' and n.get('route')=='finetuned':return
 if n.get('route')!='finetuned' or (n.get('job') or {}).get('id')!=(n.get('submission') or {}).get('id'):raise ValueError('Load the checkpoint from your own training job before certification.')

def refresh_cloud(n):
 if (n.get('submission') or {}).get('provider')=='serverless':
  job=training_cloud.refresh(n)
  return job['stage']
 if n.get('submission'):
  job=tf.api('/v1/fine_tuning/jobs/'+urllib.parse.quote(n['submission']['id'],safe=''));n['submission'].update(tf.safe_job(job))
 if n.get('job'):
  job=tf.api('/v1/fine_tuning/jobs/'+urllib.parse.quote(n['job']['id'],safe=''));n['job'].update(tf.safe_job(job))
  if job['status']=='succeeded':n['checkpoints']=tf.api('/v1/fine_tuning/jobs/'+urllib.parse.quote(job['id'],safe='')+'/checkpoints')
 if n.get('endpoint'):n['endpoint'].update(endpoint_summary(tf.get_endpoint(n['endpoint']['id'])))
 return 'Cloud status refreshed.'

def deploy(n,body):
 refresh_cloud(n)
 if not n.get('job') or n['job']['status']!='succeeded':raise ValueError('A succeeded fine-tuning job is required before deployment.')
 if n.get('deployment_submission_unknown'):raise ValueError('A previous deployment had an uncertain outcome. Check Token Factory before creating another endpoint.')
 if n.get('endpoint'):raise ValueError('An endpoint is already linked. Refresh its status instead of creating another.')
 weights=str(body.get('weights','')).strip()
 if not weights or len(weights)>200:raise ValueError('Register this job’s checkpoint in Token Factory and enter its custom-weight ID.')
 template=next((t for t in n['connection']['templates'] if t['name']==n['job']['model']),None)
 flavor=str(body.get('flavor',''));gpu=str(body.get('gpu',''));region=str(body.get('region',''));count=int(body.get('count',1))
 cfg=(template or {}).get('flavors',{}).get(flavor,{}).get('available_configurations',{}).get('gpu_configurations',{}).get(gpu,{})
 if region not in cfg.get('allowed_regions',[]) or count not in cfg.get('allowed_gpu_counts',[]):raise ValueError('Choose a GPU, count and region supported by this model’s template.')
 base_for({'region':region})
 payload={'name':'haunted-caretaker-'+str(int(time.time())),'model_name':n['job']['model'],'flavor_name':flavor,'gpu_type':gpu,'gpu_count':count,'region':region,'scaling':{'min_replicas':1,'max_replicas':1},'custom_weights_id':weights}
 n['deployment_submission_unknown']=True
 try:result=tf.api('/v0/dedicated_endpoints','POST',payload)
 except tf.TokenFactoryError as error:
  if error.status in (400,401,403,404,422):n['deployment_submission_unknown']=False
  raise
 e=result.get('endpoint',result)
 if not e.get('id'):raise ValueError('Create response omitted an endpoint ID. Check the console before retrying.')
 n['deployment_submission_unknown']=False
 n['endpoint']=endpoint_summary(e);n['deployment_receipt']={'job_id':n['job']['id'],'weights_id':weights,'endpoint_id':e['id'],'created_here':True,'lineage':'User-declared checkpoint registration; public API does not verify artifact lineage.'};n['report']=None
 return 'Dedicated endpoint created. Refresh status until a replica is ready.'

def final_assessment(n,progress=lambda x:None):
 if not (n.get('submission') or {}).get('id'):raise ValueError('Submit a real training job before the final assessment, including the prompt alternative.')
 require_own_model(n)
 if not (n.get('report') or {}).get('passed'):raise ValueError('Pass the Mac mini behavior tests first.')
 if n.get('route')!='prompt':refresh_cloud(n)
 job=n.get('job') or {};ep=n.get('endpoint') or {};receipt=n.get('deployment_receipt') or {}
 if n.get('route')=='prompt':
  if n['report'].get('route')!='prompt' or n['report']['config']!=n['config']:raise ValueError('Run the Mac mini again against the current prompt profile and settings.')
 elif (n.get('runner') or {}).get('provider')=='serverless':
  fresh=training_cloud.refresh(n)
  if fresh['status']!='succeeded' or fresh.get('artifact_hash')!=n['runner'].get('artifact_hash'):raise ValueError('Load this job’s completed adapter before certification.')
  if n['report'].get('serving_id')!=serving_id(n) or n['report']['config']!=n['config']:raise ValueError('Run the Mac mini again with the active model and settings.')
 elif (n.get('runner') or {}).get('active'):
  health=runner_call('/health')
  if job.get('status')!='succeeded' or job.get('id')!=health.get('job_id') or job.get('model')!=health.get('model') or job.get('recipe_hash')!=health.get('recipe_hash') or n['runner'].get('artifact_hash')!=health.get('artifact_hash'):raise ValueError('The loaded caretaker does not match the verified training backup.')
  if n['report'].get('serving_id')!=health['artifact_hash'] or n['report']['config']!=n['config']:raise ValueError('Run the Mac mini again against the current checkpoint and settings.')
 else:
  if job.get('status')!='succeeded' or receipt.get('job_id')!=job.get('id'):raise ValueError('Complete a real fine-tuning job and deploy its registered checkpoint first.')
  if not ep.get('custom_weights_id') or ep.get('custom_weights_id')!=receipt.get('weights_id') or ep.get('model_name')!=job.get('model') or receipt.get('endpoint_id')!=ep.get('id'):raise ValueError('The deployment does not match the training receipt.')
  if not ep.get('enabled') or ep.get('deployment',{}).get('ready_replicas',0)<1:raise ValueError('The dedicated endpoint is not ready yet.')
  if n['report'].get('endpoint_id')!=ep['id'] or n['report']['config']!=n['config']:raise ValueError('Run the Mac mini again against the current endpoint and settings.')
 results=[]
 # Fresh image-only vision requests feed the final real text requests.
 for c in [c for c in CAMERAS if c['id']!='healthy' or n.get('flow_version',2)>=3]:
  progress('Final camera inspection: '+c['title']);vision(n,c['id']);o=n['observations'][c['id']]
  response=text_call(n,o['request']);measured=checks(response,c['expected'])
  measured.update(vision_equipment=o['equipment']==c['equipment'],vision_fault=o['fault']==c['fault'])
  results.append({'camera':c['id'],'observation':o['observation'],'equipment':o['equipment'],'fault':o['fault'],'request':o['request'],**response,'checks':measured})
 n['final']={'passed':all(all(r['checks'].values()) for r in results),'results':results,'at':time.time()}
 return 'Caretaker certified. Take him downstairs to restore cooling and release the final exit.' if n['final']['passed'] else 'The camera-to-caretaker test needs another repair. Inspect the final results.'

def _run(action,n,body,source,runtime,progress):
 if action=='exit-decision':
  require_own_model(n)
  flags=body['status'];expected={'action':'release_latch' if all(flags.values()) else 'leave_alone','equipment':'exit_door'}
  prompt='Exit inspection: '+json.dumps(flags,sort_keys=True)+'. Decide whether the exit door may open.'
  if n.get('flow_version',2)<3:prompt='The final exit door latch is stuck in the locked position.'
  reply=text_call(n,prompt);measured=checks(reply,expected)
  n['exit_decision']={**reply,'checks':measured,'expected':expected,'status':flags,'at':time.time()}
  if not all(flags.values()):return 'The caretaker holds the door. Still needed: '+', '.join({'loop_sealed':'a sealed cooling loop','controller_ready':'a responding cloud controller','cooling_healthy':'cooling within operating limits'}[k] for k,v in flags.items() if not v)+'. Then ask him again.'
  return 'The caretaker sent release_latch to his door connection.' if measured['correct'] and measured['complete'] else 'The caretaker’s door command was rejected. Compare the expected command and his actual reply at the terminal.'
 if action=='connect':return connect(n)
 if action=='personality':
  return personality(n,body.get('profile'))
 if action=='speak':return personality(n,n.get('personality'),body.get('event','A lesson was saved.'))
 if action=='try-example':return lessons.try_example(n,body.get('camera'))
 if action=='evidence':
  lessons.evidence(n,body.get('camera'));return 'Maintenance evidence added to the rehearsal.'
 if action=='try-probe':return lessons.try_probe(n,body.get('camera'))
 if action=='rehearse':return lessons.rehearse(n,body.get('camera'),body.get('repair'))
 if action=='inspect':
  if not n.get('connection'):connect(n)
  return vision(n,body.get('camera'))
 if action=='review-probe':
  camera=body.get('camera');o=n['observations'].get(camera)
  if not o:raise ValueError('Scan this camera first.')
  camera_request(o['equipment'],o['fault']);o['reviewed']=True
  expected=next(c['expected'] for c in CAMERAS if c['id']==camera)
  reply=text_call(n,o['request']);n['probe']={'camera':camera,'request':o['request'],**reply,'checks':checks(reply,expected)};n.setdefault('probes',{})[camera]=copy.deepcopy(n['probe'])
  return 'Caretaker replied. Compare its repair with the camera fault.'
 if action=='vision':return vision(n,body.get('camera'))
 if action=='probe':
  camera=body.get('camera','west');o=n['observations'].get(camera)
  if not o or not o['reviewed']:raise ValueError('Inspect a camera and check its transcription first.')
  n['probe']={'camera':camera,'request':o['request'],**text_call(n,o['request'])};return 'The caretaker replied. Read its answer on the monitor.'
 if action=='test':return assess(n,progress)
 if action=='verify':
  require_submission(n,source)
  require_own_model(n)
  assess(n,progress)
  if not n['report']['passed']:return 'The caretaker needs another adjustment. Check the Mac mini results.'
  return final_assessment(n,progress)
 if action=='train':return train(n,source,runtime)
 if action=='load-own':return activate_own_checkpoint(n,source,runtime,progress,body.get('uploaded'))
 if action in ('backup','prompt-profile'):
  require_submission(n,source)
  if not body.get('host_override'):raise ValueError('Use host controls to choose an explicit fallback or prompt experiment.')
  previous=n.get('host_override');n['host_override']={'kind':'backup' if action=='backup' else 'prompt','at':time.time()}
  try:
   if action=='backup':
    checkpoint_flow.reload_runner(runtime,(runtime.parent.parent if runtime.parent.name=='runs' else runtime)/'caretaker/receipt.json',runner_call)
    return activate_backup(n,source)
   return activate_prompt_route(n,source)
  except Exception:
   if previous:n['host_override']=previous
   else:n.pop('host_override',None)
   raise
 if action=='refresh':return refresh_cloud(n)
 if action=='deploy':return deploy(n,body)
 if action=='final':
  require_submission(n,source)
  return final_assessment(n,progress)
 raise ValueError('Unknown caretaker action.')

# A single CPU model runner serves all UUID saves. Serialize adapter selection
# with inference so one player's model cannot leak into another player's test.
RUNNER_LOCK=threading.RLock()
def run(action,n,body,source,runtime,progress):
 if n.get('training_provider')=='serverless' or (n.get('submission') or {}).get('provider')=='serverless':return _run(action,n,body,source,runtime,progress)
 if action not in ('connect','inspect','review-probe','probe','test','verify','load-own','backup','final','exit-decision'):
  return _run(action,n,body,source,runtime,progress)
 progress('Waiting for the shared caretaker CPU…')
 with RUNNER_LOCK:
  if (n.get('runner') or {}).get('active') and n.get('route')=='finetuned' and action not in ('load-own','backup'):
   health=runner_call('/health')
   if health.get('artifact_hash')!=n['runner'].get('artifact_hash') or health.get('job_id')!=(n.get('job') or {}).get('id'):
    job=(n.get('job') or {}).get('id','')
    receipt=runtime/'noc-checkpoints'/hashlib.sha256(job.encode()).hexdigest()[:20]/'receipt.json'
    if n.get('host_override',{}).get('kind')=='backup':
     shared=runtime.parent.parent if runtime.parent.name=='runs' else runtime
     receipt=shared/'caretaker/receipt.json'
    progress('Restoring this shift’s trained caretaker on the shared CPU…')
    restored=checkpoint_flow.reload_runner(runtime,receipt,runner_call)
    if restored.get('artifact_hash')!=n['runner'].get('artifact_hash') or restored.get('job_id')!=job:
     raise ValueError('The runner did not load this shift’s verified checkpoint.')
  return _run(action,n,body,source,runtime,progress)

PERSONALITIES={
 'sarcastic':{'name':'Sarcastic','style':'Dry, affectionate workplace sarcasm. Never insult the player.'},
 'friendly':{'name':'Friendly','style':'Warm, encouraging and delighted to help the night shift.'},
 'funny':{'name':'Funny','style':'Playful infrastructure jokes and mild spooky puns.'},
}
def personality(n,profile,event='You have just been restored. Introduce yourself to the night shift.'):
 if profile not in PERSONALITIES:raise ValueError('Choose a personality cartridge.')
 reply=completion(BASE,[{'role':'system','content':'You are Caretaker, a ghostlike AI in a monitor who maintains the building. Humans are repairing it with you. '+PERSONALITIES[profile]['style']+' Respond with one short sentence, under 28 words. This is dialogue only. Never emit equipment commands, claim repairs happened, or claim training finished unless the event says so.'},{'role':'user','content':event}],0.7,80)
 n['personality']=profile;n['dialogue']={**reply,'profile':profile,'at':time.time()}
 return 'Personality cartridge loaded through Token Factory. Your training controls his decisions.'
