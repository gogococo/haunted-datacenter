"""Real Nebius Serverless CPU deployment. No shell execution or browser credentials.
Auth tokens remain in private runtime receipts and never enter /api/state.
"""
import json,os,re,secrets,subprocess,time,urllib.request,urllib.parse
import contextlib,fcntl,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def cli(args):
    env={**os.environ,'AI_AGENT':os.environ.get('AI_AGENT') or 'codex'}
    try:p=subprocess.run(['nebius',*args,'--format','json','--no-browser','--auth-timeout','180s' if args[:3]==['ai','endpoint','create'] else '45s','--timeout','180s' if args[:3]==['ai','endpoint','create'] else '45s','--per-retry-timeout','180s' if args[:3]==['ai','endpoint','create'] else '45s','--retries','1'],capture_output=True,text=True,timeout=200 if args[:3]==['ai','endpoint','create'] else 65,env=env)
    except (OSError,subprocess.TimeoutExpired):raise ValueError('Nebius CLI is unavailable or timed out. Check your AI Cloud login; no automatic retry.') from None
    if p.returncode:
        # Never echo CLI output: endpoint responses and errors can carry auth tokens.
        if 'compute.instance.non-gpu.vcpu' in p.stderr and ('Quota' in p.stderr or 'quota' in p.stderr):
            raise ValueError('Nebius CPU quota is full. No extra controller was provisioned. Stop an unused demo or reuse this game’s existing controller; other demos are left alone.')
        raise ValueError('Nebius CLI could not complete '+ ' '.join(args[:3])+'. Check your project, CLI login and resource quotas. No automatic retry.')
    if '--dry-run' in args:return {'validated':True}
    try:return json.loads(p.stdout or '{}')
    except ValueError:
        if args[:3] in (['ai','endpoint','stop'],['ai','endpoint','start']):return {'accepted':True}
        if args[:3]==['ai','endpoint','create']:
            # Some CLI builds emit a human receipt even with --format json.
            # Resolve the unique name through a read; never re-submit a create.
            project=args[args.index('--parent-id')+1];name=args[args.index('--name')+1]
            rows=cli(['ai','endpoint','list','--parent-id',project]).get('items',[])
            for row in rows:
                if row.get('metadata',{}).get('name')==name:return row
        raise ValueError('Nebius CLI returned an unreadable result. Check the console before retrying.') from None

def config(runtime):
    path=runtime/'serverless/config.json'
    values=json.loads(path.read_text()) if path.exists() else {}
    return {'project_id':os.environ.get('NEBIUS_PROJECT_ID') or values.get('project_id',''),
            'subnet_id':os.environ.get('NEBIUS_SUBNET_ID') or values.get('subnet_id',''),
            'platform':values.get('platform','cpu-d3'),'preset':values.get('preset','2vcpu-8gb')}

def private_path(runtime,identifier):
    if not re.fullmatch(r'[a-zA-Z0-9-]{1,100}',identifier):raise ValueError('Invalid endpoint ID.')
    return runtime/'serverless'/('endpoint-'+identifier+'.json')

def public(row):
    meta=row.get('metadata',{});status=row.get('status',{})
    urls=[u for u in status.get('public_endpoints',[]) if isinstance(u,str) and u.startswith('https://')]
    return {'id':meta.get('id'),'name':meta.get('name'),'state':status.get('state','STARTING'),'url':urls[0] if urls else '', 'service':'Nebius Serverless AI','checked_at':time.time()}

# One project controller is reused between incidents. Credentials and the lease are
# private; only the selected endpoint DTO is copied into the saved game state.
_POOL_LOCK=threading.RLock()
_RELEASED=set()
_RELEASE_LOCK=threading.Lock()
POOL_NAME='haunted-cooling-controller-v3'
LEASE_TTL=20*60
ACTIVE_STATES={'RUNNING','STARTING','CREATING','UPDATING','IMAGE_PULLING','PROVISIONING'}

def _write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value));temp.chmod(0o600);temp.replace(path)

def _pool_path(runtime):return runtime/'serverless/controller.json'

