#!/usr/bin/env python3
"""UUID-isolated escape-room saves on one shared application and CPU runner."""
import argparse, json, os, secrets, subprocess, sys, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse,parse_qs
import content
import caretaker, copy
import switchboard,clue_post,plant,lessons,serverless,hosting,sessions

ROOT=Path(__file__).resolve().parent
RUNTIME=Path(os.environ.get('GAME_DATA_DIR',str(ROOT/'.runtime'))); RUNTIME.mkdir(parents=True,exist_ok=True)
TOKEN=secrets.token_urlsafe(24)
LOCK=threading.RLock()

def fresh():
    return hosting.initialize({'plant':plant.initial(),'noc':caretaker.initial(),'puzzle_version':switchboard.VERSION,'board':switchboard.initial(),'created_at':time.time(),'mode':'rehearsal','started':None,'paused':False,'pause_at':None,'pause_total':0,'evidence':None,'calibration':False,'rooms':[False,False,False],'guard':False,'training':None,'endpoint':False,'baseline':None,'evaluation':None,'escaped':False,'hints':{'1':0,'2':0,'3':0},'sources':{'retry':content.RETRY_STARTER,'guard':content.RUNBOOK_STARTER,'dataset':content.starter_records()},'log':[{'text':'Incident SEV-0 opened. Previous on-call engineer: still assigned.','at':time.time()}]})

try: STATE=json.loads((RUNTIME/'state.json').read_text())
except (OSError,ValueError): STATE=fresh()
if STATE.get('puzzle_version')!=switchboard.VERSION:
    (RUNTIME/'before-switchboard-state.json').write_text(json.dumps(STATE))
    old_mode=STATE.get('mode','rehearsal');STATE=fresh();STATE['mode']=old_mode
    (RUNTIME/'state.json').write_text(json.dumps(STATE))

if STATE.get('plant',{}).get('version')!=plant.VERSION: STATE['plant']=plant.initial()
if (STATE['plant'].get('operation') or {}).get('status')=='running': STATE['plant']['operation'].update(status='interrupted',message='Diagnostic request interrupted. Ask again when ready.')

if STATE.get('noc',{}).get('version')!=caretaker.VERSION:
    (RUNTIME/('before-noc-upgrade-'+str(int(time.time()))+'.json')).write_text(json.dumps(STATE))
    STATE['noc']=caretaker.initial();STATE['rooms'][1]=False;STATE['rooms'][2]=False;STATE['escaped']=False
    STATE['sources']['dataset']=content.starter_records()
    (RUNTIME/'state.json').write_text(json.dumps(STATE))
if (STATE['noc'].get('operation') or {}).get('status')=='running':
    STATE['noc']['operation'].update(status='interrupted',message='Server restarted during this operation. Check cloud status before retrying training or deployment.')

# Preserve saved lessons/jobs while retiring the old default shortcut.
if STATE['noc'].get('flow_version')!=2:
    (RUNTIME/('before-own-checkpoint-'+str(int(time.time()))+'.json')).write_text(json.dumps(STATE))
    n=STATE['noc'];n['flow_version']=2
    if n.get('route')!='untrained' and (n.get('job') or {}).get('id')!=(n.get('submission') or {}).get('id'):
        n['route']='untrained';n['report']=None;n.pop('final',None)
        if n.get('runner'):n['runner']['active']=False
        STATE['rooms'][1]=False;STATE['rooms'][2]=False;STATE['escaped']=False

hosting.initialize(STATE)
# Persist the original host UUID before accepting independent player sessions.
_temp=RUNTIME/'state.tmp';_temp.write_text(json.dumps(STATE));_temp.chmod(0o600);_temp.replace(RUNTIME/'state.json')

class GameContext:
    """Request-local game data; the original host save remains the default locally.

    ContextVars isolate concurrent HTTP requests. Background workers explicitly
    inherit the originating context, so another browser cannot redirect a result.
    """
    @property
    def state(self):return sessions.CURRENT.get().state if sessions.CURRENT.get() else STATE
    @state.setter
    def state(self,value):
        global STATE
        if sessions.CURRENT.get():sessions.CURRENT.get().state=value
        else:STATE=value
    @property
    def runtime(self):return sessions.CURRENT.get().runtime if sessions.CURRENT.get() else RUNTIME
    @property
    def root(self):return sessions.CURRENT.get().root if sessions.CURRENT.get() else RUNTIME
    @property
    def lock(self):return sessions.CURRENT.get().lock if sessions.CURRENT.get() else LOCK
    @property
    def token(self):return sessions.CURRENT.get().token if sessions.CURRENT.get() else TOKEN
    @property
    def admin(self):return sessions.ADMIN.get()
G=GameContext()

def background(worker):
    context=__import__('contextvars').copy_context()
    threading.Thread(target=context.run,args=(worker,),daemon=True).start()

