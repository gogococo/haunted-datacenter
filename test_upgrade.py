"""Learning-path gates and cloud execution proof; all external calls mocked here."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import lessons,content,caretaker,serverless,cloud_controller,plant,switchboard
from test_plant import SOLUTION

class MQTTTests(unittest.TestCase):
 def test_plus_is_one_level_hash_is_zero_or_more(self):
  for filt,topic,want in [('a/+','a/b',True),('a/+','a/b/c',False),('a/#','a',True),('a/#','a/b/c',True),('a/+','a/',True),('#','$SYS/status',False)]:
   self.assertEqual(switchboard.topic_matches(filt,topic),want)
 def test_malformed_filters_are_rejected(self):
  for value in ('a/#/b','a/x+','a/b#',''):
   with self.assertRaises(ValueError):switchboard.topic_matches(value,'a/b')
 def test_broad_and_exact_filters_do_not_pass_mabels_request(self):
  for value in ('#','midnight/#','midnight/door/announcement','+/+/announcement'):
   self.assertFalse(switchboard.test_subscription(value)['passed'])
  self.assertTrue(switchboard.test_subscription('midnight/+/announcement')['passed'])

class DemonstrationTests(unittest.TestCase):
 def setUp(self):self.n=caretaker.initial();self.source=content.starter_records()
 def prepare(self,id):
  note=lessons.NOTES[id]
  self.n['observations'][id]={'reviewed':True,'observation':'Actual camera report '+id,'request':'Real observation '+id,'inference':{'request_id':'vision-'+id}}
  self.n['probes'][id]={'output':'actual base reply'};lessons.evidence(self.n,id)
  return note
 def test_guessing_controls_without_vision_does_not_record_a_lesson(self):
  with self.assertRaises(ValueError):lessons.rehearse(self.n,'east','stop_pump')
  with self.assertRaises(ValueError):lessons.record(self.n,'east',self.source)
 def test_wrong_demonstration_remains_a_failed_rehearsal(self):
  self.prepare('east');lessons.rehearse(self.n,'east','restart_fans')
  self.assertFalse(self.n['demonstrations']['east']['correct'])
  with self.assertRaises(ValueError):lessons.record(self.n,'east',self.source)
 def test_record_keeps_actual_vision_input_and_exact_demonstrated_command(self):
  note=self.prepare('east');lessons.rehearse(self.n,'east',note['action']);self.source=lessons.record(self.n,'east',self.source)
  lesson=self.n['lessons']['east'];self.assertEqual(lesson['input'],'Real observation east');self.assertEqual(lesson['answer'],{'action':'stop_pump','equipment':'cooling_loop'})
  self.assertEqual(lesson['camera_request_id'],'vision-east')
 def test_pack_contains_real_records_and_validation_is_separate(self):
  for id in lessons.NOTES:
   note=self.prepare(id);lessons.rehearse(self.n,id,note['action']);self.source=lessons.record(self.n,id,self.source)
  with tempfile.TemporaryDirectory() as tmp:
   counts=lessons.write_pack(self.n,self.source,Path(tmp));self.assertEqual(counts['train'],75)
   rows=[json.loads(x) for x in (Path(tmp)/'train.jsonl').read_text().splitlines()]
   self.assertEqual({r['messages'][1]['content'] for r in rows[-3:]},{x['input'] for x in self.n['lessons'].values()})
   self.assertFalse({x['prompt'] for x in caretaker.LIVE_CASES}&{r['messages'][1]['content'] for r in rows})
 def test_pack_is_locked_after_submission(self):
  self.n['submission']={'id':'real-job'}
  with self.assertRaisesRegex(ValueError,'already been submitted'):lessons.record(self.n,'east',self.source)
 def test_both_serving_routes_require_a_real_submission_receipt(self):
  for fn in (caretaker.activate_backup,caretaker.activate_prompt_route):
   with self.assertRaisesRegex(ValueError,'Submit'):fn(self.n,self.source)

class RouteStateTests(unittest.TestCase):
 def test_prompt_route_deactivates_the_adapter_and_keeps_submission(self):
  n=caretaker.initial();source='\n'.join(json.dumps(r) for r in content.clean_records())
  n['baseline']={'passed':False};n['runner']={'active':True};n['submission']={'id':'submitted','pack_hash':lessons.packet_hash(n,source)}
  n['host_override']={'kind':'prompt'};caretaker.activate_prompt_route(n,source)
  self.assertFalse(n['runner']['active']);self.assertEqual(n['submission']['id'],'submitted');self.assertEqual(n['route'],'prompt')
 def test_unreadable_actual_reply_cannot_be_recorded_as_a_demonstration(self):
  n=caretaker.initial();n['probes']['east']={'output':'Sure, stop it!','finish_reason':'stop'}
  lessons.try_probe(n,'east');self.assertFalse(n['demonstrations']['east']['correct'])

class CloudControllerTests(unittest.TestCase):
 def test_ready_application_can_still_have_unhealthy_cooling(self):
  r=cloud_controller.simulate({'nonce':'test','loop_sealed':False})
  self.assertTrue(r['ready']);self.assertFalse(r['healthy']);self.assertEqual(r['settings']['pump_mode'],'off')
 def test_application_chooses_lowest_power_valid_profile(self):
  r=cloud_controller.simulate({'nonce':'test','loop_sealed':True})
  self.assertTrue(r['healthy']);self.assertEqual((r['temperature_c'],r['power_kw']),(63,10));self.assertEqual(r['nonce'],'test')
 def test_too_small_power_budget_does_not_claim_success(self):
  r=cloud_controller.simulate({'nonce':'test','loop_sealed':True},75,5)
  self.assertFalse(r['healthy']);self.assertEqual(r['settings']['pump_mode'],'off')
 def test_real_call_response_must_match_current_request_nonce(self):
  p={'endpoint':{'id':'ep'},'health':{'passed':True}}
  with patch.object(serverless,'call',return_value={'service':cloud_controller.VERSION,'nonce':'stale'}),self.assertRaisesRegex(ValueError,'live request'):serverless.assess(p,Path('.'),SOLUTION)
 def test_cloud_result_is_independently_checked_against_circuit(self):
  p={'endpoint':{'id':'ep'},'health':{'passed':True}}
  def remote(p,rt,path,data):return cloud_controller.simulate(data)
  with patch.object(serverless,'call',side_effect=remote):serverless.assess(p,Path('.'),SOLUTION)
  self.assertTrue(p['report']['passed']);self.assertEqual(p['report']['board_hash'],plant.fingerprint(SOLUTION));self.assertTrue(p['report']['request_nonce'])
 def test_fake_remote_measurement_does_not_unlock(self):
  p={'endpoint':{'id':'ep'},'health':{'passed':True}}
  def remote(p,rt,path,data):
   r=cloud_controller.simulate(data);r['temperature_c']=1;return r
  with patch.object(serverless,'call',side_effect=remote):serverless.assess(p,Path('.'),SOLUTION)
  self.assertFalse(p['report']['passed'])
 def test_cloud_metadata_does_not_expose_auth(self):
  row={'metadata':{'id':'ep','name':'app'},'spec':{'auth_token':'secret'},'status':{'state':'RUNNING','public_endpoints':['https://app.example']}}
  self.assertNotIn('secret',json.dumps(serverless.public(row)))
 def test_uncertain_deployment_is_not_resubmitted(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(serverless,'cli') as cli,self.assertRaisesRegex(ValueError,'uncertain'):serverless.deploy({'deployment_unknown':True},{},Path(tmp))
  cli.assert_not_called()
if __name__=='__main__':unittest.main()
