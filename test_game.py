"""Game checks. Cloud calls are mocked; browser playtests exercise real Tavily."""
import json,tempfile,threading,unittest,urllib.request,urllib.error,itertools
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import content,server,tokenfactory,switchboard

CORRECT={'pip':'DNS','edgar':'SMTP','mabel':'MQTT'}

class ContentTests(unittest.TestCase):
 def test_three_damaged_labels(self):
  rows,errors=content.validate_seed(content.starter_records());self.assertEqual(len(errors),3);self.assertEqual(len(rows),6)
 def test_clean_disjoint_splits(self):
  with tempfile.TemporaryDirectory() as tmp:
   counts=content.write_datasets('\n'.join(json.dumps(r) for r in content.clean_records()),Path(tmp));self.assertEqual(counts,{'train':72,'validation':18,'evaluation':27})
   def prompts(n):return {json.loads(l)['messages'][1]['content'] for l in (Path(tmp)/n).read_text().splitlines()}
   a,b=prompts('train.jsonl'),prompts('validation.jsonl');c={r['prompt'] for r in content.eval_cases()};self.assertFalse(a&b or a&c or b&c)
 def test_duplicate_rejected(self):
  rows=content.clean_records();rows[1]=rows[0];self.assertTrue(content.validate_seed('\n'.join(json.dumps(r) for r in rows))[1])
 def test_prose_not_structured_output(self):self.assertIsNone(tokenfactory.parse_output('Sure! {"action":"ground","zone":"west"}'))

class SwitchboardTests(unittest.TestCase):
 def test_starts_with_alexs_crossed_cables(self):
  routes=switchboard.initial()['routes'];self.assertEqual(set(routes),set(CORRECT));self.assertEqual(len(set(routes.values())),3);self.assertTrue(all(routes[k]!=CORRECT[k] for k in CORRECT))
 def test_only_one_complete_wiring_is_correct(self):
  successes=[]
  for ports in itertools.permutations(switchboard.PROTOCOLS):
   routes=dict(zip(CORRECT,ports));r=switchboard.evaluate(routes)
   if r['ready']:successes.append(routes)
   self.assertEqual(len(r['results']),3)
  self.assertEqual(successes,[CORRECT])
 def test_each_route_has_a_reaction(self):
  for ghost in CORRECT:
   for protocol in switchboard.PROTOCOLS:
    r=switchboard.evaluate({ghost:protocol});result=next(x for x in r['results'] if x['id']==ghost)
    self.assertTrue(result['line']);self.assertEqual(result['correct'],CORRECT[ghost]==protocol);self.assertFalse(r['ready'])
 def test_empty_and_partial_connections_are_safe(self):
  self.assertFalse(switchboard.evaluate({})['ready']);self.assertEqual(switchboard.evaluate({})['results'][0]['status'],'UNPLUGGED')
  self.assertTrue(switchboard.evaluate({'pip':'DNS'})['results'][0]['correct'])
 def test_invalid_cables_sockets_and_duplicate_connections_rejected(self):
  for routes in [None,[],{'not-a-ghost':'DNS'},{'pip':'FTP'},{'pip':'DNS','edgar':'DNS'}]:
   with self.subTest(routes=routes),self.assertRaises(ValueError):switchboard.evaluate(routes)
 def test_bad_routes_explain_consequences_not_solution(self):
  r=switchboard.evaluate({'pip':'SMTP','edgar':'MQTT','mabel':'DNS'})
  self.assertFalse(r['ready']);self.assertTrue(all(not x['correct'] for x in r['results']))
  self.assertIn('subscriber',r['results'][1]['line'])

class FlowTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();cls.old_runtime=server.RUNTIME;cls.old_state=server.STATE;server.RUNTIME=Path(cls.tmp.name)
  cls.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler);cls.base='http://127.0.0.1:'+str(cls.http.server_port);threading.Thread(target=cls.http.serve_forever,daemon=True).start()
 @classmethod
 def tearDownClass(cls):
  cls.http.shutdown();cls.http.server_close();server.RUNTIME=cls.old_runtime;server.STATE=cls.old_state;cls.tmp.cleanup()
 def setUp(self):server.STATE=server.fresh()
 def post(self,name,body=None,token=True):
  req=urllib.request.Request(self.base+'/api/'+name,data=json.dumps(body or {}).encode(),headers={'Content-Type':'application/json',**({'X-Game-Token':server.TOKEN} if token else {})})
  try:
   with urllib.request.urlopen(req) as r:return json.load(r)
  except urllib.error.HTTPError as e:
   try:e.game_error=json.load(e).get('error','')
   finally:e.close()
   raise
 def restore(self):
  self.post('search',{'archived':True});self.post('switchboard/test',{'routes':CORRECT});self.open_terminal_door()
 def open_terminal_door(self):
  self.post('terminal',{'command':'ghostctl apply'});return self.post('terminal',{'command':'mqtt publish midnight/door OPEN'})
 def test_token_required(self):
  with self.assertRaises(urllib.error.HTTPError):self.post('start',token=False)
 def test_correct_routes_require_research(self):
  r=self.post('switchboard/test',{'routes':CORRECT});self.assertTrue(r['board']['ready']);self.assertFalse(r['state']['rooms'][0])
 def test_research_and_routing_work_in_either_order(self):
  for order in [('search','switchboard/test'),('switchboard/test','search')]:
   server.STATE=server.fresh()
   for i,step in enumerate(order):
    self.post(step,{'archived':True} if step=='search' else {'routes':CORRECT});self.assertFalse(server.STATE['rooms'][0])
   self.assertTrue(self.open_terminal_door()['state']['rooms'][0])
 def test_wrong_routes_relock_door_and_keep_reference(self):
  self.restore();r=self.post('switchboard/test',{'routes':{'pip':'SMTP','edgar':'MQTT','mabel':'DNS'}})
  self.assertFalse(r['state']['rooms'][0]);self.assertTrue(r['state']['board_citation']);self.assertEqual(r['board']['attempts'],2)
 def test_invalid_wiring_does_not_overwrite_last_attempt(self):
  self.restore()
  with self.assertRaises(urllib.error.HTTPError):self.post('switchboard/test',{'routes':{'pip':'DNS','edgar':'DNS'}})
  self.assertTrue(server.STATE['rooms'][0]);self.assertEqual(server.STATE['board']['attempts'],1)
 def test_missing_research_can_be_added_after_successful_test(self):
  self.post('switchboard/test',{'routes':CORRECT})
  result={'results':[{'title':'MQTT Version 5.0','url':'https://docs.oasis-open.org/mqtt/mqtt/v5.0/os/mqtt-v5.0-os.html','content':'MQTT is a publish/subscribe messaging protocol.'}]}
  with patch.object(server.subprocess,'run',return_value=type('Result',(),{'returncode':0,'stdout':json.dumps(result)})()):
   r=self.post('search',{'query':'topic subscribers messaging protocol'})
   self.assertFalse(r['state']['rooms'][0]);self.assertEqual(r['state']['evidence'],'tavily')
   self.assertTrue(self.open_terminal_door()['state']['rooms'][0])
 def test_dns_research_does_not_verify_subscriber_protocol(self):
  self.post('switchboard/test',{'routes':CORRECT})
  result={'results':[{'title':'DNS — MDN','url':'https://developer.mozilla.org/en-US/docs/Glossary/DNS','content':'DNS resolves names to IP addresses.'}]}
  with patch.object(server.subprocess,'run',return_value=type('Result',(),{'returncode':0,'stdout':json.dumps(result)})()):
   r=self.post('search',{'query':'DNS names IP addresses'});self.assertFalse(r['state']['rooms'][0]);self.assertNotIn('board_citation',r['state'])
 def test_blank_search_does_not_run_tavily(self):
  with patch.object(server.subprocess,'run') as run:
   with self.assertRaises(urllib.error.HTTPError):self.post('search',{'query':' '})
   run.assert_not_called()
 def test_retired_clock_and_code_routes_cannot_bypass_switchboard(self):
  self.post('search',{'archived':True});self.post('calibrate',{'kind':'absolute','wait':'120'});self.post('check',{'kind':'retry','source':content.RETRY_SOLUTION})
  self.assertFalse(server.STATE['rooms'][0])
 def test_terminal_requires_test_research_and_apply(self):
  self.assertIn('BLOCKED',self.post('terminal',{'command':'ghostctl apply'})['output'])
  self.post('switchboard/test',{'routes':CORRECT})
  self.assertIn('Tavily',self.post('terminal',{'command':'ghostctl apply'})['output'])
  self.post('search',{'archived':True})
  self.assertIn('OFFLINE',self.post('terminal',{'command':'mqtt publish midnight/door OPEN'})['output'])
  self.assertFalse(server.STATE['rooms'][0])
 def test_terminal_wrong_topic_payload_and_shell_input_are_safe(self):
  self.post('search',{'archived':True});self.post('switchboard/test',{'routes':CORRECT});self.post('terminal',{'command':'ghostctl apply'})
  with patch.object(server.subprocess,'run') as run:
   for command in ['mqtt publish wrong/topic OPEN','mqtt publish midnight/door closed','ghostctl apply; touch /tmp/haunted','$(whoami)','mqtt publish "']:
    r=self.post('terminal',{'command':command});self.assertFalse(r['state']['rooms'][0]);self.assertTrue(r['output'])
   run.assert_not_called()
  self.assertTrue(self.open_terminal_door()['state']['rooms'][0])
 def test_changed_wiring_invalidates_applied_fix(self):
  self.restore();self.post('switchboard/test',{'routes':{'pip':'SMTP','edgar':'MQTT','mabel':'DNS'}})
  self.post('switchboard/test',{'routes':CORRECT})
  self.assertFalse(server.STATE['rooms'][0]);self.assertFalse(server.STATE['switchboard_applied'])
  self.assertIn('OFFLINE',self.post('terminal',{'command':'mqtt publish midnight/door OPEN'})['output'])
 def test_help_status_and_history_are_persistent(self):
  self.assertIn('mqtt publish <topic> OPEN',self.post('terminal',{'command':'help'})['output'])
  r=self.post('terminal',{'command':'status'});self.assertIn('WAITING',r['output'])
  self.assertEqual(r['state']['terminal_history'][-1]['command'],'status')
  self.assertEqual(json.loads((server.RUNTIME/'state.json').read_text())['terminal_history'],r['state']['terminal_history'])
 def test_early_escape_blocked(self):
  with self.assertRaises(urllib.error.HTTPError):self.post('escape',{'sequence':[]})
 def test_damaged_training_blocked(self):
  self.restore();self.post('baseline')
  with self.assertRaises(urllib.error.HTTPError):self.post('train',{'source':content.starter_records()})
 def test_full_rehearsal(self):
  self.post('start');self.restore();self.post('baseline');self.post('train',{'source':'\n'.join(json.dumps(r) for r in content.clean_records())})
  with self.assertRaises(urllib.error.HTTPError):self.post('deploy')
  self.post('check',{'kind':'guard','source':content.RUNBOOK_SOLUTION});server.STATE['training']['started']-=20;self.post('deploy')
  with self.assertRaises(urllib.error.HTTPError):self.post('evaluate')
  self.assertFalse(server.STATE['rooms'][1])
  # Room 3 sequence checks use a completed caretaker fixture; real NOC gates
  # and fresh vision/text assessment are covered in test_caretaker.py.
  server.STATE['rooms'][1]=True
  with self.assertRaises(urllib.error.HTTPError) as caught:self.post('escape',{'sequence':['unlock:crypt','drain:east','ground:west']})
  for spoiler in ('ground','west','drain','east','unlock','crypt'):self.assertNotIn(spoiler,caught.exception.game_error)
  r=self.post('escape',{'sequence':['ground:west','drain:east','unlock:crypt']});self.assertTrue(r['state']['escaped']);self.assertTrue(all(r['state']['rooms']))
 def test_live_rejects_fixtures(self):
  self.post('host',{'action':'live'})
  with self.assertRaises(urllib.error.HTTPError):self.post('search',{'archived':True})
  with self.assertRaises(urllib.error.HTTPError):self.post('baseline')
 def test_mode_change_clears_progress(self):
  self.restore();self.post('host',{'action':'live'});self.assertFalse(any(server.STATE['rooms']));self.assertIsNone(server.STATE['evidence'])
 def test_stale_report_blocked(self):
  self.post('host',{'action':'live'});server.STATE['rooms'][0]=True;(server.RUNTIME/'live-report.json').write_text('{"passed":true,"checked_at":1}');self.assertFalse(server.view()['rooms'][1])

