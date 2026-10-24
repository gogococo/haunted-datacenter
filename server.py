#!/usr/bin/env python3
"""Local, single-team demo server. Standard library only. Bind to loopback."""
import argparse, json, os, secrets, subprocess, sys, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
import content
import caretaker, copy
import switchboard,clue_post,plant,lessons,serverless

ROOT=Path(__file__).resolve().parent
RUNTIME=ROOT/'.runtime'; RUNTIME.mkdir(exist_ok=True)
TOKEN=secrets.token_urlsafe(24)
LOCK=threading.RLock()

def fresh():
    return {'plant':plant.initial(),'noc':caretaker.initial(),'puzzle_version':switchboard.VERSION,'board':switchboard.initial(),'created_at':time.time(),'mode':'rehearsal','started':None,'paused':False,'pause_at':None,'pause_total':0,'evidence':None,'calibration':False,'rooms':[False,False,False],'guard':False,'training':None,'endpoint':False,'baseline':None,'evaluation':None,'escaped':False,'hints':{'1':0,'2':0,'3':0},'sources':{'retry':content.RETRY_STARTER,'guard':content.RUNBOOK_STARTER,'dataset':content.starter_records()},'log':[{'text':'Incident SEV-0 opened. Previous on-call engineer: still assigned.','at':time.time()}]}
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

def maintenance_access():
    n=STATE['noc'];j=n.get('submission') or {}
    return bool(STATE['rooms'][0] and j.get('id') and j.get('pack_hash')==lessons.packet_hash(n,STATE['sources']['dataset']))

def save():
    temp=RUNTIME/'state.tmp'; temp.write_text(json.dumps(STATE)); temp.replace(RUNTIME/'state.json')

def event(message):
    STATE['log'].append({'text':message,'at':time.time()}); STATE['log']=STATE['log'][-40:]

def refresh_archive():
    """Unlock from the current evidence, diagnosis and code in any completion order."""
    if STATE.get('puzzle_version')==switchboard.VERSION: return
    report=STATE.get('retry_report')
    if not report: return
    report['needs_evidence']=bool(report.get('passed') and not STATE['evidence'])
    report['needs_calibration']=bool(report.get('passed') and not STATE.get('calibration'))
    ready=bool(report.get('passed') and STATE['evidence'] and STATE.get('calibration'))
    if ready and not STATE['rooms'][0]: event('Archive door restored. The retry storm subsides. One ghost unsubscribes.')
    STATE['rooms'][0]=ready

def refresh_switchboard():
    ready=bool(STATE.get('board',{}).get('ready') and STATE.get('board_citation') and STATE.get('topic_evidence') and STATE.get('switchboard_applied') and STATE.get('door_signal') and STATE.get('subscription',{}).get('passed'))
    if ready and not STATE['rooms'][0]:event('All three ghosts routed correctly. Research verified. Archive door unlocked.')
    STATE['rooms'][0]=ready

def view():
    if not STATE.get('board',{}).get('routes') and not STATE.get('board',{}).get('attempts'):
        STATE['board']=switchboard.initial();save()
    if STATE['training'] and STATE['training']['status']=='running' and time.time()-STATE['training']['started']>=16:
        STATE['training']['status']='succeeded'; event('REHEARSAL: scripted training walkthrough complete. No weights trained.'); save()
    return {**STATE,'maintenance_route_open':maintenance_access(),'noc':{**STATE['noc'],'maintenance_notes':lessons.NOTES},'maintenance_notes':lessons.NOTES,'serverless_configured':bool(serverless.config(RUNTIME)['project_id'] and serverless.config(RUNTIME)['subnet_id']),'plant_definition':plant.definition(),'training_seed_before':content.starter_records(),'mabel_post_url':clue_post.public_url(),'mabel_post_html':clue_post.article(),'memory_status':content.memory_status(STATE['sources']['dataset']),'live_report':None,'token':TOKEN,'tavily_available':bool(__import__('shutil').which('tvly')),'nebius_configured':bool(os.environ.get('NEBIUS_API_KEY') or os.environ.get('NEBIUS_TOKEN_FACTORY_KEY'))}

