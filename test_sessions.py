"""Independent public playthroughs, private UUID resume, and shared resource safety."""
import concurrent.futures,copy,json,os,tempfile,threading,time,unittest,urllib.error,urllib.request,uuid
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import server,sessions,hosting,caretaker,checkpoint_flow,serverless
from test_serverless import resource,PROJECT

class PlayerHTTPTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=(server.RUNTIME,server.STATE)
  server.RUNTIME=Path(self.tmp.name);server.STATE=server.fresh();hosting._new_shifts.clear()
  self.env=patch.dict(os.environ,{'PUBLIC_DEPLOYMENT':'true','HOST_ACCESS_CODE':'test-host-access-code','SESSION_SECRET':'test-session-secret-with-at-least-32-characters'});self.env.start()
  self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler);self.base=f'http://127.0.0.1:{self.http.server_port}'
  threading.Thread(target=self.http.serve_forever,daemon=True).start()
 def tearDown(self):
  self.http.shutdown();self.http.server_close();self.env.stop();server.RUNTIME,server.STATE=self.old;self.tmp.cleanup()
 def request(self,path,body=None,game=None,token=None):
  headers={'Content-Type':'application/json'}
  if game:headers.update({'X-Run-ID':game['run_id'],'X-Game-Token':token or game['token']})
  req=urllib.request.Request(self.base+'/api/'+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
  with urllib.request.urlopen(req,timeout=5) as r:return json.load(r)
 def create(self,name):return self.request('sessions',{'name':name})['state']
 def test_two_players_start_without_a_host_code_and_have_private_progress(self):
  a=self.create('Alice');b=self.create('Bob');self.assertNotEqual(a['run_id'],b['run_id']);self.assertFalse(a['is_host'])
  self.request('hint',{'room':'2'},a)
  self.assertEqual(self.request('state',game=a)['hints']['2'],1);self.assertEqual(self.request('state',game=b)['hints']['2'],0)
  self.assertEqual(server.STATE['hints']['2'],0)
 def test_uuid_resumes_in_a_new_browser_and_survives_cache_restart(self):
  a=self.create('Alice');self.request('subscription/test',{'filter':'midnight/+/announcement'},a)
  with sessions._cache_lock:sessions._cache.clear()
  resumed=self.request('state?run='+a['run_id']);self.assertEqual(resumed['player_name'],'Alice')
  self.assertEqual(resumed['token'],a['token']);self.assertTrue(resumed['subscription']['passed'])
  folder=server.RUNTIME/'runs'/a['run_id'];self.assertEqual((folder/'state.json').stat().st_mode & 0o777,0o600)
 def test_cannot_mutate_another_uuid_with_the_wrong_token(self):
  a=self.create('Alice');b=self.create('Bob')
  with self.assertRaises(urllib.error.HTTPError) as error:self.request('hint',{'room':'2'},b,token=a['token'])
  self.assertEqual(error.exception.code,403);self.assertEqual(self.request('state',game=b)['hints']['2'],0)
 def test_unknown_uuid_and_path_traversal_do_not_create_saves(self):
  for value in ('../../state',str(uuid.uuid4())):
   with self.assertRaises(urllib.error.HTTPError):self.request('state?run='+urllib.parse.quote(value))
  self.assertFalse((server.RUNTIME/'runs').exists())
 def test_reset_keeps_both_old_saves_and_creates_a_new_uuid(self):
  a=self.create('Alice');b=self.create('Bob');self.request('hint',{'room':'1'},a)
  with patch.object(serverless,'release'):
   new=self.request('host',{'action':'reset'},a)['state']
  self.assertNotIn(new['run_id'],(a['run_id'],b['run_id']))
  self.assertEqual(self.request('state',game=a)['hints']['1'],1);self.assertEqual(self.request('state',game=b)['player_name'],'Bob')
 def test_player_cannot_use_host_experiments(self):
  a=self.create('Alice')
  for path,body in [('host',{'action':'caretaker-backup'}),('host',{'action':'live'}),('solution',{'kind':'retry'}),('noc/playtest',{})]:
   with self.assertRaises(urllib.error.HTTPError):self.request(path,body,a)
  self.assertFalse(self.request('state',game=a)['is_host'])
 def test_parallel_requests_do_not_cross_game_state(self):
  a=self.create('Alice');b=self.create('Bob')
  with concurrent.futures.ThreadPoolExecutor() as pool:
   list(pool.map(lambda pair:self.request('subscription/test',{'filter':pair[1]},pair[0]),[(a,'midnight/+/announcement'),(b,'#')]))
  self.assertTrue(self.request('state',game=a)['subscription']['passed']);self.assertFalse(self.request('state',game=b)['subscription']['passed'])
 def test_background_jobs_save_to_their_originating_uuid(self):
  a=self.create('Alice');b=self.create('Bob');entered={'Alice':threading.Event(),'Bob':threading.Event()};release=threading.Event()
  def fake(action,n,body,source,runtime,progress):
   name=body['owner'];entered[name].set();release.wait(3);n['connection']={'owner':name};progress('Finishing '+name);return name
  with patch.object(caretaker,'run',side_effect=fake):
   self.request('noc/connect',{'owner':'Alice'},a);self.request('noc/connect',{'owner':'Bob'},b)
   self.assertTrue(entered['Alice'].wait(1));self.assertTrue(entered['Bob'].wait(1));release.set()
   for _ in range(60):
    states=[self.request('state',game=g) for g in (a,b)]
    if all((s['noc'].get('operation') or {}).get('status')=='succeeded' for s in states):break
    time.sleep(.01)
  self.assertEqual(states[0]['noc']['connection']['owner'],'Alice');self.assertEqual(states[1]['noc']['connection']['owner'],'Bob')
  for g,name in [(a,'Alice'),(b,'Bob')]:self.assertEqual(json.loads((server.RUNTIME/'runs'/g['run_id']/'state.json').read_text())['noc']['connection']['owner'],name)
 def test_leaderboard_does_not_publish_private_resume_uuids(self):
  with patch.object(hosting,'leaderboard',return_value=[{'run_id':str(uuid.uuid4()),'rank':1,'name':'Alice','elapsed_seconds':42}]):
   rows=self.request('leaderboard')['entries'];self.assertNotIn('run_id',rows[0]);self.assertEqual(rows[0]['name'],'Alice')
 def test_original_host_save_remains_resumable_without_moving_artifacts(self):
  id=server.STATE['run_id'];server.STATE['hints']['1']=2
  s=self.request('state?run='+id);self.assertEqual(s['hints']['1'],2);self.assertFalse(s['is_host'])
  self.create('Alice');self.assertEqual(self.request('state?run='+id)['hints']['1'],2)
 def test_reset_while_job_runs_keeps_result_in_the_old_uuid(self):
  a=self.create('Alice');entered=threading.Event();finish=threading.Event()
  def fake(action,n,body,source,runtime,progress):
   entered.set();finish.wait(3);n['connection']={'owner':'Alice'};return 'done'
  with patch.object(caretaker,'run',side_effect=fake),patch.object(serverless,'release'):
   self.request('noc/connect',{},a);self.assertTrue(entered.wait(1))
   new=self.request('host',{'action':'reset'},a)['state'];finish.set()
   for _ in range(40):
    old=self.request('state',game=a)
    if old['noc']['connection']:break
    time.sleep(.01)
  self.assertEqual(old['noc']['connection']['owner'],'Alice');self.assertIsNone(self.request('state',game=new)['noc']['connection'])


class SharedRunnerTests(unittest.TestCase):
 def test_model_selection_and_inference_are_serialized_per_players_checkpoint(self):
  active={'artifact_hash':'foreign','job_id':'foreign'};seen=[]
  def call(path,*args):return active.copy()
  def load(runtime,receipt,callback):
   id=Path(runtime).name;active.update(artifact_hash=id,job_id=id);return active.copy()
  def infer(action,n,*args):
   time.sleep(.02);seen.append((n['job']['id'],active['job_id']));return 'done'
  a={'route':'finetuned','runner':{'active':True,'artifact_hash':'alice'},'job':{'id':'alice'}}
  b={'route':'finetuned','runner':{'active':True,'artifact_hash':'bob'},'job':{'id':'bob'}}
  with patch.object(caretaker,'runner_call',side_effect=call),patch.object(checkpoint_flow,'reload_runner',side_effect=load),patch.object(caretaker,'_run',side_effect=infer),concurrent.futures.ThreadPoolExecutor() as pool:
   jobs=[pool.submit(caretaker.run,'test',n,{},'',Path('/runtime')/n['job']['id'],lambda _:None) for n in (a,b)]
   [j.result() for j in jobs]
  self.assertCountEqual(seen,[('alice','alice'),('bob','bob')])
 def test_identical_weights_from_different_jobs_still_restore_the_players_own_receipt(self):
  n={'route':'finetuned','runner':{'active':True,'artifact_hash':'same-weights'},'job':{'id':'alice'}}
  health={'artifact_hash':'same-weights','job_id':'bob'}
  with patch.object(caretaker,'runner_call',return_value=health),patch.object(checkpoint_flow,'reload_runner',return_value={'artifact_hash':'same-weights','job_id':'alice'}) as load,patch.object(caretaker,'_run',return_value='done'):
   caretaker.run('test',n,{},'',Path('/runtime/alice'),lambda _:None)
  load.assert_called_once()
 def test_new_players_connection_does_not_copy_another_players_checkpoint_receipt(self):
  health={'ready':True,'model':'small','device':'cpu','artifact_hash':'bobs-weights','job_id':'bobs-job','checkpoint_id':'bobs-checkpoint','has_adapter':True}
  n=caretaker.initial()
  with patch.object(caretaker.tf,'api',return_value={'data':[]}),patch.object(caretaker,'runner_call',return_value=health):caretaker.connect(n)
  self.assertFalse(n['runner']['active']);self.assertNotIn('job_id',n['runner']);self.assertNotIn('bobs-weights',json.dumps(n['runner']))
 def test_player_checkpoint_uses_shared_runner_control_without_copying_its_secret(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);folder=root/'caretaker';folder.mkdir();(folder/'runner-control.json').write_text(json.dumps({'token':'private-control','model':'small'}))
   player=root/'runs'/str(uuid.uuid4());player.mkdir(parents=True)
   self.assertEqual(checkpoint_flow.runner_config(player)['model'],'small');self.assertFalse((player/'caretaker').exists())

class SharedControllerTests(unittest.TestCase):
 def test_one_player_finishing_cannot_stop_another_players_controller(self):
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'NEBIUS_PROJECT_ID':PROJECT,'NEBIUS_SUBNET_ID':'subnet'}):
   root=Path(d);row=resource();calls=[]
   def cli(args):
    calls.append(args)
    return {'items':[row]} if args[2]=='list' else row if args[2]=='get' else {}
   with patch.object(serverless,'cli',side_effect=cli):
    serverless.deploy({}, {},root,'alice',shared=True);serverless.deploy({}, {},root,'bob',shared=True)
    serverless.release(root,'alice').join(2);self.assertFalse(any(x[2]=='stop' for x in calls))
    serverless.release(root,'bob').join(2);self.assertEqual(sum(x[2]=='stop' for x in calls),1)
 def test_shared_configuration_cannot_replace_other_players_cpu(self):
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'NEBIUS_PROJECT_ID':PROJECT,'NEBIUS_SUBNET_ID':'subnet'}):
   root=Path(d);row=resource();calls=[]
   def cli(args):calls.append(args);return {'items':[row]} if args[2]=='list' else row
   with patch.object(serverless,'cli',side_effect=cli):
    p={};serverless.deploy(p,{},root,'alice',shared=True)
    with self.assertRaisesRegex(ValueError,'share this CPU'):serverless.replace(p,{'target':70},root,'bob',shared=True)
   self.assertFalse(any(x[2] in ('create','stop') for x in calls))
 def test_single_player_receipt_upgrade_preserves_the_endpoint_and_allocates_nothing(self):
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'NEBIUS_PROJECT_ID':PROJECT}):
   root=Path(d);serverless._write(serverless._pool_path(root),{'id':'existing','project_id':PROJECT,'lease':'old-shift','state':'RUNNING'})
   with patch.object(serverless,'cli') as cli:serverless.enable_shared(root)
   pool=serverless._read(serverless._pool_path(root));self.assertEqual(pool['id'],'existing');self.assertIn('old-shift',pool['leases']);cli.assert_not_called()
 def test_old_reset_cannot_stop_the_same_uuid_after_an_explicit_new_claim(self):
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'NEBIUS_PROJECT_ID':PROJECT,'NEBIUS_SUBNET_ID':'subnet'}):
   root=Path(d);row=resource();calls=[]
   def cli(args):calls.append(args);return {'items':[row]} if args[2]=='list' else row if args[2]=='get' else {}
   with patch.object(serverless,'cli',side_effect=cli):
    serverless.deploy({}, {},root,'alice',shared=True)
    with serverless.lifecycle_lock(root):
     cleanup=serverless.release(root,'alice')
     pool=serverless._read(serverless._pool_path(root));pool['claims']['alice']=time.time()+1;serverless._write(serverless._pool_path(root),pool)
    cleanup.join(2)
   self.assertFalse(any(x[2]=='stop' for x in calls))
 def test_abandoned_leases_expire_and_stop_the_controller(self):
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'NEBIUS_PROJECT_ID':PROJECT,'NEBIUS_SUBNET_ID':'subnet'}):
   root=Path(d);row=resource();calls=[]
   def cli(args):calls.append(args);return {'items':[row]} if args[2]=='list' else row if args[2]=='get' else {}
   with patch.object(serverless,'cli',side_effect=cli):
    serverless.deploy({}, {},root,'alice',shared=True)
    pool=serverless._read(serverless._pool_path(root));pool['leases']['alice']=time.time()-serverless.LEASE_TTL-10;serverless._write(serverless._pool_path(root),pool)
    serverless.reap(root).join(2)
   self.assertEqual(sum(x[2]=='stop' for x in calls),1)
 def test_delayed_idle_cleanup_does_not_stop_a_freshly_active_lease(self):
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'NEBIUS_PROJECT_ID':PROJECT,'NEBIUS_SUBNET_ID':'subnet'}):
   root=Path(d);row=resource();calls=[]
   def cli(args):calls.append(args);return {'items':[row]} if args[2]=='list' else row if args[2]=='get' else {}
   with patch.object(serverless,'cli',side_effect=cli):
    serverless.deploy({}, {},root,'alice',shared=True)
    serverless.release(root,'alice',idle=True).join(2)
   self.assertFalse(any(x[2]=='stop' for x in calls))

if __name__=='__main__':unittest.main()
