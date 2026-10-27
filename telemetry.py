"""Explicit anonymous product events, durable local buffering, background PostHog delivery.

Never send request bodies, URLs, names, save UUIDs, credentials or model contents.
Analytics errors must never change the outcome of a game action.
"""
import contextlib, datetime, hashlib, hmac, json, logging, os, re, secrets, sqlite3, threading, time, uuid
from pathlib import Path
from urllib.request import Request, urlopen
import hosting

_lock=threading.RLock()
_started=set()
HOSTS={'us':'https://us.i.posthog.com','eu':'https://eu.i.posthog.com'}
STEPS={'research':1,'documentation':1,'bookmark':1,'switchboard':1,'speaker':1,'door_command':1,
       'camera':2,'demonstration':2,'training_pack':2,'baseline':2,'training':2,'checkpoint':2,'exam':2,
       'pipes':3,'commissioning':3,'health':3,'cooling':3,'exit':3}
OBJECTS={'research':'research','mabel-post':'bookmark','switchboard':'switchboard','speaker':'speaker','rack':'door_command',
         'noc-camera':'camera','noc-binder':'training_pack','noc-console':'training','noc-mini':'exam',
         'plant-pipes':'pipes','plant-controller':'cooling','plant-exit':'exit'}
log=logging.getLogger('haunted.analytics')

def safe(fn):
    def wrapped(*args,**kwargs):
        try:return fn(*args,**kwargs)
        except Exception as error:log.warning('analytics_unavailable error_type=%s',type(error).__name__)
    return wrapped

@contextlib.contextmanager
def connect(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(root/'analytics.sqlite',timeout=.2)
    db.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, at REAL, payload TEXT, sent INTEGER DEFAULT 0)')
    db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, metadata TEXT)')
    try:
        with db:yield db
    finally:db.close()

def pseudonym(root,value):
    path=Path(root)/'analytics-salt'
    if not path.exists():
        path.write_text(secrets.token_hex(32));path.chmod(0o600)
    return hmac.new(path.read_bytes(),str(value).encode(),hashlib.sha256).hexdigest()

def settings(root):
    try:d=json.loads((Path(root)/'posthog.json').read_text())
    except (OSError,ValueError):d={}
    return {'enabled':d.get('enabled') is True,'region':d.get('region','us'),'key':d.get('key',''),'project_url':d.get('project_url','')}

def configure(root,body):
    old=settings(root);region=body.get('region','us');key=str(body.get('key') or old['key']).strip();url=str(body.get('project_url','')).strip()
    if region not in HOSTS:raise ValueError('Choose US or EU PostHog Cloud.')
    if key and not re.fullmatch(r'phc_[a-zA-Z0-9_-]{12,200}',key):raise ValueError('Use the project ingestion key beginning phc_, not a personal API key.')
    if not isinstance(body.get('enabled'),bool):raise ValueError('Choose whether to send analytics.')
    if body['enabled'] and not key:raise ValueError('Add the PostHog project ingestion key first.')
    if url and not re.fullmatch(r'https://(?:us|eu|app)\.posthog\.com/project/\d+(?:/)?',url):raise ValueError('Use the PostHog project URL, without query parameters.')
    value={'enabled':body['enabled'],'region':region,'key':key,'project_url':url}
    with _lock:
        path=Path(root)/'posthog.json';tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value));tmp.chmod(0o600);tmp.replace(path)
    return status(root)

def status(root):
    s=settings(root)
    with _lock,connect(root) as db:pending=db.execute('SELECT count(*) FROM events WHERE sent=0').fetchone()[0]
    return {k:s[k] for k in ('enabled','region','project_url')}|{'configured':bool(s['key']),'pending_events':pending}

def load(db,key,state):
    row=db.execute('SELECT metadata FROM runs WHERE id=?',(key,)).fetchone()
    if row:return json.loads(row[0])
    return {'rooms':list(state.get('rooms',[False]*3)),'entered':{},'active':{},'steps':{},'ended':bool(state.get('escaped') or hosting.clock(state)['expired'])}

def store(db,key,meta):db.execute('INSERT OR REPLACE INTO runs VALUES (?,?)',(key,json.dumps(meta)))

