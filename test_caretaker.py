"""Behavior, cloud boundary, and no-shortcut checks for the NOC room."""
import copy,json,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
import caretaker as c,content,server

def response(output='{"action":"ground","zone":"west"}',finish='stop'):
 return {'output':output,'finish_reason':finish,'model':'test','request_id':'test','usage':{}}

class AssessmentTests(unittest.TestCase):
 def test_cutoff_does_not_pass_even_when_json_is_valid(self):
  r=c.checks(response(finish='length'),{'action':'ground','zone':'west'})
  self.assertTrue(r['correct']);self.assertFalse(r['complete'])
 def test_prose_and_extra_keys_fail_contract(self):
  for out in ['Sure! {"action":"ground","zone":"west"}','{"action":"ground","zone":"west","story":"boo"}']:
   self.assertFalse(c.checks(response(out),{'action':'ground','zone':'west'})['structured'])
 def test_wrong_but_consistent_is_not_a_pass(self):
  n=c.initial();n['connection']={"models":[]}
  with patch.object(c,'text_call',return_value=response()) as call:c.assess(n)
  self.assertEqual(call.call_count,9);self.assertTrue(n['report']['checks']['consistent']);self.assertFalse(n['report']['checks']['correct']);self.assertFalse(n['report']['passed'])
 def test_varied_actions_fail_consistency(self):
  n=c.initial();n['connection']={"models":[]}
  outputs=[response(),response('{"action":"drain","zone":"west"}'),response()]*3
  with patch.object(c,'text_call',side_effect=outputs):c.assess(n)
  self.assertFalse(n['report']['checks']['consistent'])
 def test_correct_sample_passes_at_any_temperature(self):
  n=c.initial();n['connection']={'models':[]};n['config']['temperature']=1.8
  outputs=[response(json.dumps(content.eval_cases()[i]['expected'])) for i in (0,12,24) for _ in range(3)]
  with patch.object(c,'text_call',side_effect=outputs):c.assess(n)
  self.assertTrue(n['report']['passed']);self.assertEqual(n['baseline'],n['report'])
 def test_settings_validate_and_use_request_parameters(self):
  for values in [{'temperature':'nan'},{'temperature':3},{'max_tokens':0},{'system':''}]:
   with self.assertRaises(ValueError):c.settings(values,c.initial()['config'])
  n=c.initial();n['config']=c.settings({'temperature':0.3,'max_tokens':64,'system':'JSON only'},n['config'])
  with patch.object(c,'completion',return_value=response()) as call:c.text_call(n,'mourn the thorn')
  self.assertEqual(call.call_args.args[2:4],(0.3,64));self.assertEqual(call.call_args.args[1][0]['content'],'JSON only')
 def test_vision_sends_pixels_and_no_expected_answer(self):
  n=c.initial();n['config']['vision_model']='vision'
  with patch.object(c,'completion',return_value=response('{"request":"mourn the thorn","observation":"Sparks"}')) as call:c.vision(n,'west')
  messages=call.call_args.args[1];self.assertIn('data:image/png;base64,',messages[1]['content'][1]['image_url']['url']);self.assertNotIn('ground',json.dumps(messages));self.assertFalse(n['observations']['west']['reviewed'])
 def test_final_cannot_pass_without_real_training_and_endpoint(self):
  n=c.initial();n['report']={'passed':True}
  with self.assertRaises(ValueError):c.final_assessment(n)
 def test_final_requires_current_settings(self):
  n=self.ready();n['config']['temperature']=0.4
  with patch.object(c,'refresh_cloud'):
   with self.assertRaisesRegex(ValueError,'current endpoint and settings'):c.final_assessment(n)
 def ready(self):
  n=c.initial();n['job']={'id':'job','status':'succeeded','model':'base'};n['endpoint']={'id':'ep','model_name':'base','custom_weights_id':'weights','routing_key':'dedicated/test','region':'eu-north1','enabled':True,'deployment':{'ready_replicas':1}}
  n['deployment_receipt']={'job_id':'job','weights_id':'weights','endpoint_id':'ep'};n['report']={'passed':True,'endpoint_id':'ep','config':copy.deepcopy(n['config'])};return n
 def test_final_uses_fresh_vision_and_text_for_all_three_incidents(self):
  n=self.ready()
  def vision(n,id):n['observations'][id]={'request':id,'observation':'actual vision output'}
  def text(n,prompt):return response(json.dumps(next(x['expected'] for x in c.CAMERAS if x['id']==prompt)))
  with patch.object(c,'refresh_cloud'),patch.object(c,'vision',side_effect=vision) as v,patch.object(c,'text_call',side_effect=text) as t:c.final_assessment(n)
  self.assertEqual(v.call_count,3);self.assertEqual(t.call_count,3);self.assertTrue(n['final']['passed'])
 def test_weight_mismatch_blocks_final(self):
  n=self.ready();n['endpoint']['custom_weights_id']='other'
  with patch.object(c,'refresh_cloud'),self.assertRaisesRegex(ValueError,'does not match'):c.final_assessment(n)
 def test_held_out_prompts_absent_from_training_and_validation(self):
  train={r['messages'][1]['content'] for r in content.expand(content.clean_records(),content.TRAIN_TEMPLATES+content.VALID_TEMPLATES)}
  self.assertFalse(train&{content.eval_cases()[i]['prompt'] for i in (0,12,24)})

