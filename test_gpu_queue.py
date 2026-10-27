"""Shared GPU admission, exam isolation and resume warm-up regression checks."""
import copy,json,queue,tempfile,threading,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import training_worker as worker,training_cloud as cloud,caretaker,server

class QueueTests(unittest.TestCase):
 def setUp(self):
  self.patches=[patch.object(worker,'PENDING',queue.Queue(maxsize=8)),patch.object(worker,'SLOTS',{}),patch.object(worker,'ACTIVE_SLOT',None),patch.object(worker,'CURRENT_JOB',None),patch.object(worker,'READY',True)]
  for p in self.patches:p.start()
 def tearDown(self):
  for p in reversed(self.patches):p.stop()
 def reserve(self,job=None):return worker.reserve({'request_id':str(uuid.uuid4()),'job_id':job,'label':'practical exam'})
 def wait_active(self,slot):
  end=time.monotonic()+1
  while time.monotonic()<end:
   if worker.slot_info(slot)['status']=='active':return
   time.sleep(.002)
  self.fail('GPU slot did not become active')
 def test_complete_exam_holds_slot_before_training_and_next_player(self):
  job='train-'+'a'*32;first=self.reserve(job);events=[]
  worker.PENDING.put(('train','training-job'));second=self.reserve()
  def consume():
   for _ in range(3):worker.process_next()
  with patch.object(worker,'train_job',side_effect=lambda _:events.append('training')):
   thread=threading.Thread(target=consume,daemon=True);thread.start();self.wait_active(first['id'])
   self.assertEqual(worker.slot_info(second['id'])['queue_ahead'],2)
   for request in ('exam-request-1','exam-request-12','fresh-camera-check'):
    with worker.gpu_access({'slot_id':first['id'],'job_id':job}):events.append(request)
   self.assertNotIn('training',events)
   worker.release_slot(first['id']);self.wait_active(second['id'])
   self.assertEqual(events,['exam-request-1','exam-request-12','fresh-camera-check','training'])
   worker.release_slot(second['id']);thread.join(1);self.assertFalse(thread.is_alive())
 def test_retrying_reservation_is_idempotent_and_cannot_change_checkpoint(self):
  body={'request_id':str(uuid.uuid4()),'job_id':'train-'+'a'*32}
  first=worker.reserve(body);self.assertEqual(worker.reserve(body)['id'],first['id']);self.assertEqual(worker.PENDING.qsize(),1)
  with self.assertRaisesRegex(ValueError,'another checkpoint'):worker.reserve({**body,'job_id':'train-'+'b'*32})
 def test_wrong_checkpoint_cannot_use_another_players_slot(self):
  first=self.reserve('train-'+'a'*32);thread=threading.Thread(target=worker.process_next,daemon=True);thread.start();self.wait_active(first['id'])
  try:
   with self.assertRaisesRegex(ValueError,'does not match'):
    with worker.gpu_access({'slot_id':first['id'],'job_id':'train-'+'b'*32}):self.fail('Mismatched job received GPU access')
  finally:worker.release_slot(first['id']);thread.join(1)
 def test_cancelled_waiter_does_not_block_the_next_job(self):
  slot=self.reserve();worker.release_slot(slot['id']);worker.PENDING.put(('train','next'));events=[]
  with patch.object(worker,'train_job',side_effect=events.append):worker.process_next();worker.process_next()
  self.assertEqual(events,['next']);self.assertEqual(worker.slot_info(slot['id'])['status'],'cancelled')
 def test_expiry_waits_for_inflight_generation_before_next_training(self):
  slot=self.reserve();worker.PENDING.put(('train','next'));trained=threading.Event();inside=threading.Event();finish=threading.Event()
  def consume():worker.process_next();worker.process_next()
  def generate():
   with worker.gpu_access({'slot_id':slot['id'],'job_id':None}):inside.set();finish.wait(2)
  with patch.object(worker,'SLOT_TTL',.02),patch.object(worker,'train_job',side_effect=lambda _:trained.set()):
   consumer=threading.Thread(target=consume,daemon=True);consumer.start();self.wait_active(slot['id'])
   generation=threading.Thread(target=generate,daemon=True);generation.start();self.assertTrue(inside.wait(1))
   self.assertFalse(trained.wait(.35));finish.set();generation.join(1);consumer.join(1)
   self.assertTrue(trained.is_set());self.assertEqual(worker.slot_info(slot['id'])['status'],'expired')
 def test_queue_capacity_rejection_does_not_create_a_task(self):
  for _ in range(8):self.reserve()
  with self.assertRaisesRegex(ValueError,'queue is full'):self.reserve()
  self.assertEqual(len(worker.SLOTS),8)

