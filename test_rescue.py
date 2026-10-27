"""Regression checks for the teaching curriculum and model-only door connection."""
import copy,json,queue,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
import caretaker,content,lessons,plant,server,serverless,training_worker,cloud_controller
from test_plant import SOLUTION

class TeachingTests(unittest.TestCase):
 def test_healthy_case_must_be_observed_tried_and_demonstrated(self):
  n=caretaker.initial();n['observations']['healthy']={'equipment':'gpu_rack','fault':'healthy','observation':'Fan is healthy','request':'Independent camera says healthy','inference':{'request_id':'vision'}}
  with self.assertRaises(ValueError):lessons.record(n,'healthy',content.starter_records())
  lessons.try_example(n,'healthy');self.assertFalse(n['demonstrations']['healthy']['correct'])
  self.assertIn('stops',n['demonstrations']['healthy']['outcome'])
  lessons.evidence(n,'healthy');lessons.rehearse(n,'healthy','leave_alone')
  lessons.record(n,'healthy',content.starter_records())
  self.assertEqual(n['lessons']['healthy']['answer'],{'action':'leave_alone','equipment':'gpu_rack'})
 def test_misread_camera_cannot_silently_become_a_training_label(self):
  n=caretaker.initial();n['observations']['healthy']={'equipment':'gpu_rack','fault':'fan_failure','observation':'Bad scan','request':'Wrong scan','inference':{}}
  lessons.try_example(n,'healthy');lessons.evidence(n,'healthy');lessons.rehearse(n,'healthy','leave_alone')
  with self.assertRaisesRegex(ValueError,'vision report'):lessons.record(n,'healthy',content.starter_records())
 def test_personality_prompt_never_changes_the_equipment_system_prompt(self):
  n=caretaker.initial();before=copy.deepcopy(n['config'])
  reply={'output':'I have arrived. Expectations pending.','model':'dialogue','request_id':'actual-request'}
  with patch.object(caretaker,'completion',return_value=reply) as call:caretaker.personality(n,'sarcastic')
  self.assertEqual(n['config'],before);self.assertEqual(n['dialogue']['request_id'],'actual-request')
  self.assertIn('sarcasm',call.call_args.args[1][0]['content'])
 def test_curriculum_has_distinct_validation_and_both_safe_and_unsafe_examples(self):
  train=lessons.curriculum('train');valid=lessons.curriculum('validation')
  self.assertFalse({r['messages'][1]['content'] for r in train}&{r['messages'][1]['content'] for r in valid})
  answers=[json.loads(r['messages'][2]['content']) for r in train]
  self.assertIn({'action':'leave_alone','equipment':'gpu_rack'},answers)
  self.assertIn({'action':'leave_alone','equipment':'exit_door'},answers)
  self.assertIn({'action':'release_latch','equipment':'exit_door'},answers)

class WarmSubmissionTests(unittest.TestCase):
 def test_retries_keep_the_same_job_and_changed_data_is_rejected(self):
  record=content.clean_records()[0];valid=copy.deepcopy(record);valid['messages'][1]['content']='Independent validation'
  body={'request_id':'f325691c-1bde-4485-a8cc-c03c488bdc1b','train':[record]*3,'validation':[valid]*3}
  with tempfile.TemporaryDirectory() as tmp,patch.object(training_worker,'ROOT',Path(tmp)),patch.object(training_worker,'JOBS',{}),patch.object(training_worker,'PENDING',queue.Queue(maxsize=8)),patch.object(training_worker,'READY',True):
   first=training_worker.submit(body);second=training_worker.submit(body)
   self.assertEqual(first['id'],second['id']);self.assertEqual(training_worker.PENDING.qsize(),1)
   other=copy.deepcopy(body);other['train'][0]['messages'][1]['content']='Changed pack'
   with self.assertRaisesRegex(ValueError,'another pack'):training_worker.submit(other)