def launch_noc(action,body):
    noc=STATE['noc']
    if (noc.get('operation') or {}).get('status')=='running':raise ValueError('The caretaker is already working. Wait for the current operation.')
    snapshot=copy.deepcopy(noc);source=STATE['sources']['dataset'];session=STATE['created_at']
    if action in ('test','verify','train','deploy','backup','prompt-profile','load-own'):
        snapshot['previous_report']=snapshot.get('report');snapshot['report']=None;snapshot.pop('final',None);noc['report']=None;noc.pop('final',None)
    if action in ('final','verify'):snapshot.pop('final',None)
    noc['operation']={'action':action,'status':'running','message':'Checking the caretaker…','started':time.time()};noc['revision']+=1
    if action in ('test','verify','train','deploy','backup','prompt-profile','load-own','final'):
        STATE['rooms'][1]=False;STATE['rooms'][2]=False;STATE['escaped']=False
    def progress(message):
        with LOCK:
            if STATE['created_at']==session:
                STATE['noc']['operation']['message']=message;STATE['noc']['revision']+=1;save()
    def worker():
        try:message=caretaker.run(action,snapshot,body,source,RUNTIME,progress);status='succeeded'
        except (ValueError,KeyError,TypeError,OSError) as error:
            message=str(error) if isinstance(error,ValueError) else 'Cloud operation failed ('+type(error).__name__+'). Check configuration and refresh cloud status.';status='failed'
        except Exception as error:message='Cloud operation failed ('+type(error).__name__+'). No automatic retry.';status='failed'
        with LOCK:
            if STATE['created_at']!=session:
                (RUNTIME/('noc-recovered-'+str(int(session))+'-'+action+'.json')).write_text(json.dumps({'action':action,'status':status,'noc':snapshot}))
                return
            snapshot['operation']={'action':action,'status':status,'message':message,'finished':time.time()}
            snapshot['revision']=STATE['noc']['revision']+1;STATE['noc']=snapshot
            if action in ('final','verify'):STATE['rooms'][1]=bool(status=='succeeded' and snapshot.get('final',{}).get('passed'))
            save()
    threading.Thread(target=worker,daemon=True).start()


def launch_plant(action,body):
    p=STATE['plant'];session=STATE['created_at']
    if (p.get('operation') or {}).get('status')=='running':raise ValueError('A cloud request is still running. You can place pipes while deployment submits.')
    snapshot=copy.deepcopy(p)
    if action in ('deploy','health','test','replace'):snapshot['report']=None
    if action in ('deploy','health','replace'):snapshot['health']=None
    board=plant.normalize(body.get('pipes',p['pipes']))
    if action in ('deploy','health','test','replace'):p['report']=None;STATE['rooms'][2]=False;STATE['escaped']=False
    p['operation']={'action':action,'status':'running','message':{'deploy':'Submitting the real CPU app to Nebius Serverless…','refresh':'Reading cloud endpoint status…','health':'Requesting the deployed app’s /healthz route…','test':'Sending this circuit’s sensor report to the real app…','logs':'Reading the real app’s logs…','replace':'Stopping the old app and deploying the corrected configuration…'}[action]};p['revision']+=1
    def worker():
        try:
            if action=='deploy':message=serverless.deploy(snapshot,body,RUNTIME)
            elif action=='replace':message=serverless.replace(snapshot,body,RUNTIME)
            elif action=='refresh':message=serverless.refresh(snapshot,RUNTIME)
            elif action=='health':message=serverless.health(snapshot,RUNTIME)
            elif action=='logs':message=serverless.logs(snapshot,RUNTIME)
            else:message=serverless.assess(snapshot,RUNTIME,board)
            status='succeeded'
        except (ValueError,OSError,KeyError,TypeError) as error:message=str(error) if isinstance(error,ValueError) else 'Cloud request failed. Check the endpoint in the console.';status='failed'
        except Exception:message='Cloud operation failed. Check the endpoint status and try the specific check again.';status='failed'
        with LOCK:
            if STATE['created_at']!=session:return
            current=STATE['plant']
            for key in ('endpoint','health','deployment_unknown','cloud_logs','previous_endpoints'):
                if key in snapshot:current[key]=snapshot[key]
            if action=='test':
                for key in ('settings','pipes','pipe_report','report'):current[key]=snapshot.get(key)
            current['operation']={'action':action,'status':status,'message':message,'finished':time.time()};current['revision']+=1;save()
    threading.Thread(target=worker,daemon=True).start()

