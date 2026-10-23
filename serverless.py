"""Real Nebius Serverless CPU deployment. No shell execution or browser credentials.
Auth tokens remain in private runtime receipts and never enter /api/state.
"""
import json,os,re,secrets,subprocess,time,urllib.request,urllib.parse
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def cli(args):
    env={**os.environ,'AI_AGENT':os.environ.get('AI_AGENT') or 'codex'}
    try:p=subprocess.run(['nebius',*args,'--format','json','--no-browser','--auth-timeout','180s' if args[:3]==['ai','endpoint','create'] else '45s','--timeout','180s' if args[:3]==['ai','endpoint','create'] else '45s','--per-retry-timeout','180s' if args[:3]==['ai','endpoint','create'] else '45s','--retries','1'],capture_output=True,text=True,timeout=200 if args[:3]==['ai','endpoint','create'] else 65,env=env)
    except (OSError,subprocess.TimeoutExpired):raise ValueError('Nebius CLI is unavailable or timed out. Check your AI Cloud login; no automatic retry.') from None
    if p.returncode:
        # Never echo CLI output: endpoint responses and errors can carry auth tokens.
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

def deploy(p,body,runtime):
    if p.get('deployment_unknown'):raise ValueError('A deployment had an uncertain result. Check Serverless AI in the console before submitting another.')
    if p.get('endpoint'):raise ValueError('This incident already has an endpoint. Refresh its status instead of creating another.')
    c=config(runtime)
    if not c['project_id'] or not c['subnet_id']:raise ValueError('Configure your Nebius AI Cloud project and subnet before deploying. See README → Serverless setup.')
    try:port=int(body.get('port',8000));target=float(body.get('target',75));budget=float(body.get('budget',12))
    except (TypeError,ValueError):raise ValueError('Use numeric port, temperature target and power budget.') from None
    if not 1<=port<=65535 or not 30<=target<=100 or not 1<=budget<=30:raise ValueError('Check the controller plate: port, temperature target and power budget must be within the supported ranges.')
    name='haunted-cooling-'+str(int(time.time()));token=secrets.token_urlsafe(32)
    args=['ai','endpoint','create','--name',name,'--parent-id',c['project_id'],'--subnet-id',c['subnet_id'],
          '--image','python:3.12-slim','--platform',c['platform'],'--preset',c['preset'],'--disk-size','20Gi',
          '--container-port',str(port),'--container-command','python','--args','/opt/controller.py',
          '--inject-file',str(ROOT/'cloud_controller.py')+':/opt/controller.py','--env','TARGET_C='+str(target),'--env','MAX_POWER_KW='+str(budget),
          '--auth','token','--token',token,'--async']
    # Resolve validation before making the create request.
    cli([*args,'--dry-run'])
    p['deployment_unknown']=True
    folder=runtime/'serverless';folder.mkdir(exist_ok=True)
    pending=folder/'pending.json';pending.write_text(json.dumps({'name':name,'token':token,'project_id':c['project_id']}));pending.chmod(0o600)
    result=cli(args)
    identifier=result.get('resource_id') or result.get('resourceId') or result.get('metadata',{}).get('id')
    if not identifier:raise ValueError('Create returned no endpoint ID. Inspect the console; do not submit another deployment.')
    receipt={'token':token,'project_id':c['project_id'],'port':port,'target':target,'budget':budget,'created_at':time.time()}
    path=private_path(runtime,identifier);path.write_text(json.dumps(receipt));path.chmod(0o600)
    p['endpoint']={'id':identifier,'name':name,'state':'STARTING','url':'','config':{'port':port,'target':target,'budget':budget}}
    p['deployment_unknown']=False;p['health']=None;p['report']=None
    return 'Deployment submitted to Nebius Serverless. Repair the cooling loop while the container starts.'

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
    reply=call(p,runtime,'/simulate',{'loop_sealed':circuit['passed'],'nonce':nonce})
    from cloud_controller import VERSION
    if reply.get('service')!=VERSION or reply.get('nonce')!=nonce:raise ValueError('The controller response does not match this live request.')
    values=plant.settings(reply.get('settings',{}));measured=plant.test_controller(board,values)
    valid=reply.get('healthy') is True and reply.get('temperature_c')==measured['temperature_c'] and reply.get('power_kw')==measured['power_kw']
    p['settings']=values;p['pipes']=board;p['pipe_report']=circuit
    p['report']={**measured,'passed':bool(measured['passed'] and valid),'endpoint_id':p['endpoint']['id'],'remote':reply,'request_nonce':nonce,'scope':'Real Serverless app execution against simulated game telemetry.'}
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

def replace(p,body,runtime):
    ep=p.get('endpoint')
    if not ep:raise ValueError('There is no deployment to replace.')
    if not private_path(runtime,ep['id']).exists():raise ValueError('Only a controller created by this game can be replaced.')
    cli(['ai','endpoint','stop',ep['id']])
    p.setdefault('previous_endpoints',[]).append({'id':ep['id'],'name':ep['name'],'state':'STOPPED'})
    p['endpoint']=None;p['health']=None;p['report']=None
    return deploy(p,body,runtime)