class LegacyGame:
    @property
    def state(self):return STATE
    @state.setter
    def state(self,value):
        global STATE
        STATE=value
    @property
    def runtime(self):return RUNTIME
    @property
    def root(self):return RUNTIME
    @property
    def lock(self):return LOCK
    @property
    def token(self):return TOKEN
LEGACY=LegacyGame()
def legacy_game():return LEGACY

def maintenance_access():
    n=G.state['noc'];j=n.get('submission') or {}
    return bool(G.state['rooms'][0] and j.get('id') and j.get('pack_hash')==lessons.packet_hash(n,G.state['sources']['dataset']))

def save():
    temp=G.runtime/'state.tmp'; temp.write_text(json.dumps(G.state)); temp.chmod(0o600); temp.replace(G.runtime/'state.json')

def event(message):
    G.state['log'].append({'text':message,'at':time.time()}); G.state['log']=G.state['log'][-40:]

def refresh_archive():
    """Unlock from the current evidence, diagnosis and code in any completion order."""
    if G.state.get('puzzle_version')==switchboard.VERSION: return
    report=G.state.get('retry_report')
    if not report: return
    report['needs_evidence']=bool(report.get('passed') and not G.state['evidence'])
    report['needs_calibration']=bool(report.get('passed') and not G.state.get('calibration'))
    ready=bool(report.get('passed') and G.state['evidence'] and G.state.get('calibration'))
    if ready and not G.state['rooms'][0]: event('Archive door restored. The retry storm subsides. One ghost unsubscribes.')
    G.state['rooms'][0]=ready

def refresh_switchboard():
    ready=bool(G.state.get('board',{}).get('ready') and G.state.get('board_citation') and G.state.get('topic_evidence') and G.state.get('switchboard_applied') and G.state.get('door_signal') and G.state.get('subscription',{}).get('passed'))
    if ready and not G.state['rooms'][0]:event('All three ghosts routed correctly. Research verified. Archive door unlocked.')
    G.state['rooms'][0]=ready

def view():
    if not G.state.get('board',{}).get('routes') and not G.state.get('board',{}).get('attempts'):
        G.state['board']=switchboard.initial();save()
    if G.state['training'] and G.state['training']['status']=='running' and time.time()-G.state['training']['started']>=16:
        G.state['training']['status']='succeeded'; event('REHEARSAL: scripted training walkthrough complete. No weights trained.'); save()
    return {**G.state,'timer':hosting.clock(G.state),'has_session':True,'is_host':G.admin,'authenticated':True,'hosted':hosting.hosted(),'maintenance_route_open':maintenance_access(),'noc':{**G.state['noc'],'maintenance_notes':lessons.NOTES},'maintenance_notes':lessons.NOTES,'cooling_controller':serverless.pool_status(G.root),'serverless_configured':bool(serverless.config(G.root)['project_id'] and serverless.config(G.root)['subnet_id']),'plant_definition':plant.definition(),'training_seed_before':content.starter_records(),'mabel_post_url':clue_post.public_url(),'mabel_post_html':clue_post.article(),'memory_status':content.memory_status(G.state['sources']['dataset']),'live_report':None,'token':G.token,'tavily_available':bool(__import__('shutil').which('tvly')),'nebius_configured':bool(os.environ.get('NEBIUS_API_KEY') or os.environ.get('NEBIUS_TOKEN_FACTORY_KEY'))}

def launch_noc(action,body):
    noc=G.state['noc']
    if (noc.get('operation') or {}).get('status')=='running':raise ValueError('The caretaker is already working. Wait for the current operation.')
    snapshot=copy.deepcopy(noc);source=G.state['sources']['dataset'];session=G.state['run_id']
    if action in ('test','verify','train','deploy','backup','prompt-profile','load-own'):
        snapshot['previous_report']=snapshot.get('report');snapshot['report']=None;snapshot.pop('final',None);noc['report']=None;noc.pop('final',None)
    if action in ('final','verify'):snapshot.pop('final',None)
    noc['operation']={'action':action,'status':'running','message':'Checking the caretaker…','started':time.time()};noc['revision']+=1
    if action in ('test','verify','train','deploy','backup','prompt-profile','load-own','final'):
        G.state['rooms'][1]=False;G.state['rooms'][2]=False;G.state['escaped']=False
    def progress(message):
        with G.lock:
            if G.state['run_id']==session:
                G.state['noc']['operation']['message']=message;G.state['noc']['revision']+=1;save()
    def worker():
        try:message=caretaker.run(action,snapshot,body,source,G.runtime,progress);status='succeeded'
        except (ValueError,KeyError,TypeError,OSError) as error:
            message=str(error) if isinstance(error,ValueError) else 'Cloud operation failed ('+type(error).__name__+'). Check configuration and refresh cloud status.';status='failed'
        except Exception as error:message='Cloud operation failed ('+type(error).__name__+'). No automatic retry.';status='failed'
        with G.lock:
            if G.state['run_id']!=session:
                (G.runtime/('noc-recovered-'+str(session)+'-'+action+'.json')).write_text(json.dumps({'action':action,'status':status,'noc':snapshot}))
                return
            snapshot['operation']={'action':action,'status':status,'message':message,'finished':time.time()}
            snapshot['revision']=G.state['noc']['revision']+1;G.state['noc']=snapshot
            if action in ('final','verify'):G.state['rooms'][1]=bool(status=='succeeded' and snapshot.get('final',{}).get('passed'))
            save()
    background(worker)