class CloudWorkflowTests(unittest.TestCase):
 def test_training_uploads_disjoint_data_and_uses_real_job_response(self):
  n=c.initial();n['baseline']={'passed':False};n['connection']={'templates':[{'name':c.BASE}]}
  source='\n'.join(json.dumps(r) for r in content.clean_records())
  with tempfile.TemporaryDirectory() as tmp,patch.object(c.tf,'upload',side_effect=['train-id','valid-id']),patch.object(c.tf,'api',return_value={'id':'job-1','status':'queued','model':c.BASE}) as api:
   c.train(n,source,Path(tmp))
   payload=api.call_args.args[2];self.assertEqual(payload['training_file'],'train-id');self.assertFalse(payload['hyperparameters']['lora']);self.assertEqual(n['job']['id'],'job-1')
   train={json.loads(x)['messages'][1]['content'] for x in (Path(tmp)/'noc-training/train.jsonl').read_text().splitlines()}
   valid={json.loads(x)['messages'][1]['content'] for x in (Path(tmp)/'noc-training/validation.jsonl').read_text().splitlines()}
   self.assertFalse(train&valid)
 def test_deployment_uses_wrapped_api_response_and_template(self):
  n=c.initial();n['job']={'id':'job-1','status':'succeeded','model':'base'};n['connection']={'templates':[{'name':'base','flavors':{'base':{'available_configurations':{'gpu_configurations':{'gpu-h100-sxm':{'allowed_regions':['eu-north1'],'allowed_gpu_counts':[1]}}}}}}]}
  body={'weights':'w1','flavor':'base','gpu':'gpu-h100-sxm','region':'eu-north1','count':1}
  endpoint={'id':'ep1','name':'test','model_name':'base','custom_weights_id':'w1','routing_key':'dedicated/test','region':'eu-north1','deployment':{'ready_replicas':0}}
  with patch.object(c,'refresh_cloud'),patch.object(c.tf,'api',return_value={'endpoint':endpoint}) as api:c.deploy(n,body)
  self.assertEqual(n['endpoint']['id'],'ep1');self.assertEqual(api.call_args.args[2]['scaling'],{'min_replicas':1,'max_replicas':1})
  self.assertEqual(n['deployment_receipt']['weights_id'],'w1')
 def test_uncertain_deployment_blocks_duplicate(self):
  n=c.initial();n['job']={'status':'succeeded'};n['deployment_submission_unknown']=True
  with patch.object(c,'refresh_cloud'),self.assertRaisesRegex(ValueError,'uncertain'):c.deploy(n,{})

class AsyncTests(unittest.TestCase):
 def setUp(self):
  self.old=server.STATE;self.rt=server.RUNTIME;self.tmp=tempfile.TemporaryDirectory();server.RUNTIME=Path(self.tmp.name);server.STATE=server.fresh()
 def tearDown(self):server.STATE=self.old;server.RUNTIME=self.rt;self.tmp.cleanup()
 def test_late_result_cannot_overwrite_reset(self):
  started=threading.Event();release=threading.Event();done=threading.Event()
  def work(*args):started.set();release.wait(3);done.set();return 'finished'
  with patch.object(c,'run',side_effect=work):
   with server.LOCK:server.launch_noc('connect',{})
   self.assertTrue(started.wait(2))
   with server.LOCK:server.STATE=server.fresh();session=server.STATE['created_at']
   release.set();self.assertTrue(done.wait(2));time.sleep(.02)
   self.assertEqual(server.STATE['created_at'],session);self.assertIsNone(server.STATE['noc']['operation'])
 def test_failed_retest_cannot_reuse_a_passing_report(self):
  server.STATE['noc']['report']={'passed':True}
  with patch.object(c,'run',side_effect=ValueError('inference failed')):
   with server.LOCK:server.launch_noc('test',{})
   for _ in range(100):
    time.sleep(.01)
    with server.LOCK:
     if server.STATE['noc']['operation']['status']!='running':break
   self.assertEqual(server.STATE['noc']['operation']['status'],'failed');self.assertIsNone(server.STATE['noc']['report']);self.assertFalse(server.STATE['rooms'][1])
 def test_duplicate_operation_rejected(self):
  server.STATE['noc']['operation']={'status':'running'}
  with self.assertRaises(ValueError):server.launch_noc('train',{})
if __name__=='__main__':unittest.main()