def emit(db,key,meta,event,props=None,at=None):
    now=time.time() if at is None else at
    payload={'uuid':str(uuid.uuid4()),'event':'haunted_'+event,'properties':{'distinct_id':meta.get('visitor',key),'game_id':key,'$process_person_profile':False,'$geoip_disable':True,'environment':'production' if hosting.hosted() else 'local','analytics_version':1,'practice':meta.get('practice',False),**(props or {})},'timestamp':datetime.datetime.fromtimestamp(now,datetime.timezone.utc).isoformat()}
    db.execute('INSERT INTO events (id,at,payload) VALUES (?,?,?)',(payload['uuid'],now,json.dumps(payload)))

@safe
def observe(root,state,new=False,visitor=None):
    if not state.get('started'):return
    with _lock,connect(root) as db:
        key=pseudonym(root,state['run_id']);meta=load(db,key,state);now=time.time()
        if not meta.get('observed'):
            if visitor:
                try:meta['visitor']=pseudonym(root,'visitor:'+str(uuid.UUID(visitor)))
                except (ValueError,TypeError,AttributeError):pass
            meta['observed']=True;meta['practice']=bool(state.get('practice_reasons'))
            emit(db,key,meta,'shift_started' if new else 'shift_observed',{'historical':not new},state['started'] if new else now)
        meta['practice']=bool(state.get('practice_reasons'))
        for index,ready in enumerate(state.get('rooms',[]),1):
            room=str(index)
            if ready and not meta['rooms'][index-1]:
                extra=now-meta.get('last',now) if meta.get('current')==room and meta.get('visible') else 0
                props={'room':index,'active_seconds':round(meta['active'].get(room,0)+(extra if 0<=extra<=35 else 0),2)}
                if room in meta['entered']:props['elapsed_seconds']=round(now-meta['entered'][room],2)
                emit(db,key,meta,'room_completed',props)
                meta['rooms'][index-1]=True
        job=state.get('noc',{}).get('submission') or {}
        if job.get('id'):
            job_key=pseudonym(root,job['id'])
            if meta.get('job_key')!=job_key:
                meta.update(job_key=job_key,job_seen=now,job_status=job.get('status'))
                emit(db,key,meta,'training_submitted',{'historical':not new and job.get('status') in ('succeeded','failed','cancelled')})
            elif meta.get('job_status')!=job.get('status') and job.get('status') in ('succeeded','failed','cancelled'):
                emit(db,key,meta,'training_finished',{'outcome':job['status'],'duration_seconds':round(now-meta['job_seen'],2)})
            meta['job_status']=job.get('status')
        ended=bool(state.get('escaped') or hosting.clock(state)['expired'])
        if ended and not meta.get('ended'):
            emit(db,key,meta,'shift_completed' if state.get('escaped') else 'shift_expired',{'elapsed_seconds':round((state.get('finished') or now)-state['started'],2),'rooms_completed':sum(bool(r) for r in state['rooms'])})
            meta['ended']=True
        store(db,key,meta)

@safe
def activity(root,state,room,object_id=None,visible=True):
    if not state.get('started') or state.get('escaped') or hosting.clock(state)['expired']:return
    if str(room) not in ('1','2','3'):return
    observe(root,state)
    with _lock,connect(root) as db:
        key=pseudonym(root,state['run_id']);meta=load(db,key,state);now=time.time();room=str(room)
        previous=meta.get('current');delta=now-meta.get('last',now)
        if previous and meta.get('visible') and 0<=delta<=35:
            meta['active'][previous]=meta['active'].get(previous,0)+delta
        if room not in meta['entered']:
            meta['entered'][room]=now;emit(db,key,meta,'room_entered',{'room':int(room)})
        step=OBJECTS.get(object_id)
        if step and step not in meta['steps']:
            meta['steps'][step]={'started':now,'attempts':0};emit(db,key,meta,'step_viewed',{'step':step,'room':STEPS[step]})
        meta.update(current=room,last=now,visible=visible is True and not state.get('paused'));store(db,key,meta)

