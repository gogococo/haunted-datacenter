"""One Serverless VM; distinct application processes and credential environments."""
import json,os,pathlib,signal,subprocess,sys,threading,time
for mount in ('/mnt/persist','/mnt/soma'):
    # Mount roots can be root-only on each new VM. Both applications drop uid.
    os.chmod(mount,pathlib.Path(mount).stat().st_mode|0o111)
ROOT=pathlib.Path('/mnt/persist/shared-host');ROOT.mkdir(exist_ok=True)
ACTIVATION=ROOT/'activation.json'
children={};launches={};retry_at={}
BASE_KEYS=('PATH','LANG','LD_LIBRARY_PATH','CUDA_HOME','CUDA_VERSION','NVIDIA_VISIBLE_DEVICES','NVIDIA_DRIVER_CAPABILITIES','PYTHONUNBUFFERED','OMP_NUM_THREADS','MKL_NUM_THREADS','TOKENIZERS_PARALLELISM')
def env(prefix='',extras=None):
    result={k:os.environ[k] for k in BASE_KEYS if k in os.environ}
    if prefix:
        result.update({k[len(prefix):]:v for k,v in os.environ.items() if k.startswith(prefix)})
    return {**result,**(extras or {})}
def start(name,args,cwd,environ):
    launches[name]=(args,cwd,environ)
    child=subprocess.Popen(args,cwd=cwd,env=environ,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,start_new_session=True)
    children[name]=child
    def logs():
        private=[v for k,v in environ.items() if len(v)>10 and any(t in k for t in ('KEY','TOKEN','SECRET','ACCESS_CODE'))]
        with open('/tmp/shared-'+name+'.log','a',buffering=1) as output:
            for line in child.stdout:
                for value in private:line=line.replace(value,'[REDACTED]')
                output.write(line);print('['+name+'] '+line,end='',flush=True)
    threading.Thread(target=logs,daemon=True).start()
def stop(*args):
    for p in children.values():
        if p.poll() is None:os.killpg(p.pid,signal.SIGTERM)
    for p in children.values():
        try:p.wait(timeout=15)
        except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL)
    raise SystemExit(0)
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
if not pathlib.Path('/app/runtime-data').exists():pathlib.Path('/app/runtime-data').symlink_to('/mnt/persist',target_is_directory=True)
if not pathlib.Path('/app/data/runs').exists():pathlib.Path('/app/data/runs').symlink_to('/mnt/soma/runs',target_is_directory=True)
start('maintenance',[sys.executable,'/opt/shared/maintenance.py'],'/app',env('MAINTENANCE_',{'ACTIVATION_FILE':str(ACTIVATION)}))
worker=env('WORKER_',{'HF_HOME':'/mnt/persist/training-worker/cache','TRAINING_DATA_DIR':'/mnt/persist/training-worker/jobs','CARETAKER_WORKER_PORT':'8001'})
start('worker',[sys.executable,'-u','/opt/training_worker.py'],'/app',worker)
started=False
while True:
    for name,p in list(children.items()):
        if p.poll() is None:continue
        if name not in retry_at:
            print(name+' exited; restarting this service independently.',flush=True);retry_at[name]=time.monotonic()+5
        if time.monotonic()>=retry_at[name]:
            start(name,*launches[name]);retry_at.pop(name,None)
    if not started and ACTIVATION.exists():
        cfg=json.loads(ACTIVATION.read_text())
        # A replacement endpoint must be explicitly activated, even when the
        # previous endpoint's activation remains on the persistent filesystem.
        if cfg['name']!=os.environ.get('SHARED_EXPECTED_NAME',cfg['name']):time.sleep(1);continue
        shared={'SHARED_COOLING_ENDPOINT_ID':cfg['endpoint_id'],'SHARED_COOLING_URL':cfg['cooling_url'],
                'SHARED_COOLING_TOKEN':os.environ['COOLING_TOKEN'],'SHARED_HOST_NAME':cfg['name']}
        start('cooling',[sys.executable,'-u','/opt/shared/cooling.py'],'/app',env(extras={'SHARED_COOLING_TOKEN':os.environ['COOLING_TOKEN']}))
        start('haunted',[sys.executable,'deploy/bootstrap.py'],'/app',env('HAUNTED_',{
            **shared,'HOME':'/home/haunted','HOST':'0.0.0.0','PORT':'8080','PUBLIC_DEPLOYMENT':'true',
            'GAME_DATA_DIR':'/app/runtime-data/runtime','CARETAKER_WORKER_URL':cfg['worker_url'],
            'CARETAKER_WORKER_TOKEN':os.environ['WORKER_CARETAKER_WORKER_TOKEN']}))
        start('soma',['node','bootstrap.mjs'],'/opt/soma',env('SOMA_',{
            'HOST':'0.0.0.0','PORT':'8081','PUBLIC_DEPLOYMENT':'true','RUNS_DIR':'/app/data/runs'}))
        started=True
        print('Shared demo applications started.',flush=True)
    time.sleep(1)
