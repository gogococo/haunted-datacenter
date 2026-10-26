"""Prepare the dedicated persistent volume, drop privileges, supervise both processes."""
import json, os, pathlib, signal, subprocess, sys, time, urllib.request

ROOT=pathlib.Path(__file__).resolve().parents[1]
runtime=pathlib.Path(os.environ.get('GAME_DATA_DIR',str(ROOT/'.runtime')))
if os.getuid()==0:
    # Nebius mounts dedicated filesystems as root. Grant only this app access.
    runtime.parent.mkdir(parents=True,exist_ok=True);os.chmod(runtime.parent,0o711)
    runtime.mkdir(parents=True,exist_ok=True);os.chown(runtime,1000,1000)
    os.setgroups([]);os.setgid(1000);os.setuid(1000)
    os.environ['HOME']='/home/haunted'
else:runtime.mkdir(parents=True,exist_ok=True)

if os.environ.get('NEBIUS_PRIVATE_KEY'):
    key=runtime/'cloud-identity.pem';key.write_text(os.environ.pop('NEBIUS_PRIVATE_KEY'));key.chmod(0o600)
    profile_action='update' if (pathlib.Path.home()/'.nebius/config.yaml').exists() else 'create'
    command=['nebius','profile',profile_action,'haunted-runtime','--endpoint','api.nebius.cloud','--skip-auth','--service-account-id',os.environ['NEBIUS_SERVICE_ACCOUNT_ID'],
             '--public-key-id',os.environ['NEBIUS_PUBLIC_KEY_ID'],'--private-key-file-path',str(key),
             '--parent-id',os.environ['NEBIUS_PROJECT_ID'],'--no-browser','--no-check-update']
    result=subprocess.run(command,capture_output=True,timeout=90)
    if result.returncode:raise SystemExit('Cloud service-account authentication failed; check the identity configuration.')

children=[]
def stop(*_):
    for child in children:
        if child.poll() is None:child.terminate()
    for child in children:
        try:child.wait(timeout=10)
        except subprocess.TimeoutExpired:child.kill()
    raise SystemExit(0)
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
runner=subprocess.Popen([sys.executable,str(ROOT/'caretaker_runner.py'),'--base-dir',os.environ.get('CARETAKER_BASE_DIR','/opt/models/base'),'--runtime',str(runtime)],cwd=ROOT)
children.append(runner)
for _ in range(120):
    if runner.poll() is not None:raise SystemExit('Caretaker runner exited during startup.')
    try:
        with urllib.request.urlopen('http://127.0.0.1:8770/health',timeout=2) as response:
            if json.load(response).get('ready'):break
    except OSError:pass
    time.sleep(1)
else:stop()

# Reload the active run's persisted adapter after a container replacement.
try:
    state=json.loads((runtime/'state.json').read_text());n=state.get('noc',{})
    if n.get('route')=='finetuned' and n.get('runner',{}).get('active'):
        sys.path.insert(0,str(ROOT));import checkpoint_flow,caretaker
        job=(n.get('job') or {}).get('id','')
        import hashlib
        receipt=runtime/'noc-checkpoints'/hashlib.sha256(job.encode()).hexdigest()[:20]/'receipt.json'
        if receipt.exists():checkpoint_flow.reload_runner(runtime,receipt,caretaker.runner_call)
except (OSError,ValueError,KeyError):
    if (runtime/'state.json').exists():print('Saved adapter needs reloading at the maintenance terminal.',flush=True)

children.append(subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT))
while all(child.poll() is None for child in children):time.sleep(1)
stop()
