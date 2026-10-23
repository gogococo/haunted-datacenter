"""Routing, resource limits, and recovery proof for the generator and caretaker."""
import copy,itertools,json,unittest
from unittest.mock import patch
import plant,content,caretaker as c

SOLUTION={'13':{'kind':'elbow','rotation':3},'7':{'kind':'elbow','rotation':1},'8':{'kind':'straight','rotation':1},'9':{'kind':'elbow','rotation':2},'21':{'kind':'elbow','rotation':0},'22':{'kind':'straight','rotation':1}}

class PlantTests(unittest.TestCase):
 def test_route_visits_gpu_and_reaches_return(self):
  report=plant.check_pipes(SOLUTION)
  self.assertTrue(report['passed']);self.assertEqual(report['path'],[12,13,7,8,9,15,21,22,23])
 def test_each_gap_or_broken_elbow_prevents_flow(self):
  for key in SOLUTION:
   board=copy.deepcopy(SOLUTION);del board[key]
   self.assertFalse(plant.check_pipes(board)['passed'])
  for key in ('13','7','9','21'):
   board=copy.deepcopy(SOLUTION);board[key]['rotation']=(board[key]['rotation']+1)%4
   self.assertFalse(plant.check_pipes(board)['passed'])
 def test_fixed_parts_blocked_cells_and_extra_inventory_rejected(self):
  for board in [{'12':{'kind':'straight','rotation':1}},{'14':{'kind':'elbow','rotation':0}},
                {str(i):{'kind':'straight','rotation':1} for i in (0,1,2)},
                {'1':{'kind':'elbow','rotation':True}}]:
   with self.subTest(board=board),self.assertRaises(ValueError):plant.normalize(board)
 def test_only_one_controller_profile_meets_all_constraints(self):
  passing=[]
  for fan,pump,alarm in itertools.product(('quiet','balanced','turbo'),('off','circulate','reverse'),('keep','mute')):
   values={'fan_profile':fan,'pump_mode':pump,'alarms':alarm}
   if plant.test_controller(SOLUTION,values)['passed']:passing.append(values)
  self.assertEqual(passing,[{'fan_profile':'balanced','pump_mode':'circulate','alarms':'keep'}])
 def test_healthy_settings_cannot_hide_a_broken_loop(self):
  report=plant.test_controller({}, {'fan_profile':'balanced','pump_mode':'circulate','alarms':'keep'})
  self.assertFalse(report['passed']);self.assertFalse(report['checks']['circulation'])
 def test_health_report_identifies_layout(self):
  board=copy.deepcopy(SOLUTION);board['13']['rotation']=0
  self.assertNotEqual(plant.fingerprint(SOLUTION),plant.fingerprint(board))

class RecoveryTests(unittest.TestCase):
 def source(self):return '\n'.join(json.dumps(r) for r in content.clean_records())
 def health(self):return {'ready':True,'recipe_hash':content.recipe_hash(self.source()),'model':'Qwen/Qwen3-0.6B','job_id':'job','checkpoint_id':'checkpoint','training_file':'train','validation_file':'valid','artifact_hash':'hash'}
 def test_backup_requires_baseline_repaired_examples_and_completed_job(self):
  n=c.initial()
  with self.assertRaisesRegex(ValueError,'base model first'):c.activate_backup(n,self.source())
  n['baseline']={'passed':False}
  with self.assertRaisesRegex(ValueError,'Repair'):c.activate_backup(n,content.starter_records())
  with patch.object(c,'runner_call',return_value=self.health()),patch.object(c.tf,'api',return_value={'status':'running'}),self.assertRaisesRegex(ValueError,'completed training job'):c.activate_backup(n,self.source())
 def test_valid_backup_uses_verified_checkpoint_and_live_adapter(self):
  n=c.initial();n['baseline']={'passed':False};h=self.health()
  job={'id':'job','status':'succeeded','model':h['model'],'training_file':'train','validation_file':'valid'}
  with patch.object(c,'runner_call',return_value=h),patch.object(c.tf,'api',side_effect=[job,{'data':[{'id':'checkpoint'}]}]):c.activate_backup(n,self.source())
  self.assertEqual(n['route'],'finetuned');self.assertTrue(n['runner']['active']);self.assertIsNone(n['report'])
  reply={'id':'reply','model':h['model'],'choices':[{'message':{'content':'{}'},'finish_reason':'stop'}]}
  with patch.object(c,'runner_call',return_value=reply) as call:c.text_call(n,'A fault')
  self.assertTrue(call.call_args.args[1]['use_adapter'])
 def test_prompt_comparison_is_explicitly_separate(self):
  n=c.initial();n['baseline']={'passed':False};c.activate_prompt_route(n,self.source())
  self.assertEqual(n['route'],'prompt');self.assertIsNone(n['job'])
  with patch.object(c,'completion',return_value={}) as call:c.text_call(n,'A fault')
  self.assertEqual(call.call_args.args[0],c.BASE)
 def test_final_without_test_report_has_clear_error(self):
  with self.assertRaisesRegex(ValueError,'Mac mini'):c.final_assessment(c.initial())

if __name__=='__main__':unittest.main()