class LiveTests(unittest.TestCase):
 def test_endpoint_model_mismatch_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'plan.json';p.write_text(json.dumps({'name':'demo','model_name':'wrong','flavor_name':'base','gpu_type':'gpu-h100-sxm','gpu_count':1,'region':'eu-north1','scaling':{'min_replicas':1,'max_replicas':1},'custom_weights_id':'w-1'}))
   with patch.object(tokenfactory,'api',return_value={'status':'succeeded','model':'base'}) as call:
    with self.assertRaisesRegex(ValueError,'base model'):tokenfactory.run_deploy(type('Args',(),{'job':'job-1','plan':str(p)})())
    self.assertEqual(call.call_count,1)
 def test_api_host_restricted(self):
  with self.assertRaisesRegex(ValueError,'official'):tokenfactory.api('/v1/models',base='https://example.com')
 def test_failed_evaluation_clears_stale_pass(self):
  args=type('Args',(),{'job':'job-1','endpoint':'ep-1','base_model':'base','inference_base':None,'baseline_base':tokenfactory.CONTROL+'/v1'})()
  ep={'model_name':'base','custom_weights_id':'w-1','enabled':True,'deployment':{'ready_replicas':1},'routing_key':'dedicated/night-operator','region':'eu-north1'}
  with tempfile.TemporaryDirectory() as tmp,patch.object(tokenfactory,'RT',Path(tmp)),patch.object(tokenfactory,'api',return_value={'status':'succeeded','model':'base'}),patch.object(tokenfactory,'get_endpoint',return_value=ep),patch.object(tokenfactory,'evaluate_cases',side_effect=ValueError('failed')):
   (Path(tmp)/'deployment-ep-1.json').write_text('{"job_id":"job-1","custom_weights_id":"w-1"}');(Path(tmp)/'live-report.json').write_text('{"passed":true}')
   with self.assertRaises(ValueError):tokenfactory.run_evaluate(args)
   self.assertFalse(json.loads((Path(tmp)/'live-report.json').read_text())['passed'])
if __name__=='__main__':unittest.main()