def launch_plant_advice(values):
    current=STATE['plant'];session=STATE['created_at']
    if (current.get('operation') or {}).get('status')=='running':raise ValueError('The diagnostic model is already reading the logs.')
    settings=plant.settings(values);current['operation']={'status':'running','message':'Token Factory is reading the controller logs…'};current['revision']+=1
    def worker():
        try:reply=plant.advise(settings);status='succeeded';message='Real Token Factory diagnostic reply received.'
        except Exception as error:reply=None;status='failed';message=str(error) if isinstance(error,ValueError) else 'Diagnostic request failed. Check the local server and try again.'
        with LOCK:
            if STATE['created_at']!=session:return
            STATE['plant']['operation']={'status':status,'message':message};STATE['plant']['advice']=reply;STATE['plant']['revision']+=1;save()
    threading.Thread(target=worker,daemon=True).start()

def run_code(kind,source):
    if len(source)>20000: raise ValueError('Puzzle source is too long.')
    path=RUNTIME/f'{kind}.py'; path.write_text(source)
    env={k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL','TMPDIR','SYSTEMROOT')}
    result=subprocess.run([sys.executable,'-I',str(ROOT/'check_puzzle.py'),str(path),kind],capture_output=True,text=True,timeout=5,cwd=RUNTIME,env=env)
    try: return json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError,IndexError): return {'passed':False,'error':'Puzzle did not return a test report. Check syntax and return values.'}

