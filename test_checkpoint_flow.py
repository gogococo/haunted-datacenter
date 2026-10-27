"""Model ownership, download boundaries and loading gates, without real cloud calls."""
import io,json,tempfile,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch,Mock
import caretaker as c,checkpoint_flow as flow,content,lessons,server

class OwnershipTests(unittest.TestCase):
 def prepared(self):
  n=c.initial();source='\n'.join(json.dumps(x) for x in content.clean_records());n['baseline']={'passed':False}
  n['submission']={'id':'mine','model':'Qwen/Qwen3-0.6B','training_file':'my-train','validation_file':'my-valid','pack_hash':lessons.packet_hash(n,source)}
  return n,source
 def test_old_checkpoint_cannot_certify_the_new_job(self):
  n,_=self.prepared();n['route']='finetuned';n['job']={'id':'alex'}
  with self.assertRaisesRegex(ValueError,'own training job'):c.require_own_model(n)
 def test_prompting_is_not_a_default_shortcut(self):
  n,source=self.prepared();n['route']='prompt'
  with self.assertRaises(ValueError):c.require_own_model(n)
  with self.assertRaisesRegex(ValueError,'host-only'):c.activate_prompt_route(n,source)
 def test_explicit_host_experiment_is_distinguished(self):
  n,_=self.prepared();n['route']='prompt';n['host_override']={'kind':'prompt'};c.require_own_model(n)
 def test_default_loader_uses_this_job_and_checks_runner_identity(self):
  n,source=self.prepared();job={**n['submission'],'status':'succeeded'}
  with tempfile.TemporaryDirectory() as tmp:
   receipt=Path(tmp)/'receipt.json';receipt.write_text(json.dumps({'checkpoint_id':'my-final'}))
   health={'job_id':'mine','model':job['model'],'training_file':'my-train','validation_file':'my-valid','checkpoint_id':'my-final','artifact_hash':'actual-weights'}
   with patch.object(flow,'prepare',return_value=(receipt,job)),patch.object(flow,'reload_runner',return_value=health):c.activate_own_checkpoint(n,source,Path(tmp),lambda _:None)
  self.assertEqual(n['job']['id'],'mine');self.assertTrue(n['runner']['active']);self.assertNotIn('host_override',n)
 def test_runner_loading_another_job_is_rejected(self):
  n,source=self.prepared();job={**n['submission'],'status':'succeeded'}
  with tempfile.TemporaryDirectory() as tmp:
   receipt=Path(tmp)/'receipt.json';receipt.write_text(json.dumps({'checkpoint_id':'my-final'}))
   with patch.object(flow,'prepare',return_value=(receipt,job)),patch.object(flow,'reload_runner',return_value={'job_id':'alex','model':job['model']}),self.assertRaisesRegex(ValueError,'submitted training job'):c.activate_own_checkpoint(n,source,Path(tmp),lambda _:None)
  self.assertEqual(n['route'],'untrained')
 def test_blocked_download_does_not_activate_the_old_model(self):
  n,source=self.prepared();n['checkpoint_download']={'status':'needs_import','message':'Import your weights'}
  with patch.object(flow,'prepare',return_value=None),patch.object(flow,'reload_runner') as reload:c.activate_own_checkpoint(n,source,Path('.'),lambda _:None)
  reload.assert_not_called();self.assertEqual(n['route'],'untrained')
 def test_changed_cloud_dataset_identity_is_rejected_without_overwriting_receipt(self):
  n,source=self.prepared();job={**n['submission'],'status':'succeeded','training_file':'different'}
  with patch.object(flow.tf,'api',return_value=job),self.assertRaisesRegex(ValueError,'submitted pack'):flow.prepare(n,source,Path('.'),lambda _:None)
  self.assertEqual(n['submission']['training_file'],'my-train')
 def test_submission_opens_maintenance_access_before_certification(self):
  n,source=self.prepared();old=server.STATE
  try:
   server.STATE=server.fresh();server.STATE.update(noc=n,sources={'dataset':source},rooms=[True,False,False])
   self.assertFalse(server.maintenance_access());self.assertFalse(server.STATE['rooms'][1])
   server.STATE['rooms'][1]=True
   self.assertTrue(server.maintenance_access())
   n['submission']['pack_hash']='wrong-pack';self.assertFalse(server.maintenance_access())
  finally:server.STATE=old
 def test_old_noc_shortcut_routes_are_rejected(self):
  handler=object.__new__(server.Handler)
  for route in ('backup','prompt-profile'):
   with patch.object(server.hosting,'clock',return_value={'expired':False}),self.assertRaisesRegex(ValueError,'host controls'):handler.action('/api/noc/'+route,{})

class DownloadTests(unittest.TestCase):
 def redirect(self,url):return urllib.error.HTTPError('https://api.tokenfactory.nebius.com/file',307,'redirect',{'Location':url},None)
 def test_signed_storage_request_does_not_receive_bearer_key(self):
  opener=Mock();opener.open.side_effect=[self.redirect('https://storage.eu-west2.nebius.cloud/bucket/model?signature=private'),io.BytesIO(b'weights')]
  with tempfile.TemporaryDirectory() as tmp,patch.object(flow.tf,'key',return_value='secret'),patch.object(flow.urllib.request,'build_opener',return_value=opener):
   dest=Path(tmp)/'adapter';flow.download('file',dest,7);self.assertEqual(dest.read_bytes(),b'weights')
  self.assertEqual(opener.open.call_args_list[0].args[0].get_header('Authorization'),'Bearer secret')
  self.assertIsNone(opener.open.call_args_list[1].args[0].get_header('Authorization'))
 def test_unexpected_redirect_host_is_rejected(self):
  opener=Mock();opener.open.side_effect=self.redirect('https://evil.example/weights')
  with patch.object(flow.tf,'key',return_value='secret'),patch.object(flow.urllib.request,'build_opener',return_value=opener),self.assertRaisesRegex(ValueError,'Unexpected'):flow.download('file',Path('unused'),1)
  self.assertEqual(opener.open.call_count,1)
 def test_storage_failure_does_not_expose_signed_url(self):
  opener=Mock();opener.open.side_effect=[self.redirect('https://storage.eu-west2.nebius.cloud/weights?signature=private'),urllib.error.HTTPError('private',403,'denied',{},None)]
  with patch.object(flow.tf,'key',return_value='secret'),patch.object(flow.urllib.request,'build_opener',return_value=opener),self.assertRaises(flow.DownloadUnavailable) as error:flow.download('file',Path('unused'),1)
  self.assertNotIn('signature',str(error.exception));self.assertNotIn('private',str(error.exception))
 def test_truncated_download_is_not_written(self):
  opener=Mock();opener.open.return_value=io.BytesIO(b'bad')
  with tempfile.TemporaryDirectory() as tmp,patch.object(flow.tf,'key',return_value='secret'),patch.object(flow.urllib.request,'build_opener',return_value=opener):
   dest=Path(tmp)/'adapter'
   with self.assertRaisesRegex(ValueError,'size differs'):flow.download('file',dest,8)
   self.assertFalse(dest.exists())
if __name__=='__main__':unittest.main()