class ClientQueueTests(unittest.TestCase):
 def test_wait_is_visible_then_one_slot_covers_all_requests_and_releases_on_failure(self):
  messages=[];calls=[];n={'route':'finetuned','runner':{'active':True},'submission':{'id':'train-'+'a'*32}}
  def api(path,body=None):
   calls.append((path,body))
   if path=='/slots':
    self.identifier='slot-'+body['request_id'].replace('-','');return {'id':self.identifier,'job_id':n['submission']['id'],'status':'queued','queue_ahead':2}
   if path.startswith('/slots/') and path!='/slots/release':return {'id':self.identifier,'job_id':n['submission']['id'],'status':'active','queue_ahead':0}
   return {'released':True}
  with patch.object(cloud,'configured',return_value=True),patch.object(cloud,'api',side_effect=api),patch.object(cloud.time,'sleep'):
   with self.assertRaisesRegex(ValueError,'exam failed'):
    with cloud.gpu_slot('verify',n,messages.append):
     self.assertEqual(cloud.queued_body({'job_id':n['submission']['id']})['slot_id'],self.identifier)
     self.assertEqual(cloud.queued_body({})['slot_id'],self.identifier)
     raise ValueError('exam failed')
  self.assertTrue(any('2 tasks ahead' in m for m in messages));self.assertIsNone(cloud.SLOT.get())
  self.assertEqual(calls[-1],('/slots/release',{'slot_id':self.identifier}))
 def test_queue_receipt_must_match_the_requested_checkpoint(self):
  def api(path,body=None):
   if path=='/slots':return {'id':'slot-'+body['request_id'].replace('-',''),'job_id':'other','status':'active'}
   return {}
  with patch.object(cloud,'configured',return_value=True),patch.object(cloud,'api',side_effect=api):
   with self.assertRaisesRegex(ValueError,'receipt'):
    with cloud.gpu_slot('test',{},lambda _:None):self.fail('Wrong receipt was accepted')
 def test_full_verify_uses_one_queue_slot_and_vision_only_stays_outside_queue(self):
  n=caretaker.initial();n['training_provider']='serverless'
  from contextlib import contextmanager
  order=[]
  @contextmanager
  def slot(*args):
   order.append('entered');yield;order.append('released')
  def run(*args):order.append('whole exam');return 'done'
  with patch.object(cloud,'gpu_slot',side_effect=slot),patch.object(caretaker,'_run',side_effect=run):
   caretaker.run('verify',n,{},'',Path('.'),lambda _:None)
   self.assertEqual(order,['entered','whole exam','released']);order.clear()
   caretaker.run('inspect',n,{},'',Path('.'),lambda _:None);self.assertEqual(order,['whole exam'])

class ResumeWarmupTests(unittest.TestCase):
 def setUp(self):
  self.old_state=server.STATE;self.state=server.fresh();self.state['started']=time.time();server.STATE=self.state
 def tearDown(self):server.STATE=self.old_state
 def test_resume_warms_existing_controller_without_changing_progress(self):
  self.state['rooms'][0]=True;before=copy.deepcopy(self.state)
  with patch.object(server,'warm_existing_controller') as warm:server.Handler.action(None,'/api/resume',{})
  warm.assert_called_once_with(server.RUNTIME,self.state['run_id']);self.assertEqual(self.state,before)
 def test_finished_and_expired_games_do_not_warm(self):
  for expired in (False,True):
   self.state['started']=time.time()-2800 if expired else time.time();self.state['finished']=None if expired else time.time();self.state['escaped']=not expired
   with patch.object(server,'warm_existing_controller') as warm,self.assertRaises(ValueError):server.Handler.action(None,'/api/resume',{})
   warm.assert_not_called()

if __name__=='__main__':unittest.main()