class Handler(BaseHTTPRequestHandler):
    def json(self,data,status=200):
        body=json.dumps(data).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/api/state':
            with LOCK:
                n=STATE['noc'];job=n.get('submission') or {}
                if job.get('id') and job.get('status') not in ('succeeded','failed','cancelled') and time.time()-n.get('polled_at',0)>=20 and (n.get('operation') or {}).get('status')!='running':
                    n['polled_at']=time.time();launch_noc('refresh',{})
                self.json(view())
            return
        files={'/controller.py':('cloud_controller.py','text/plain'),'/training-replay.json':('web/training-replay.json','application/json'),'/plant.js':('web/plant.js','text/javascript'),'/mabel-post.html':('web/mabel-post.html','text/html'),'/noc.js':('web/noc.js','text/javascript'),**{'/cameras/'+c['id']+'.png':('web/cameras/'+c['id']+'.png','image/png') for c in caretaker.CAMERAS},'/':('web/index.html','text/html'),'/room.js':('web/room.js','text/javascript'),'/app.js':('web/app.js','text/javascript'),'/style.css':('web/style.css','text/css')}
        if path not in files: self.send_error(404); return
        file,mime=files[path]; data=(ROOT/file).read_bytes()
        self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
    def do_POST(self):
        if self.headers.get('X-Game-Token')!=TOKEN: self.json({'error':'Refresh the page to reconnect.'},403);return
        origin=self.headers.get('Origin')
        if origin and urlparse(origin).netloc!=self.headers.get('Host'): self.json({'error':'Cross-origin request refused.'},403);return
        try:
            length=int(self.headers.get('Content-Length',0))
            if urlparse(self.path).path=='/api/noc/import':
                if not 0<length<=64*1024*1024:raise ValueError('Choose a LoRA adapter under 64 MiB.')
                uploaded=self.rfile.read(length)
                if len(uploaded)!=length:raise ValueError('Upload was incomplete.')
                with LOCK:
                    launch_noc('load-own',{'uploaded':uploaded});save();self.json({'state':view()})
                return
            if length>50000: raise ValueError('Request too large.')
            body=json.loads(self.rfile.read(length) or b'{}')
            with LOCK:
                result=self.action(urlparse(self.path).path,body);save();self.json({'state':view(),**(result or {})})
        except subprocess.TimeoutExpired: self.json({'error':'Operation timed out. Your progress is saved.'},408)
        except (ValueError,KeyError,TypeError,FileNotFoundError) as e:self.json({'error':str(e)},400)
        except Exception as e:self.json({'error':f'Operation failed ({type(e).__name__}). Check the local terminal.'},500)
    def action(self,path,b):
        global STATE
        if path=='/api/start':
            if not STATE['started']: STATE['started']=time.time();STATE['paused']=False;STATE['pause_at']=None;STATE['pause_total']=0;event('You accepted the pager. Forty-five minutes until midnight.')
        elif path=='/api/host':
            act=b['action']
            if act in ('caretaker-backup','caretaker-prompt'):
                launch_noc('backup' if act=='caretaker-backup' else 'prompt-profile',{'host_override':True})
            elif act=='reset': STATE=fresh()
            elif act=='pause':
                if not STATE['paused']: STATE['pause_at']=time.time();STATE['paused']=True
                else: STATE['pause_total']+=time.time()-STATE['pause_at'];STATE['paused']=False;STATE['pause_at']=None
            elif act in ('live','rehearsal'):
                if STATE['mode']!=act:
                    # Keep code edits; clear all gates to prevent simulated evidence carrying into live mode.
                    sources=STATE['sources'];STATE=fresh();STATE['sources']=sources;STATE['mode']=act
                    event(f'Mode changed to {act}. Gates and timer reset; code edits retained.')
        elif path=='/api/solution':
            kind=b['kind']
            if kind not in ('retry','dataset','guard'): raise ValueError('Unknown solution.')
            return {'source': {'retry':content.RETRY_SOLUTION,'guard':content.RUNBOOK_SOLUTION,'dataset':'\n'.join(json.dumps(r) for r in content.clean_records())}[kind], 'settings': {'fallback':60,'floor':0,'direction':'until'} if kind=='retry' else None, 'routes': {k:v['protocol'] for k,v in switchboard.GHOSTS.items()} if kind=='retry' else None}
        elif path=='/api/hint':
            room=str(b['room']); n=STATE['hints'][room];STATE['hints'][room]=min(n+1,3)
            return {'hint':content.HINTS[room][min(n,2)]}
        elif path=='/api/mabel-post':
            source=clue_post.saved_post() if b.get('bookmark') and not clue_post.public_url() else clue_post.retrieve(bool(b.get('archived')),STATE['mode'])
            STATE['topic_evidence']=source;refresh_switchboard()
            event('Mabel’s topic recovered from '+('her saved bookmark.' if source['kind']=='saved-post' else 'a marked rehearsal draft.' if source['kind']=='rehearsal' else 'a live Tavily extraction.'))
            return {'source':source}
        elif path=='/api/search':
            if b.get('archived'):
                if STATE['mode']!='rehearsal': raise ValueError('Live mode requires a real Tavily search.')
                sources=switchboard.ARCHIVE;STATE['evidence']='fixture';event('REHEARSAL: loaded illustrative protocol references.')
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
                STATE['evidence']='tavily';event('Tavily evidence retrieved from authoritative documentation.')
            STATE['search_results']=sources
            # A search is discovery. Players must explicitly inspect a source.

            refresh_switchboard();return {'sources':sources}
        elif path=='/api/research/extract':
            url=b.get('url');source=next((x for x in STATE.get('search_results',[]) if x['url']==url),None)
            if not source:raise ValueError('Choose a source returned by your Tavily search.')
            if 'MQTT' not in source.get('protocols',[]):raise ValueError('This reference covers another protocol. Find MQTT topic-filter documentation for the speaker.')
            proc=subprocess.run(['tvly','extract',url,'--query','MQTT topic filter + single level wildcard # multi level wildcard subscription topic levels','--chunks-per-source','3','--extract-depth','advanced','--json'],capture_output=True,text=True,timeout=45)
            if proc.returncode:raise ValueError('Tavily Extract could not read that source. Try another documentation result.')
            data=json.loads(proc.stdout);rows=data.get('results',[])
            if not rows:raise ValueError('No readable document returned. Choose another source.')
            text=rows[0].get('raw_content') or rows[0].get('content','')
            if not text.strip():raise ValueError('The source had no extractable text. Try another reference.')
            STATE['board_citation']={**source,'content':text[:6000],'kind':'tavily-extract'}
            refresh_switchboard();return {'source':STATE['board_citation']}
        elif path=='/api/subscription/test':
            STATE['subscription']=switchboard.test_subscription(b.get('filter',''))
            STATE['switchboard_applied']=False;STATE['door_signal']=False
            refresh_switchboard();return {'report':STATE['subscription']}
        elif path=='/api/switchboard/test':
            previous=STATE.get('board',switchboard.initial())
            board=switchboard.evaluate(b.get('routes',{}));board['attempts']=previous.get('attempts',0)+1
            if board['routes']!=previous['routes']:
                STATE['switchboard_applied']=False;STATE['door_signal']=False
            STATE['board']=board;refresh_switchboard()
            event('Switchboard test sent. '+str(sum(r['correct'] for r in board['results']))+'/3 ghost services working.')
            return {'board':board}
        elif path=='/api/terminal':
            command=b.get('command','')
            output=switchboard.terminal_command(STATE,command)
            STATE['terminal_history']=(STATE.get('terminal_history',[])+[{'command':command.strip(),'output':output}])[-20:]
            refresh_switchboard()
            return {'output':output}
        elif path.startswith('/api/plant/'):
            action=path.rsplit('/',1)[1];p=STATE['plant']
            if action in ('deploy','refresh','health','test','logs','replace'):
                if not maintenance_access() and not STATE['noc'].get('playtest'):raise ValueError('Submit the caretaker training job before entering the generator room.')
                launch_plant(action,b)
            elif action=='pipes':
                if (p.get('operation') or {}).get('action')=='test' and p['operation']['status']=='running':raise ValueError('Wait for the cooling test before editing pipes.')
                board=plant.normalize(b.get('pipes',{}));p['pipes']=board;p['pipe_report']=plant.check_pipes(board);p['report']=None
                STATE['rooms'][2]=False;STATE['escaped']=False;p['revision']+=1
            elif action=='escape':
                board=plant.normalize(b.get('pipes',{}));report=p.get('report') or {}
                if not STATE['rooms'][0] or not STATE['rooms'][1]:raise ValueError('Restore communications and certify the caretaker before releasing the exit.')
                if not report.get('passed') or not report.get('request_nonce') or report.get('endpoint_id')!=(p.get('endpoint') or {}).get('id') or report.get('board_hash')!=plant.fingerprint(board) or not plant.check_pipes(board)['passed']:raise ValueError('Complete the circuit, deploy the controller, and pass its live cooling test with this layout.')
                STATE['rooms'][2]=True;STATE['escaped']=True;STATE['finished']=time.time();event('Closed cooling circuit stable. Cloud controller healthy. Everyone leaves together.')
            else:raise ValueError('Unknown generator-room action.')
        elif path.startswith('/api/noc/'):
            action=path.rsplit('/',1)[1]
            if action in ('backup','prompt-profile'):raise ValueError('Fallbacks and prompt experiments are available in host controls only.')
            if action=='playtest':
                STATE['noc']['playtest']=True;STATE['noc']['revision']+=1
                STATE['started']=time.time();STATE['paused']=False;STATE['pause_at']=None;STATE['pause_total']=0;STATE.pop('finished',None)
            elif action in ('evidence','rehearse','try-probe'):
                if (STATE['noc'].get('operation') or {}).get('status')=='running':raise ValueError('Wait for the current model request.')
                message=caretaker.run(action,STATE['noc'],b,STATE['sources']['dataset'],RUNTIME,lambda _:None)
                STATE['noc']['revision']+=1
                return {'message':message}
            elif action=='preview':
                if not lessons.complete(STATE['noc']):raise ValueError('Record the three camera lessons first.')
                rows,errors=content.validate_seed(STATE['sources']['dataset'])
                if errors:raise ValueError(errors[0])
                return {'records':content.expand(rows,content.TRAIN_TEMPLATES)+[content.record(x['input'],x['answer']) for x in STATE['noc']['lessons'].values()]}
            elif action=='record':
                if (STATE['noc'].get('operation') or {}).get('status')=='running':raise ValueError('Wait for the caretaker’s current request.')
                STATE['sources']['dataset']=lessons.record(STATE['noc'],b.get('camera'),STATE['sources']['dataset'])
                _,errors=content.validate_seed(STATE['sources']['dataset']);STATE['noc']['dataset_report']={'passed':not errors,'errors':errors};STATE['noc']['revision']+=1
                STATE['rooms'][1]=False;STATE['rooms'][2]=False;STATE['escaped']=False
            elif action=='memory':
                if (STATE['noc'].get('operation') or {}).get('status')=='running':raise ValueError('Wait for the caretaker to finish its current task.')
                source=content.repair_memory(STATE['sources']['dataset'],b.get('memory'),b.get('choice'))
                return self.action('/api/dataset',{'source':source})
            elif action=='settings':
                if (STATE['noc'].get('operation') or {}).get('status')=='running':raise ValueError('Wait for the current operation before changing settings.')
                if STATE['noc'].get('runner') and STATE['noc'].get('route')!='prompt' and b.get('base_model',STATE['noc']['runner']['model'])!=STATE['noc']['runner']['model']:raise ValueError('This local backup uses '+STATE['noc']['runner']['model']+'. Load a different checkpoint to change its base model.')
                STATE['noc']['config']=caretaker.settings(b,STATE['noc']['config']);STATE['noc']['report']=None;STATE['noc'].pop('final',None);STATE['rooms'][1]=False;STATE['rooms'][2]=False;STATE['escaped']=False;STATE['noc']['revision']+=1
            elif action=='review':
                if (STATE['noc'].get('operation') or {}).get('status')=='running':raise ValueError('Wait for the camera inspection to finish.')
                observation=STATE['noc']['observations'].get(b.get('camera'))
                if not observation:raise ValueError('Inspect this camera first.')
                equipment=str(b.get('equipment','')).strip().lower();fault=str(b.get('fault','')).strip().lower()
                request=caretaker.camera_request(equipment,fault)
                observation.update(equipment=equipment,fault=fault,request=request,reviewed=True);STATE['noc']['revision']+=1
            elif action in ('connect','inspect','vision','review-probe','probe','test','verify','train','refresh','deploy','backup','prompt-profile','load-own','final','evidence','rehearse','try-probe'):
                if not STATE['rooms'][0] and not STATE['noc'].get('playtest') and action not in ('connect','refresh'):raise ValueError('Restore Room 1 before running the caretaker. You can explore this room first.')
                launch_noc(action,b)
            else:raise ValueError('Unknown caretaker action.')
        elif path=='/api/calibrate':
            if b.get('kind')!='absolute': raise ValueError('That interpretation does not fit the server’s value. Compare the manual with your research.')
            try: wait=int(str(b.get('wait','')))
            except ValueError: raise ValueError('Enter the wait as a whole number of seconds.')
            if wait<120: raise ValueError('That would retry before the scheduled recovery. Compare the reply time with the clock’s receipt time.')
            if wait>120: raise ValueError('That would wait past the scheduled recovery. Check the interval and its units.')
            STATE['calibration']=True;event('Last reply reconstructed. Controller diagnostic console unlocked.');refresh_archive()
        elif path=='/api/repair':
            source,settings=content.configured_retry_source(b.get('settings'))
            STATE['retry_settings']=settings
            return self.action('/api/check',{'kind':'retry','source':source})
        elif path=='/api/check':
            kind=b['kind']
            if kind not in ('retry','guard'): raise ValueError('Unknown puzzle.')
            source=b['source'];STATE['sources'][kind]=source
            report=run_code(kind,source)
            STATE[f'{kind}_report']=report
            if kind=='retry': refresh_archive()
            else:
                STATE['guard']=bool(report['passed'])
                if STATE['guard']: event('Runbook guard passed. Documents no longer issue commands.')
            return {'report':report}
        elif path=='/api/dataset':
            if (STATE['noc'].get('operation') or {}).get('status')=='running': raise ValueError('Wait for the current caretaker operation before editing training records.')
            STATE['sources']['dataset']=b['source'];rows,errors=content.validate_seed(b['source'])
            STATE['noc']['report']=None;STATE['noc'].pop('final',None);STATE['rooms'][1]=False;STATE['rooms'][2]=False;STATE['escaped']=False
            STATE['noc']['dataset_report']={'passed':not errors,'errors':errors};STATE['noc']['revision']+=1
            return {'report':{'passed':not errors,'errors':errors,'valid':len(rows),'total':9}}
        elif path=='/api/baseline':
            if STATE['mode']!='rehearsal': raise ValueError('For live baseline inference, use tokenfactory.py evaluate. See host panel.')
            STATE['baseline']={'score':0,'total':27,'label':'Scripted example; no model inference'};event('REHEARSAL baseline: 0/27. This is an illustrative result, not a measured score.')
        elif path=='/api/train':
            if not STATE['rooms'][0]: raise ValueError('Restore the archive door first.')
            if STATE['mode']!='rehearsal': raise ValueError('Use tokenfactory.py train to submit a real job. See host panel.')
            if not STATE['baseline']: raise ValueError('Run the baseline before repairing the caretaker.')
            STATE['sources']['dataset']=b['source'];counts=content.write_datasets(b['source'])
            STATE['training']={'status':'running','started':time.time(),'counts':counts};STATE['endpoint']=False;STATE['evaluation']=None;STATE['rooms'][1]=False
            event('REHEARSAL: scripted training started. Investigate the exit while it runs.')
        elif path=='/api/deploy':
            if STATE['mode']!='rehearsal': raise ValueError('Deploy via tokenfactory.py or the Token Factory console.')
            view()
            if not STATE['training'] or STATE['training']['status']!='succeeded': raise ValueError('Wait for the training walkthrough to finish.')
            STATE['endpoint']=True;event('REHEARSAL: mock dedicated endpoint ready. No cloud resource created.')
        elif path=='/api/evaluate':
            raise ValueError('Use the Mac mini in Room 2. Scripted evaluation cannot unlock the caretaker.')
            if STATE['mode']!='rehearsal': raise ValueError('Use tokenfactory.py evaluate for measured inference.')
            if not STATE['endpoint']: raise ValueError('Rehearse deployment before evaluation.')
            STATE['evaluation']={'score':27,'total':27,'label':'Scripted example; no model inference'};STATE['rooms'][1]=True;event('REHEARSAL: illustrative evaluation 27/27. Caretaker restored.')
        elif path=='/api/escape':
            raise ValueError('Use the generator room: connect the cooling pipes, pass the controller health check, then release the exit.')
        else: raise ValueError('Unknown action.')
    def log_message(self,fmt,*args): pass

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765);args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Haunted Datacenter: http://127.0.0.1:{args.port}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: print('\nShift ended.')