def _read(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return {}

@contextlib.contextmanager
def lifecycle_lock(runtime):
    # Serialize CLI mutations across request threads and processes using this data
    # directory. A project-wide stable name also prevents duplicate first creates.
    with _POOL_LOCK:
        path=runtime/'serverless/lifecycle.lock';path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('a') as lock:
            path.chmod(0o600);fcntl.flock(lock,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(lock,fcntl.LOCK_UN)

def owned(row,project):
    meta=row.get('metadata',{});spec=row.get('spec',{})
    name=meta.get('name','')
    return bool(meta.get('parent_id')==project and
        re.fullmatch(r'haunted-cooling-(?:[0-9]+|controller(?:-[a-z0-9]+)?)',name) and
        spec.get('image')=='python:3.12-slim' and spec.get('container_command')=='python' and
        spec.get('args')=='/opt/controller.py' and
        any(x.get('container_path')=='/opt/controller.py' for x in spec.get('injected_files',[])))

def _settings(body):
    try:values={'port':int(body.get('port',8000)),'target':float(body.get('target',75)),'budget':float(body.get('budget',12))}
    except (TypeError,ValueError):raise ValueError('Use numeric port, temperature target and power budget.') from None
    if not 1<=values['port']<=65535 or not 30<=values['target']<=100 or not 1<=values['budget']<=30:
        raise ValueError('Check the controller plate: port, temperature target and power budget must be within the supported ranges.')
    return values

def _row_settings(row):
    spec=row['spec'];env={x['name']:x.get('value') for x in spec.get('environment_variables',[])}
    return _settings({'port':spec['ports'][0]['container_port'],'target':env['TARGET_C'],'budget':env['MAX_POWER_KW']})

def _leases(pool):
    now=time.time()
    leases=pool.get('leases',{}) if pool.get('shared') else ({pool['lease']:now} if pool.get('lease') else {})
    return {k:v for k,v in leases.items() if isinstance(v,(int,float)) and now-v<LEASE_TTL}

def enable_shared(runtime):
    """Upgrade the old single-shift receipt without allocating cloud resources."""
    with lifecycle_lock(runtime):
        pool=_read(_pool_path(runtime))
        if pool and not pool.get('shared') and pool.get('project_id')==config(runtime)['project_id']:
            pool.update(shared=True,leases=_leases(pool));_write(_pool_path(runtime),pool)

def allow(runtime,lease):
    with _RELEASE_LOCK:_RELEASED.discard((str(runtime.resolve()),lease))

def touch(runtime,lease):
    # Polls must not block on a slow create/stop CLI request.
    if not _POOL_LOCK.acquire(blocking=False):return
    try:
        pool=_read(_pool_path(runtime))
        if not pool.get('shared') or lease not in pool.get('leases',{}):return
        if time.time()-pool['leases'][lease]<60:return
        pool['leases'][lease]=time.time();_write(_pool_path(runtime),pool)
    finally:_POOL_LOCK.release()

def reap(runtime):
    pool=_read(_pool_path(runtime))
    if pool.get('shared') and pool.get('state') not in ('STOPPED','STOPPING') and not _leases(pool):
        return release(runtime,pool.get('lease'),idle=True)

def _remember(p,row,runtime,lease,shared=False,lease_started=0):
    c=config(runtime);identifier=row['metadata']['id'];values=_row_settings(row)
    token=row.get('spec',{}).get('auth_token') or _read(private_path(runtime,identifier)).get('token')
    if not token:raise ValueError('The existing controller has no available private access token. Check its cloud configuration before replacing it.')
    receipt={'id':identifier,'name':row['metadata']['name'],'project_id':c['project_id'],'token':token,**values,'lease':lease,'lease_started':lease_started,'state':row.get('status',{}).get('state','STARTING')}
    previous=_read(_pool_path(runtime))
    if shared or previous.get('shared'):
        receipt.update(shared=True,leases=_leases(previous))
        receipt['claims']={key:previous.get('claims',{}).get(key,0) for key in receipt['leases']}
        if lease:receipt['leases'][lease]=time.time();receipt['claims'][lease]=lease_started
    _write(private_path(runtime,identifier),receipt);_write(_pool_path(runtime),receipt)
    p['endpoint']={**public(row),'config':values,'reused':True};p['deployment_unknown']=False;p['health']=None;p['report']=None
    return receipt

def _find(p,runtime,project):
    rows=cli(['ai','endpoint','list','--parent-id',project]).get('items',[])
    # List responses can omit spec fields. GET before trusting ownership, config,
    # or credentials. Never select the host app or another project's demo.
    candidates=[]
    for row in rows:
        meta=row.get('metadata',{})
        if re.fullmatch(r'haunted-cooling-(?:[0-9]+|controller(?:-[a-z0-9]+)?)',meta.get('name','')):
            full=cli(['ai','endpoint','get',meta['id']])
            if owned(full,project):candidates.append(full)
    preferred=(p.get('endpoint') or {}).get('id') or _read(_pool_path(runtime)).get('id')
    candidates.sort(key=lambda r:(r['metadata']['name'].startswith(POOL_NAME),r.get('status',{}).get('state') in ACTIVE_STATES,r['metadata']['id']==preferred,r['metadata'].get('created_at','')),reverse=True)
    return candidates

def _cancelled(runtime,lease):
    with _RELEASE_LOCK:return (str(runtime.resolve()),lease) in _RELEASED

def _stop(row,runtime):
    if row.get('status',{}).get('state')!='STOPPED':
        cli(['ai','endpoint','stop',row['metadata']['id']])
    receipt=_read(_pool_path(runtime))
    if receipt.get('id')==row['metadata']['id']:
        receipt.update(state='STOPPED',cleanup_error=None);_write(_pool_path(runtime),receipt)

def _deploy(p,body,runtime,lease,replace=False,shared=False):
    lease_started=time.time()
    if _cancelled(runtime,lease):raise ValueError('This shift has ended. The controller was not started.')
    if p.get('deployment_unknown'):raise ValueError('A deployment had an uncertain result. Check Serverless AI in the console before submitting another.')
    c=config(runtime);values=_settings({**(p.get('endpoint') or {}).get('config',{}),**body})
    if not c['project_id'] or not c['subnet_id']:raise ValueError('Configure your Nebius AI Cloud project and subnet before deploying. See README → Serverless setup.')
    candidates=_find(p,runtime,c['project_id'])
    if replace and not candidates:raise ValueError('There is no game-owned controller to replace.')
    selected=candidates[0] if candidates else None
    if selected:
        _remember(p,selected,runtime,lease,shared,lease_started)
        pending=runtime/'serverless/pending.json'
        if _read(pending).get('name') in {r['metadata']['name'] for r in candidates}:pending.unlink(missing_ok=True)
        # Clean up only positively identified controllers from old game versions.
        # Stop first, so replacement/wake never needs two controller CPU slots.
        for row in candidates[1:]:
            if row.get('status',{}).get('state') in ACTIVE_STATES:_stop(row,runtime)
        if replace and values!=p['endpoint']['config']:
            if shared or any(id!=lease for id in _leases(_read(_pool_path(runtime)))):
                raise ValueError('Other playtests share this CPU app. Use the equipment-plate settings to reconnect; this game cannot replace their running controller.')
            _stop(selected,runtime)
            p.setdefault('previous_endpoints',[]).append({**public(selected),'state':'STOPPED'})
        else:
            if values!=p['endpoint']['config']:
                if shared:raise ValueError('The shared cooling service uses the equipment-plate settings. Correct your configuration and reconnect; other players’ controller stays running.')
                raise ValueError('Reused controller has a different configuration. Its existing values are shown below. Use “Replace with corrected deployment” to change them; the old CPU stops first.')
            state=p['endpoint']['state']
            if state=='STOPPED':
                cli(['ai','endpoint','start',p['endpoint']['id'],'--async'])
                p['endpoint']['state']='STARTING'
                receipt=_read(_pool_path(runtime));receipt['state']='STARTING';_write(_pool_path(runtime),receipt)
                return 'Starting the existing cooling controller. Same endpoint, one shared CPU controller. Repair the circuit while it wakes.'
            if state not in ACTIVE_STATES:
                raise ValueError('The existing controller is '+state+'. Wait for it to stop, then start it again; no extra controller was created.')
            return 'Connected to the existing cooling controller. No new endpoint created. Check HTTP readiness, then test this circuit.'
    pending=_read(runtime/'serverless/pending.json')
    if pending and pending.get('project_id')==c['project_id']:
        # A crash between create and receipt must never trigger a second create.
        if not any(r['metadata']['name']==pending.get('name') for r in candidates):
            raise ValueError('A previous controller create has no confirmed receipt. Check the cloud console before retrying; no duplicate was submitted.')
    if shared and values!={'port':8000,'target':75.0,'budget':12.0}:
        raise ValueError('Use the equipment-plate settings before starting the shared service. No controller was created.')
    name=POOL_NAME if not candidates else POOL_NAME+'-'+secrets.token_hex(6)
    token=secrets.token_urlsafe(32)
    args=['ai','endpoint','create','--name',name,'--parent-id',c['project_id'],'--subnet-id',c['subnet_id'],
          '--image','python:3.12-slim','--platform',c['platform'],'--preset',c['preset'],'--disk-size','20Gi',
          '--container-port',str(values['port']),'--container-command','python','--args','/opt/controller.py',
          '--inject-file',str(ROOT/'cloud_controller.py')+':/opt/controller.py','--env','TARGET_C='+str(values['target']),'--env','MAX_POWER_KW='+str(values['budget']),
          '--auth','token','--token',token,'--async']
    cli([*args,'--dry-run'])
    p['deployment_unknown']=True
    pending=runtime/'serverless/pending.json';_write(pending,{'name':name,'token':token,'project_id':c['project_id']})
    result=cli(args)
    identifier=result.get('resource_id') or result.get('resourceId') or result.get('metadata',{}).get('id')
    if not identifier:raise ValueError('Create returned no endpoint ID. Inspect the console; do not submit another deployment.')
    receipt={'id':identifier,'name':name,'token':token,'project_id':c['project_id'],**values,'lease':lease,'lease_started':lease_started,'state':'STARTING','created_at':time.time()}
    if shared:receipt.update(shared=True,leases={lease:time.time()} if lease else {},claims={lease:lease_started} if lease else {})
    _write(private_path(runtime,identifier),receipt);_write(_pool_path(runtime),receipt);pending.unlink(missing_ok=True)
    p['endpoint']={'id':identifier,'name':name,'state':'STARTING','url':'','config':values,'reused':False}
    p['deployment_unknown']=False;p['health']=None;p['report']=None
    return 'First cooling controller submitted to Nebius Serverless. Later shifts reuse this endpoint. Repair the circuit while the container starts.'

def deploy(p,body,runtime,lease=None,shared=False):
    with lifecycle_lock(runtime):return _deploy(p,body,runtime,lease,shared=shared)

def prewarm(runtime,lease):
    """Wake only an already commissioned shared app while earlier rooms are played.

    This never creates or replaces an endpoint and does not commission the player's
    console. Each game still has to find and enter the maintenance-book settings.
    """
    candidate=_read(_pool_path(runtime))
    if not candidate.get('id') or candidate.get('name')!=POOL_NAME:return
    with lifecycle_lock(runtime):
        pool=_read(_pool_path(runtime));project=config(runtime)['project_id']
        if not pool.get('id') or pool.get('project_id')!=project or pool.get('name')!=POOL_NAME or _cancelled(runtime,lease):return
        row=cli(['ai','endpoint','get',pool['id']])
        if not owned(row,project) or row['metadata'].get('name')!=POOL_NAME or _row_settings(row)!={'port':8000,'target':75.0,'budget':12.0}:return
        started=time.time();phase=row.get('status',{}).get('state')
        if phase not in ACTIVE_STATES and phase!='STOPPED':return
        _remember({},row,runtime,lease,shared=True,lease_started=started)
        if phase=='STOPPED' and not _cancelled(runtime,lease):
            cli(['ai','endpoint','start',pool['id'],'--async'])
            receipt=_read(_pool_path(runtime));receipt['state']='STARTING';_write(_pool_path(runtime),receipt)

def release(runtime,lease,endpoint=None,idle=False):
    """Nonblocking cleanup. A stale reset cannot stop a newer shift's lease."""
    if not lease:return
    released_at=time.time()
    if not idle:
        with _RELEASE_LOCK:_RELEASED.add((str(runtime.resolve()),lease))
    def worker():
        with lifecycle_lock(runtime):
            pool=_read(_pool_path(runtime));project=config(runtime)['project_id']
            try:
                if idle and _leases(pool):return
                # Adopt a pre-pool saved incident on its first reset/finish.
                if not pool and endpoint and private_path(runtime,endpoint['id']).exists():
                    row=cli(['ai','endpoint','get',endpoint['id']])
                    if owned(row,project):pool=_remember({},row,runtime,lease)
                if not pool or pool.get('project_id')!=project:return
                if pool.get('shared'):
                    if pool.get('claims',{}).get(lease,0)>released_at:return
                    leases=_leases(pool);leases.pop(lease,None);pool['leases']=leases;_write(_pool_path(runtime),pool)
                    if leases:return
                elif pool.get('lease')!=lease:return
                row=cli(['ai','endpoint','get',pool['id']])
                if not owned(row,project):raise ValueError('Controller ownership could not be verified. No resource was stopped.')
                pool.update(state='STOPPING',cleanup_error=None);_write(_pool_path(runtime),pool)
                _stop(row,runtime)
            except (ValueError,OSError,KeyError) as error:
                pool['cleanup_error']=str(error) if isinstance(error,ValueError) else 'Controller cleanup failed. Check its status in Nebius.'
                _write(_pool_path(runtime),pool)
    thread=threading.Thread(target=worker,daemon=True);thread.start();return thread

def pool_status(runtime):
    pool=_read(_pool_path(runtime))
    return {k:pool[k] for k in ('id','state','cleanup_error') if k in pool}

def refresh(p,runtime):
    ep=p.get('endpoint')
    if not ep:raise ValueError('Deploy the cooling controller first.')
    row=cli(['ai','endpoint','get',ep['id']]);p['endpoint']={**ep,**public(row)}
    return 'Endpoint '+p['endpoint']['state']+'. Check HTTP readiness before testing cooling.'

def call(p,runtime,path,data=None):
    ep=p.get('endpoint') or {};url=ep.get('url','');parts=urllib.parse.urlparse(url)
    # URLs originate only in the CLI resource response, never in a player input.
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password:raise ValueError('The endpoint has no managed HTTPS URL yet. Refresh cloud status.')
    receipt=json.loads(private_path(runtime,ep['id']).read_text())
    req=urllib.request.Request(url.rstrip('/')+path,data=json.dumps(data).encode() if data is not None else None,headers={'Authorization':'Bearer '+receipt['token'],'Content-Type':'application/json'})
    from tokenfactory import NoRedirect
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=25) as r:reply=json.load(r)
    except OSError:raise ValueError('The deployed app did not answer. Inspect endpoint status and confirm its exposed port matches the app’s port 8000.') from None
    return reply

def health(p,runtime):
    refresh(p,runtime);reply=call(p,runtime,'/healthz')
    from cloud_controller import VERSION
    if reply.get('service')!=VERSION or reply.get('ready') is not True:raise ValueError('The endpoint is not serving this cooling-controller version.')
    p['health']={'passed':True,'service':reply['service'],'target_c':reply.get('target_c'),'budget_kw':reply.get('budget_kw'),'at':time.time(),'endpoint_id':p['endpoint']['id']}
    return 'HTTP 200. The app is ready. Now prove it can cool the repaired circuit.'

def assess(p,runtime,board):
    import plant
    if not (p.get('health') or {}).get('passed'):raise ValueError('Check the deployed app’s /healthz route first.')
    circuit=plant.check_pipes(board);nonce=secrets.token_hex(16)
    request={'loop_sealed':circuit['passed'],'nonce':nonce,'settings':plant.settings(p['settings'])}
    reply=call(p,runtime,'/simulate',request)
    from cloud_controller import VERSION
    if reply.get('service')!=VERSION or reply.get('nonce')!=nonce:raise ValueError('The controller response does not match this live request.')
    values=plant.settings(reply.get('settings',{}));measured=plant.test_controller(board,values)
    valid=reply.get('healthy') is True and reply.get('temperature_c')==measured['temperature_c'] and reply.get('power_kw')==measured['power_kw'] and reply.get('requested_settings')==request['settings'] and values==request['settings']
    p['settings']=values;p['pipes']=board;p['pipe_report']=circuit
    p['report']={**measured,'passed':bool(measured['passed'] and valid),'endpoint_id':p['endpoint']['id'],'request':request,'remote':reply,'request_nonce':nonce,'scope':'Real Serverless app execution against simulated game telemetry.'}
    return 'Cooling stable. The lights hold.' if p['report']['passed'] else measured['message'] if not measured['passed'] else 'The app replied, but its measurements did not match the live circuit check.'

def logs(p,runtime):
    ep=p.get('endpoint')
    if not ep:raise ValueError('Deploy the app before requesting logs.')
    env={**os.environ,'AI_AGENT':os.environ.get('AI_AGENT') or 'codex'}
    result=subprocess.run(['nebius','ai','endpoint','logs',ep['id'],'--tail','20','--no-browser','--auth-timeout','5s','--timeout','20s'],capture_output=True,text=True,timeout=30,env=env)
    if result.returncode:raise ValueError('App logs are not available yet. Refresh endpoint status and try again.')
    receipt=json.loads(private_path(runtime,ep['id']).read_text())
    p['cloud_logs']=result.stdout.replace(receipt['token'],'[REDACTED]')[-6000:]
    return 'Actual container logs retrieved from Nebius Serverless.'

def replace(p,body,runtime,lease=None,shared=False):
    if not p.get('endpoint'):raise ValueError('There is no deployment to replace.')
    with lifecycle_lock(runtime):return _deploy(p,body,runtime,lease,replace=True,shared=shared)