def launch_plant(action,body):
    p=G.state['plant'];session=G.state['run_id'];lease=G.state['run_id']
    if (p.get('operation') or {}).get('status')=='running':raise ValueError('A cloud request is still running. You can place pipes while deployment submits.')
    if action in ('deploy','replace'):serverless.allow(G.root,lease)
    snapshot=copy.deepcopy(p)
    if action in ('deploy','health','test','replace'):snapshot['report']=None
    if action in ('deploy','health','replace'):snapshot['health']=None
    board=plant.normalize(body.get('pipes',p['pipes']))
    if action in ('deploy','health','test','replace'):p['report']=None;G.state['rooms'][2]=False;G.state['escaped']=False
    p['operation']={'action':action,'status':'running','message':{'deploy':'Connecting to the reusable CPU controller (or creating it on the first shift)…','refresh':'Reading cloud endpoint status…','health':'Requesting the deployed app’s /healthz route…','test':'Sending this circuit’s sensor report to the real app…','logs':'Reading the real app’s logs…','replace':'Stopping the old app and deploying the corrected configuration…'}[action]};p['revision']+=1
    def worker():
        try:
            if action=='deploy':message=serverless.deploy(snapshot,body,G.root,lease,shared=bool(sessions.CURRENT.get()))
            elif action=='replace':message=serverless.replace(snapshot,body,G.root,lease,shared=bool(sessions.CURRENT.get()))
            elif action=='refresh':message=serverless.refresh(snapshot,G.root)
            elif action=='health':message=serverless.health(snapshot,G.root)
            elif action=='logs':message=serverless.logs(snapshot,G.root)
            else:message=serverless.assess(snapshot,G.root,board)
            status='succeeded'
        except (ValueError,OSError,KeyError,TypeError) as error:message=str(error) if isinstance(error,ValueError) else 'Cloud request failed. Check the endpoint in the console.';status='failed'
        except Exception:message='Cloud operation failed. Check the endpoint status and try the specific check again.';status='failed'
        with G.lock:
            if G.state['run_id']!=session:return
            current=G.state['plant']
            for key in ('endpoint','health','deployment_unknown','cloud_logs','previous_endpoints'):
                if key in snapshot:current[key]=snapshot[key]
            if action=='test':
                for key in ('settings','pipes','pipe_report','report'):current[key]=snapshot.get(key)
            current['operation']={'action':action,'status':status,'message':message,'finished':time.time()};current['revision']+=1;save()
    background(worker)

def launch_plant_advice(values):
    current=G.state['plant'];session=G.state['run_id']
    if (current.get('operation') or {}).get('status')=='running':raise ValueError('The diagnostic model is already reading the logs.')
    settings=plant.settings(values);current['operation']={'status':'running','message':'Token Factory is reading the controller logs…'};current['revision']+=1
    def worker():
        try:reply=plant.advise(settings);status='succeeded';message='Real Token Factory diagnostic reply received.'
        except Exception as error:reply=None;status='failed';message=str(error) if isinstance(error,ValueError) else 'Diagnostic request failed. Check the local server and try again.'
        with G.lock:
            if G.state['run_id']!=session:return
            G.state['plant']['operation']={'status':status,'message':message};G.state['plant']['advice']=reply;G.state['plant']['revision']+=1;save()
    background(worker)

def run_code(kind,source):
    if len(source)>20000: raise ValueError('Puzzle source is too long.')
    path=G.runtime/f'{kind}.py'; path.write_text(source)
    env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL','TMPDIR','SYSTEMROOT')}
    result=subprocess.run([sys.executable,'-I',str(ROOT/'check_puzzle.py'),str(path),kind],capture_output=True,text=True,timeout=5,cwd=G.runtime,env=env)
    try: return json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError,IndexError): return {'passed':False,'error':'Puzzle did not return a test report. Check syntax and return values.'}