@safe
def attempt(root,state,step,passed=None,rejected=False,duration=None):
    if step not in STEPS or not state.get('started'):return
    observe(root,state)
    with _lock,connect(root) as db:
        key=pseudonym(root,state['run_id']);meta=load(db,key,state);now=time.time()
        item=meta['steps'].setdefault(step,{'started':now,'attempts':0});item['attempts']+=1
        props={'step':step,'room':STEPS[step],'attempt':item['attempts'],'outcome':'rejected' if rejected else 'passed' if passed is True else 'failed' if passed is False else 'submitted'}
        if duration is not None:props['request_seconds']=round(max(0,duration),3)
        emit(db,key,meta,'step_attempted',props)
        if passed is True and not item.get('passed'):
            item['passed']=True;emit(db,key,meta,'step_completed',{'step':step,'room':STEPS[step],'attempts':item['attempts'],'elapsed_seconds':round(now-item['started'],2)})
        store(db,key,meta)

@safe
def hint(root,state,room):
    if str(room) not in ('1','2','3'):return
    with _lock,connect(root) as db:
        key=pseudonym(root,state['run_id']);meta=load(db,key,state)
        emit(db,key,meta,'hint_requested',{'room':int(room),'hint_number':state['hints'].get(str(room),0)})

@safe
def cloud(root,state,area,action,status,seconds):
    if area not in ('noc','plant') or not re.fullmatch('[a-z-]{1,30}',action):return
    observe(root,state)
    with _lock,connect(root) as db:
        key=pseudonym(root,state['run_id']);meta=load(db,key,state)
        emit(db,key,meta,'cloud_operation_completed',{'area':area,'operation':action,'outcome':status,'duration_seconds':round(max(0,seconds),3)})
    log.info('cloud_operation area=%s operation=%s outcome=%s seconds=%.2f',area,action,status,seconds)

PATHS={'/api/search':'research','/api/research/extract':'documentation','/api/mabel-post':'bookmark','/api/switchboard/test':'switchboard','/api/subscription/test':'speaker','/api/terminal':'door_command','/api/noc/rehearse':'demonstration','/api/noc/record':'training_pack','/api/plant/pipes':'pipes','/api/plant/deploy':'commissioning'}

@safe
def action(root,state,path,body,result=None,rejected=False,duration=None):
    step=PATHS.get(path)
    passed=None
    if path=='/api/hint' and not rejected:hint(root,state,body.get('room'));return
    if not step or (step=='commissioning' and not rejected):return
    if not rejected:
        if step=='switchboard':passed=bool(state.get('board',{}).get('ready'))
        elif step=='speaker':passed=bool(state.get('subscription',{}).get('passed'))
        elif step=='pipes':passed=bool(state.get('plant',{}).get('pipe_report',{}).get('passed'))
        elif step=='demonstration':passed=bool(state['noc'].get('demonstrations',{}).get(body.get('camera'),{}).get('correct'))
        elif step in ('research','documentation','bookmark','training_pack'):passed=True
        elif step=='door_command':passed=bool(state.get('door_signal'))
    attempt(root,state,step,passed,rejected,duration)

@safe
def flush(root):
    s=settings(root)
    if not s['enabled'] or not s['key'] or s['region'] not in HOSTS:return
    with _lock,connect(root) as db:rows=db.execute('SELECT id,payload FROM events WHERE sent=0 ORDER BY at LIMIT 100').fetchall()
    if not rows:return
    body=json.dumps({'api_key':s['key'],'batch':[json.loads(row[1]) for row in rows]}).encode()
    request=Request(HOSTS[s['region']]+'/batch/',data=body,headers={'Content-Type':'application/json','User-Agent':'haunted-datacenter-analytics/1'})
    with urlopen(request,timeout=8) as response:
        if response.status!=200:raise OSError('PostHog did not accept the batch')
    with _lock,connect(root) as db:
        db.executemany('UPDATE events SET sent=1 WHERE id=?',[(r[0],) for r in rows])
        db.execute('DELETE FROM events WHERE sent=1 AND at<?',(time.time()-30*86400,))

def start(root):
    with _lock:
        key=str(Path(root).resolve())
        if key in _started:return
        _started.add(key)
    def deliver():
        while True:
            time.sleep(10);flush(root)
    threading.Thread(target=deliver,daemon=True,name='posthog-delivery').start()
