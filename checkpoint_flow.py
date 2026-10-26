"""Retrieve and load the current incident's trained checkpoint; never substitute a backup."""
import hashlib,json,os,urllib.error,urllib.parse,urllib.request
from pathlib import Path
import content,tokenfactory as tf,checkpoint_setup

class DownloadUnavailable(ValueError):pass

def download(file_id,destination,expected_bytes):
 if not 0<expected_bytes<=64*1024*1024:raise ValueError('Checkpoint size is outside this small-model demo’s limits.')
 req=urllib.request.Request(tf.CONTROL+'/v1/files/'+urllib.parse.quote(file_id,safe='')+'/content',headers={'Authorization':'Bearer '+tf.key()})
 opener=urllib.request.build_opener(tf.NoRedirect)
 try:
  try:response=opener.open(req,timeout=60)
  except urllib.error.HTTPError as error:
   if error.code not in (301,302,303,307,308):raise
   url=error.headers.get('Location','');u=urllib.parse.urlparse(url)
   if u.scheme!='https' or not (u.hostname or '').endswith('.nebius.cloud') or u.username or u.password or u.port not in (None,443):raise ValueError('Unexpected checkpoint storage destination.')
   # A storage signature is its own credential. Never forward the API bearer token.
   response=opener.open(urllib.request.Request(url),timeout=60)
  with response:
   data=response.read(expected_bytes+1)
  if len(data)!=expected_bytes:raise ValueError('Checkpoint download size differs from its cloud metadata.')
 except (urllib.error.URLError,TimeoutError):
  raise DownloadUnavailable('Token Factory’s weight download is unavailable. Download this job’s final adapter in the dashboard, then import it here.') from None
 Path(destination).write_bytes(data)

def runner_config(runtime):
 runtime=Path(runtime)
 shared=runtime.parent.parent if runtime.parent.name=='runs' else runtime
 path=Path(os.environ.get('CARETAKER_RUNNER_CONTROL',str(shared/'caretaker/runner-control.json')))
 try:return json.loads(path.read_text())
 except (OSError,ValueError):raise ValueError('Restart the updated caretaker runner to enable loading your new checkpoint.') from None

def reload_runner(runtime,receipt,runner_call):
 control=runner_config(runtime)
 return runner_call('/v1/checkpoints/load',{'receipt':str(Path(receipt).resolve())},control['token'])

def prepare(n,source,runtime,progress,uploaded=None):
 submission=n['submission'];expected=dict(submission);jid=submission['id'];job=tf.api('/v1/fine_tuning/jobs/'+urllib.parse.quote(jid,safe=''))
 submission.update({key:job.get(key) for key in ('status','trained_steps','total_steps','finished_at')})
 if job.get('status')!='succeeded':raise ValueError('Your training job is not finished yet. Keep working in the generator room.')
 for key in ('model','training_file','validation_file'):
  if not expected.get(key) or expected[key]!=job.get(key):raise ValueError('Training job metadata does not match your submitted pack.')
 checkpoints=tf.api('/v1/fine_tuning/jobs/'+urllib.parse.quote(jid,safe='')+'/checkpoints')['data']
 if not checkpoints:raise ValueError('The completed job has not published a checkpoint yet.')
 ck=max(checkpoints,key=lambda row:row['step_number'])
 files=[tf.api('/v1/files/'+urllib.parse.quote(fid,safe='')) for fid in ck['result_files']]
 weight=next((f for f in files if Path(f['filename']).name=='adapter_model.safetensors'),None)
 if not weight:raise ValueError('Your job did not return a LoRA adapter file.')
 control=runner_config(runtime)
 if control['model']!=job['model']:raise ValueError('The local runner’s base model must match your training model.')
 folder=runtime/'noc-checkpoints'/hashlib.sha256(jid.encode()).hexdigest()[:20];folder.mkdir(parents=True,exist_ok=True)
 weights=folder/'adapter_model.safetensors'
 if uploaded is not None:
  if len(uploaded)!=weight['bytes']:raise ValueError('Choose the final adapter_model.safetensors for this job; its size must match Token Factory’s metadata.')
  weights.write_bytes(uploaded)
 elif not weights.exists():
  progress('Retrieving the final checkpoint from your completed training job…')
  try:download(weight['id'],weights,weight['bytes'])
  except DownloadUnavailable as error:
   n['checkpoint_download']={'status':'needs_import','job_id':jid,'checkpoint_id':ck['id'],'message':str(error)}
   return None
 seed=folder/'seed.jsonl';seed.write_text(source)
 receipt=checkpoint_setup.prepare(jid,weights,control['base_dir'],folder,seed)
 data=json.loads(receipt.read_text());data['pack_hash']=submission['pack_hash']
 data['provenance']='API artifact download from this job.' if uploaded is None else 'Player selected the dashboard download for this job; size, configuration and cloud checkpoint metadata checked. No cloud checksum is available.'
 receipt.write_text(json.dumps(data,indent=2)+'\n')
 n['checkpoint_download']={'status':'prepared','job_id':jid,'checkpoint_id':ck['id']}
 return receipt,job