class Handler(BaseHTTPRequestHandler):
    def json(self,data,status=200,extra_headers=None):
        body=json.dumps(data).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Content-Length',str(len(body)))
        for key,value in (extra_headers or {}).items(): self.send_header(key,value)
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):self.dispatch(self.get)
    def do_POST(self):self.dispatch(self.post)
    def dispatch(self,handler):
        path=urlparse(self.path);value=self.headers.get('X-Run-ID') or parse_qs(path.query).get('run',[None])[0]
        admin=hosting.authenticated(self.headers)
        try:
            game=None
            if value:
                value=sessions.identifier(value)
                if value!=STATE['run_id']:game=sessions.get(RUNTIME,value)
                else:game=legacy_game()
            elif not admin and path.path.startswith('/api/') and path.path not in ('/api/state','/api/sessions','/api/login','/api/leaderboard'):
                self.json({'error':'Start a shift or enter its UUID first.'},401);return
            self.has_game=bool(value or admin)
            with sessions.scope(game,admin):handler()
        except ValueError as error:self.json({'error':str(error)},404)
    def get(self):
        path=urlparse(self.path).path
        if path=='/healthz': self.json({'ok':True,'version':'shift-entry-v3'});return
        if path=='/api/leaderboard': self.json({'entries':[{k:v for k,v in row.items() if k!='run_id'} for row in hosting.leaderboard(G.root)]});return
        if path=='/api/state':
            if not self.has_game:self.json({'authenticated':True,'hosted':hosting.hosted(),'has_session':False,'is_host':False});return
            with G.lock:
                n=G.state['noc'];job=n.get('submission') or {}
                if not hosting.clock(G.state)['expired'] and job.get('id') and job.get('status') not in ('succeeded','failed','cancelled') and time.time()-n.get('polled_at',0)>=20 and (n.get('operation') or {}).get('status')!='running':
                    n['polled_at']=time.time();launch_noc('refresh',{})
                if (G.state['plant'].get('endpoint') and not G.state.get('escaped') and not hosting.clock(G.state)['expired']):serverless.touch(G.root,G.state['run_id'])
                self.json(view())
            return
        files={'/controller.py':('cloud_controller.py','text/plain'),'/training-replay.json':('web/training-replay.json','application/json'),'/plant.js':('web/plant.js','text/javascript'),'/mabel-post.html':('web/mabel-post.html','text/html'),'/noc.js':('web/noc.js','text/javascript'),**{'/cameras/'+c['id']+'.png':('web/cameras/'+c['id']+'.png','image/png') for c in caretaker.CAMERAS},'/':('web/index.html','text/html'),'/room.js':('web/room.js','text/javascript'),'/app.js':('web/app.js','text/javascript'),'/style.css':('web/style.css','text/css')}
        if path not in files: self.send_error(404); return
        file,mime=files[path]; data=(ROOT/file).read_bytes()
        self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer');self.send_header('Cache-Control','no-cache');self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'");self.end_headers();self.wfile.write(data)
    def post(self):
        path=urlparse(self.path).path
        origin=self.headers.get('Origin')
        if origin and urlparse(origin).netloc!=self.headers.get('Host'): self.json({'error':'Cross-origin request refused.'},403);return
        if path=='/api/login':
            try:
                length=int(self.headers.get('Content-Length',0))
                if not 0<length<=1024:raise ValueError('Invalid sign-in request.')
                body=json.loads(self.rfile.read(length))
                if not isinstance(body,dict):raise ValueError('Invalid sign-in request.')
                cookie=hosting.login(body.get('code',''),self.client_address[0])
                self.json({'ok':True},extra_headers={'Set-Cookie':cookie})
            except (ValueError,TypeError,KeyError):self.json({'error':'Host code did not match, or too many attempts. Wait one minute before trying again.'},401)
            return
        if path=='/api/sessions':
            try:
                length=int(self.headers.get('Content-Length',0))
                if not 0<length<=1024:raise ValueError('Enter your name to start a shift.')
                body=json.loads(self.rfile.read(length))
                if not isinstance(body,dict):raise ValueError('Enter your name to start a shift.')
                hosting.allow_new_shift(self.client_address[0])
                name=hosting.player_name(body.get('name',''))
                game=sessions.create(RUNTIME,fresh,name,start=True)
                with sessions.scope(game,G.admin):self.json({'state':view()})
            except (ValueError,TypeError) as error:self.json({'error':str(error) if isinstance(error,ValueError) else 'Enter a display name between 1 and 40 characters.'},400)
            return
        if not self.has_game:self.json({'error':'Start a shift or enter its UUID first.'},401);return
        if self.headers.get('X-Game-Token')!=G.token: self.json({'error':'Refresh the page to reconnect.'},403);return
        if hosting.clock(G.state)['expired'] and path!='/api/host':
            self.json({'error':'This game’s 45 minutes are up. Start a new game.', 'expired':True},410);return
        if hosting.hosted() and path in ('/api/check','/api/repair','/api/calibrate','/api/baseline','/api/train','/api/deploy','/api/evaluate','/api/dataset'):
            self.json({'error':'This retired local-editor route is disabled in the hosted game.'},403);return
        try:
            length=int(self.headers.get('Content-Length',0))
            if urlparse(self.path).path=='/api/noc/import':
                if not 0<length<=64*1024*1024:raise ValueError('Choose a LoRA adapter under 64 MiB.')
                uploaded=self.rfile.read(length)
                if len(uploaded)!=length:raise ValueError('Upload was incomplete.')
                with G.lock:
                    launch_noc('load-own',{'uploaded':uploaded});save();self.json({'state':view()})
                return
            if not 0<=length<=50000: raise ValueError('Invalid request size.')
            body=json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(body,dict):raise ValueError('Use a JSON object for this request.')
            with G.lock:
                result=self.action(urlparse(self.path).path,body);save();self.json({'state':view(),**(result or {})})
        except subprocess.TimeoutExpired: self.json({'error':'Operation timed out. Your progress is saved.'},408)
        except (ValueError,KeyError,TypeError,FileNotFoundError) as e:self.json({'error':str(e)},400)
        except Exception as e:self.json({'error':f'Operation failed ({type(e).__name__}). Check the local terminal.'},500)
    def action(self,path,b):
        if hosting.clock(G.state)['expired'] and not (path=='/api/host' and b.get('action')=='reset'):
            raise ValueError('This game’s 45 minutes are up. Start a new game.')
        if not G.admin and (path=='/api/solution' or path in ('/api/noc/playtest','/api/noc/deploy') or (path=='/api/host' and b.get('action') not in ('pause','reset'))):
            raise ValueError('This experiment requires host access. Normal play does not need a host code.')
        if path=='/api/start':
            if not G.state['started']: G.state['player_name']=hosting.player_name(b.get('name') or ('Night shift' if not hosting.hosted() else ''))
            if not G.state['started']: G.state['started']=time.time();G.state['paused']=False;G.state['pause_at']=None;G.state['pause_total']=0;event('You accepted the pager. Forty-five minutes until midnight.')
        elif path=='/api/host':
            act=b['action']
            if act in ('caretaker-backup','caretaker-prompt'):
                hosting.practice(G.state,'Host model experiment')
                launch_noc('backup' if act=='caretaker-backup' else 'prompt-profile',{'host_override':True})
            elif act=='reset':
                if not G.admin:hosting.allow_new_shift(self.client_address[0])
                serverless.release(G.root,G.state['run_id'],copy.deepcopy(G.state['plant'].get('endpoint')))
                if sessions.CURRENT.get():
                    G.state['plant']['health']=None;G.state['plant']['report']=None;save()
                    sessions.CURRENT.set(sessions.create(G.root,fresh))
                else:G.state=fresh()
            elif act=='pause':
                hosting.practice(G.state,'Timer paused')
                if not G.state['paused']: G.state['pause_at']=time.time();G.state['paused']=True
                else: G.state['pause_total']+=time.time()-G.state['pause_at'];G.state['paused']=False;G.state['pause_at']=None
            elif act in ('live','rehearsal'):
                if G.state['mode']!=act:
                    # Keep code edits; clear all gates to prevent simulated evidence carrying into live mode.
                    serverless.release(G.root,G.state['run_id'],copy.deepcopy(G.state['plant'].get('endpoint')))
                    sources=G.state['sources']
                    if sessions.CURRENT.get():sessions.CURRENT.set(sessions.create(G.root,fresh))
                    else:G.state=fresh()
                    G.state['sources']=sources;G.state['mode']=act
                    event(f'Mode changed to {act}. Gates and timer reset; code edits retained.')
        elif path=='/api/solution':
            hosting.practice(G.state,'Host solution used')
            kind=b['kind']
            if kind not in ('retry','dataset','guard'): raise ValueError('Unknown solution.')
            return {'source': {'retry':content.RETRY_SOLUTION,'guard':content.RUNBOOK_SOLUTION,'dataset':'\n'.join(json.dumps(r) for r in content.clean_records())}[kind], 'settings': {'fallback':60,'floor':0,'direction':'until'} if kind=='retry' else None, 'routes': {k:v['protocol'] for k,v in switchboard.GHOSTS.items()} if kind=='retry' else None}
        elif path=='/api/hint':
            room=str(b['room']); n=G.state['hints'][room];G.state['hints'][room]=min(n+1,3)
            return {'hint':content.HINTS[room][min(n,2)]}
        elif path=='/api/mabel-post':
            source=clue_post.saved_post() if b.get('bookmark') and not clue_post.public_url() else clue_post.retrieve(bool(b.get('archived')),G.state['mode'])
            G.state['topic_evidence']=source;refresh_switchboard()
            event('Mabel’s topic recovered from '+('her saved bookmark.' if source['kind']=='saved-post' else 'a marked rehearsal draft.' if source['kind']=='rehearsal' else 'a live Tavily extraction.'))
            return {'source':source}
        elif path=='/api/search':
            if b.get('archived'):
                if G.state['mode']!='rehearsal': raise ValueError('Live mode requires a real Tavily search.')
                sources=switchboard.ARCHIVE;G.state['evidence']='fixture';event('REHEARSAL: loaded illustrative protocol references.')
            else:
                query=str(b.get('query','')).strip()[:350]
                if len(query)<3: raise ValueError('What are you investigating? Enter a search based on the room’s clues.')
                proc=subprocess.run(['tvly','search',query,'--depth','advanced','--include-domains','mqtt.org,mosquitto.org,docs.oasis-open.org,rfc-editor.org,developer.mozilla.org','--max-results','5','--json'],capture_output=True,text=True,timeout=40)
                if proc.returncode: raise ValueError('Tavily search failed. Run tvly --status in your terminal to check authentication.')
                data=json.loads(proc.stdout);sources=data.get('results',[])
                sources=[{'title':x.get('title','Source'),'url':x['url'],'content':x.get('content','')[:700]} for x in sources if urlparse(x.get('url','')).hostname in ('mqtt.org','www.mqtt.org','mosquitto.org','www.mosquitto.org','docs.oasis-open.org','www.rfc-editor.org','rfc-editor.org','developer.mozilla.org')]
                sources=[{**x,'protocols':switchboard.source_protocols(x)} for x in sources]
                sources=[x for x in sources if x['protocols']]
                sources.sort(key=lambda x: 0 if '/en-US/' in x['url'] else 1 if urlparse(x['url']).path.startswith('/docs/') else 2)
                unique=[];seen=set()
                for source in sources:
                    identity=(urlparse(source['url']).hostname, urlparse(source['url']).path.rsplit('/',1)[-1].lower())
                    if identity not in seen: unique.append(source);seen.add(identity)
                sources=unique[:3]
                if not sources: raise ValueError('No protocol reference found. Try describing what the ghost wants to do, or research one of the socket labels.')
                G.state['evidence']='tavily';event('Tavily evidence retrieved from authoritative documentation.')
            G.state['search_results']=sources
            # A search is discovery. Players must explicitly inspect a source.

            refresh_switchboard();return {'sources':sources}
        elif path=='/api/research/extract':
            url=b.get('url');source=next((x for x in G.state.get('search_results',[]) if x['url']==url),None)
            if not source:raise ValueError('Choose a source returned by your Tavily search.')
            if 'MQTT' not in source.get('protocols',[]):raise ValueError('This reference covers another protocol. Find MQTT topic-filter documentation for the speaker.')
            proc=subprocess.run(['tvly','extract',url,'--query','MQTT topic filter + single level wildcard # multi level wildcard subscription topic levels','--chunks-per-source','3','--extract-depth','advanced','--json'],capture_output=True,text=True,timeout=45)
            if proc.returncode:raise ValueError('Tavily Extract could not read that source. Try another documentation result.')
            data=json.loads(proc.stdout);rows=data.get('results',[])
            if not rows:raise ValueError('No readable document returned. Choose another source.')
            text=rows[0].get('raw_content') or rows[0].get('content','')
            if not text.strip():raise ValueError('The source had no extractable text. Try another reference.')
            G.state['board_citation']={**source,'content':text[:6000],'kind':'tavily-extract'}
            refresh_switchboard();return {'source':G.state['board_citation']}
        elif path=='/api/subscription/test':
            G.state['subscription']=switchboard.test_subscription(b.get('filter',''))
            G.state['switchboard_applied']=False;G.state['door_signal']=False
            refresh_switchboard();return {'report':G.state['subscription']}
        elif path=='/api/switchboard/test':
            previous=G.state.get('board',switchboard.initial())
            board=switchboard.evaluate(b.get('routes',{}));board['attempts']=previous.get('attempts',0)+1
            if board['routes']!=previous['routes']:
                G.state['switchboard_applied']=False;G.state['door_signal']=False
            G.state['board']=board;refresh_switchboard()
            event('Switchboard test sent. '+str(sum(r['correct'] for r in board['results']))+'/3 ghost services working.')
            return {'board':board}
        elif path=='/api/terminal':
            command=b.get('command','')
            output=switchboard.terminal_command(G.state,command)
            G.state['terminal_history']=(G.state.get('terminal_history',[])+[{'command':command.strip(),'output':output}])[-20:]
            refresh_switchboard()
            return {'output':output}
        elif path.startswith('/api/plant/'):
            action=path.rsplit('/',1)[1];p=G.state['plant']
            if action in ('deploy','refresh','health','test','logs','replace'):
                if not maintenance_access() and not G.state['noc'].get('playtest'):raise ValueError('Submit the caretaker training job before entering the generator room.')
                launch_plant(action,b)
            elif action=='pipes':
                if (p.get('operation') or {}).get('action')=='test' and p['operation']['status']=='running':raise ValueError('Wait for the cooling test before editing pipes.')
                board=plant.normalize(b.get('pipes',{}));p['pipes']=board;p['pipe_report']=plant.check_pipes(board);p['report']=None
                G.state['rooms'][2]=False;G.state['escaped']=False;p['revision']+=1
            elif action=='escape':
                board=plant.normalize(b.get('pipes',{}));report=p.get('report') or {}
                if not G.state['rooms'][0] or not G.state['rooms'][1]:raise ValueError('Restore communications and certify the caretaker before releasing the exit.')
                if not report.get('passed') or not report.get('request_nonce') or report.get('endpoint_id')!=(p.get('endpoint') or {}).get('id') or report.get('board_hash')!=plant.fingerprint(board) or not plant.check_pipes(board)['passed']:raise ValueError('Complete the circuit, deploy the controller, and pass its live cooling test with this layout.')
                G.state['rooms'][2]=True;G.state['escaped']=True;G.state['finished']=time.time();event('Closed cooling circuit stable. Cloud controller healthy. Everyone leaves together.')
                G.state['result']=hosting.record(G.state,G.root)
                serverless.release(G.root,G.state['run_id'],copy.deepcopy(p.get('endpoint')))
            else:raise ValueError('Unknown generator-room action.')
        elif path.startswith('/api/noc/'):
            action=path.rsplit('/',1)[1]
            if action in ('backup','prompt-profile'):raise ValueError('Fallbacks and prompt experiments are available in host controls only.')
            if action=='playtest':
                hosting.practice(G.state,'Room playtest shortcut')
                G.state['noc']['playtest']=True;G.state['noc']['revision']+=1
                G.state['started']=time.time();G.state['paused']=False;G.state['pause_at']=None;G.state['pause_total']=0;G.state.pop('finished',None)
            elif action in ('evidence','rehearse','try-probe'):
                if (G.state['noc'].get('operation') or {}).get('status')=='running':raise ValueError('Wait for the current model request.')
                message=caretaker.run(action,G.state['noc'],b,G.state['sources']['dataset'],G.runtime,lambda _:None)
                G.state['noc']['revision']+=1
                return {'message':message}
            elif action=='preview':
                if not lessons.complete(G.state['noc']):raise ValueError('Record the three camera lessons first.')
                rows,errors=content.validate_seed(G.state['sources']['dataset'])
                if errors:raise ValueError(errors[0])
                return {'records':content.expand(rows,content.TRAIN_TEMPLATES)+[content.record(x['input'],x['answer']) for x in G.state['noc']['lessons'].values()]}
            elif action=='record':
                if (G.state['noc'].get('operation') or {}).get('status')=='running':raise ValueError('Wait for the caretaker’s current request.')
                G.state['sources']['dataset']=lessons.record(G.state['noc'],b.get('camera'),G.state['sources']['dataset'])
                _,errors=content.validate_seed(G.state['sources']['dataset']);G.state['noc']['dataset_report']={'passed':not errors,'errors':errors};G.state['noc']['revision']+=1
                G.state['rooms'][1]=False;G.state['rooms'][2]=False;G.state['escaped']=False
            elif action=='memory':
                if (G.state['noc'].get('operation') or {}).get('status')=='running':raise ValueError('Wait for the caretaker to finish its current task.')
                source=content.repair_memory(G.state['sources']['dataset'],b.get('memory'),b.get('choice'))
                return self.action('/api/dataset',{'source':source})
            elif action=='settings':
                if (G.state['noc'].get('operation') or {}).get('status')=='running':raise ValueError('Wait for the current operation before changing settings.')
                if G.state['noc'].get('runner') and G.state['noc'].get('route')!='prompt' and b.get('base_model',G.state['noc']['runner']['model'])!=G.state['noc']['runner']['model']:raise ValueError('This local backup uses '+G.state['noc']['runner']['model']+'. Load a different checkpoint to change its base model.')
                G.state['noc']['config']=caretaker.settings(b,G.state['noc']['config']);G.state['noc']['report']=None;G.state['noc'].pop('final',None);G.state['rooms'][1]=False;G.state['rooms'][2]=False;G.state['escaped']=False;G.state['noc']['revision']+=1
            elif action=='review':
                if (G.state['noc'].get('operation') or {}).get('status')=='running':raise ValueError('Wait for the camera inspection to finish.')
                observation=G.state['noc']['observations'].get(b.get('camera'))
                if not observation:raise ValueError('Inspect this camera first.')
                equipment=str(b.get('equipment','')).strip().lower();fault=str(b.get('fault','')).strip().lower()
                request=caretaker.camera_request(equipment,fault)
                observation.update(equipment=equipment,fault=fault,request=request,reviewed=True);G.state['noc']['revision']+=1
            elif action in ('connect','inspect','vision','review-probe','probe','test','verify','train','refresh','deploy','backup','prompt-profile','load-own','final','evidence','rehearse','try-probe'):
                if not G.state['rooms'][0] and not G.state['noc'].get('playtest') and action not in ('connect','refresh'):raise ValueError('Restore Room 1 before running the caretaker. You can explore this room first.')
                launch_noc(action,b)
            else:raise ValueError('Unknown caretaker action.')
        elif path=='/api/calibrate':
            if b.get('kind')!='absolute': raise ValueError('That interpretation does not fit the server’s value. Compare the manual with your research.')
            try: wait=int(str(b.get('wait','')))
            except ValueError: raise ValueError('Enter the wait as a whole number of seconds.')
            if wait<120: raise ValueError('That would retry before the scheduled recovery. Compare the reply time with the clock’s receipt time.')
            if wait>120: raise ValueError('That would wait past the scheduled recovery. Check the interval and its units.')
            G.state['calibration']=True;event('Last reply reconstructed. Controller diagnostic console unlocked.');refresh_archive()
        elif path=='/api/repair':
            source,settings=content.configured_retry_source(b.get('settings'))
            G.state['retry_settings']=settings
            return self.action('/api/check',{'kind':'retry','source':source})
        elif path=='/api/check':
            kind=b['kind']
            if kind not in ('retry','guard'): raise ValueError('Unknown puzzle.')
            source=b['source'];G.state['sources'][kind]=source
            report=run_code(kind,source)
            G.state[f'{kind}_report']=report
            if kind=='retry': refresh_archive()
            else:
                G.state['guard']=bool(report['passed'])
                if G.state['guard']: event('Runbook guard passed. Documents no longer issue commands.')
            return {'report':report}
        elif path=='/api/dataset':
            if (G.state['noc'].get('operation') or {}).get('status')=='running': raise ValueError('Wait for the current caretaker operation before editing training records.')
            G.state['sources']['dataset']=b['source'];rows,errors=content.validate_seed(b['source'])
            G.state['noc']['report']=None;G.state['noc'].pop('final',None);G.state['rooms'][1]=False;G.state['rooms'][2]=False;G.state['escaped']=False
            G.state['noc']['dataset_report']={'passed':not errors,'errors':errors};G.state['noc']['revision']+=1
            return {'report':{'passed':not errors,'errors':errors,'valid':len(rows),'total':9}}
        elif path=='/api/baseline':
            if G.state['mode']!='rehearsal': raise ValueError('For live baseline inference, use tokenfactory.py evaluate. See host panel.')
            G.state['baseline']={'score':0,'total':27,'label':'Scripted example; no model inference'};event('REHEARSAL baseline: 0/27. This is an illustrative result, not a measured score.')
        elif path=='/api/train':
            if not G.state['rooms'][0]: raise ValueError('Restore the archive door first.')
            if G.state['mode']!='rehearsal': raise ValueError('Use tokenfactory.py train to submit a real job. See host panel.')
            if not G.state['baseline']: raise ValueError('Run the baseline before repairing the caretaker.')
            G.state['sources']['dataset']=b['source'];counts=content.write_datasets(b['source'])
            G.state['training']={'status':'running','started':time.time(),'counts':counts};G.state['endpoint']=False;G.state['evaluation']=None;G.state['rooms'][1]=False
            event('REHEARSAL: scripted training started. Investigate the exit while it runs.')
        elif path=='/api/deploy':
            if G.state['mode']!='rehearsal': raise ValueError('Deploy via tokenfactory.py or the Token Factory console.')
            view()
            if not G.state['training'] or G.state['training']['status']!='succeeded': raise ValueError('Wait for the training walkthrough to finish.')
            G.state['endpoint']=True;event('REHEARSAL: mock dedicated endpoint ready. No cloud resource created.')
        elif path=='/api/evaluate':
            raise ValueError('Use the Mac mini in Room 2. Scripted evaluation cannot unlock the caretaker.')
            if G.state['mode']!='rehearsal': raise ValueError('Use tokenfactory.py evaluate for measured inference.')
            if not G.state['endpoint']: raise ValueError('Rehearse deployment before evaluation.')
            G.state['evaluation']={'score':27,'total':27,'label':'Scripted example; no model inference'};G.state['rooms'][1]=True;event('REHEARSAL: illustrative evaluation 27/27. Caretaker restored.')
        elif path=='/api/escape':
            raise ValueError('Use the generator room: connect the cooling pipes, pass the controller health check, then release the exit.')
        else: raise ValueError('Unknown action.')
    def log_message(self,fmt,*args): pass

if __name__=='__main__':
    hosting.validate_config()
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=int(os.environ.get('PORT','8765')));parser.add_argument('--host',default=os.environ.get('HOST','127.0.0.1'));args=parser.parse_args()
    serverless.enable_shared(RUNTIME)
    server=ThreadingHTTPServer((args.host,args.port),Handler)
    print(f'Haunted Datacenter: http://{args.host}:{args.port}',flush=True)
    def idle_cleanup():
        while True:
            time.sleep(60)
            try:serverless.reap(RUNTIME)
            except (OSError,ValueError):pass
    threading.Thread(target=idle_cleanup,daemon=True).start()
    try: server.serve_forever()
    except KeyboardInterrupt: print('\nShift ended.')