class VisualControllerTests(unittest.TestCase):
 def test_player_controls_reach_the_cloud_logic_and_only_balanced_passes(self):
  for fan in ('quiet','balanced','turbo'):
   result=cloud_controller.simulate({'loop_sealed':True,'nonce':fan,'settings':{'fan_profile':fan,'pump_mode':'circulate','alarms':'keep'}})
   self.assertEqual(result['settings']['fan_profile'],fan)
   self.assertEqual(result['healthy'],fan=='balanced')
  self.assertGreater(cloud_controller.simulate({'loop_sealed':True,'nonce':'hot','settings':{'fan_profile':'quiet','pump_mode':'circulate','alarms':'keep'}})['temperature_c'],75)
 def test_wrong_commissioning_values_do_not_mutate_cloud(self):
  p=plant.initial();p['maintenance_book_read']=True
  for values in ({},{'port':8000,'target':75,'budget':13},{'port':8000,'target':float('nan'),'budget':12}):
   with self.assertRaises(ValueError):plant.deployment_values(p,values)
  self.assertIsNone(p['endpoint'])

class DoorTests(unittest.TestCase):
 def setUp(self):
  self.old,self.rt=server.STATE,server.RUNTIME;self.tmp=tempfile.TemporaryDirectory();server.RUNTIME=Path(self.tmp.name);server.STATE=server.fresh();self.s=server.STATE
  self.s['rooms']=[True,True,False];n=self.s['noc'];n.update(route='finetuned',training_provider='serverless',personality='friendly',submission={'id':'job'},job={'id':'job'},runner={'active':True,'artifact_hash':'own-adapter','provider':'serverless'})
  p=self.s['plant'];p.update(pipes=copy.deepcopy(SOLUTION),settings={'fan_profile':'balanced','pump_mode':'circulate','alarms':'keep'},maintenance_book_read=True,endpoint={'id':'cloud','config':plant.DEPLOYMENT_SETTINGS.copy()})
  plant.commission(p,plant.DEPLOYMENT_SETTINGS.copy());p['health']={'passed':True,'endpoint_id':'cloud'};p['report']={**plant.test_controller(SOLUTION,p['settings']),'endpoint_id':'cloud','request_nonce':'fresh'}
 def tearDown(self):server.STATE=self.old;server.RUNTIME=self.rt;self.tmp.cleanup()
 def wait(self):
  for _ in range(200):
   with server.LOCK:
    if self.s['noc']['operation']['status']!='running':return
   time.sleep(.005)
  self.fail('Exit inspection did not finish')
 def response(self,action='release_latch'):return {'output':json.dumps({'action':action,'equipment':'exit_door'}),'finish_reason':'stop','model':'own-trained-model'}
 def test_correct_real_model_decision_records_score_before_releasing_cpu_lease(self):
  def release(*args):self.assertTrue(self.s['escaped']);self.assertEqual(self.s['result'],{'saved':True})
  with patch.object(caretaker,'text_call',return_value=self.response()) as infer,patch.object(caretaker,'personality'),patch.object(server.hosting,'record',return_value={'saved':True}),patch.object(serverless,'release',side_effect=release) as cleanup:
   server.launch_exit();self.wait()
  self.assertTrue(self.s['escaped']);self.assertIn('cooling_healthy',infer.call_args.args[1]);cleanup.assert_called_once()
 def test_unsafe_room_stays_locked_even_if_model_requests_release(self):
  self.s['plant']['report']['passed']=False
  with patch.object(caretaker,'text_call',return_value=self.response()),patch.object(serverless,'release') as release:
   server.launch_exit();self.wait()
  self.assertFalse(self.s['escaped']);release.assert_not_called()
 def test_invalid_command_does_not_open_a_safe_room(self):
  with patch.object(caretaker,'text_call',return_value=self.response('leave_alone')):
   server.launch_exit();self.wait()
  self.assertFalse(self.s['escaped'])
 def test_controls_changed_during_generation_invalidate_the_approval(self):
  entered,finish=threading.Event(),threading.Event()
  def delayed(*args):entered.set();finish.wait(2);return self.response()
  with patch.object(caretaker,'text_call',side_effect=delayed),patch.object(caretaker,'personality'):
   server.launch_exit();self.assertTrue(entered.wait(1));self.s['plant']['revision']+=1;finish.set();self.wait()
  self.assertFalse(self.s['escaped']);self.assertEqual(self.s['noc']['operation']['status'],'failed')

if __name__=='__main__':unittest.main()
