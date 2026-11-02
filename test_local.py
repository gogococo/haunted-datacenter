"""Local transport boundaries and resource isolation; model quality is checked live."""
import json, os, pathlib, tempfile, unittest
from unittest.mock import patch
import haunted_cli, local_runtime, serverless, tokenfactory, training_cloud

ENV = {'HAUNTED_LOCAL_WORKERS':'1','PUBLIC_DEPLOYMENT':'false',
       'CARETAKER_WORKER_URL':'http://caretaker:8000','CARETAKER_WORKER_TOKEN':'local-test-worker',
       'LOCAL_COOLING_URL':'http://cooling:8000','LOCAL_COOLING_TOKEN':'local-test-cooling'}


class LocalBoundaryTests(unittest.TestCase):
    def test_http_worker_requires_explicit_local_mode(self):
        with patch.dict(os.environ, {'HAUNTED_LOCAL_WORKERS':'0','CARETAKER_WORKER_URL':'http://caretaker:8000'}):
            with self.assertRaisesRegex(ValueError, 'HTTPS'): training_cloud.api('/healthz')

    def test_local_mode_rejects_public_hosting_and_foreign_targets(self):
        with patch.dict(os.environ, {**ENV,'PUBLIC_DEPLOYMENT':'true'}):
            with self.assertRaisesRegex(ValueError, 'public deployment'): local_runtime.endpoint('caretaker')
        for target in ('http://example.com:8000','http://caretaker:8000@evil.test',
                       'http://caretaker:8000/path','http://caretaker:8000?key=value'):
            with patch.dict(os.environ, {**ENV,'CARETAKER_WORKER_URL':target}):
                with self.assertRaisesRegex(ValueError,'private Docker'): local_runtime.endpoint('caretaker')

    def test_local_mode_cannot_provision_nebius_or_token_factory_resources(self):
        with patch.dict(os.environ, ENV), patch.object(serverless.subprocess,'run',side_effect=AssertionError('Cloud CLI must not run')):
            with self.assertRaisesRegex(ValueError,'disabled'): serverless.cli(['ai','endpoint','create'])
            for path in ('/v1/fine_tuning/jobs','/v0/dedicated_endpoints','/v1/files'):
                with self.assertRaisesRegex(ValueError,'disabled'): tokenfactory.api(path,'POST',{})

    def test_local_worker_transport_keeps_auth_and_disables_redirects(self):
        response=unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value=b'{"ready":true}'
        opener=unittest.mock.Mock();opener.open.return_value=response
        with patch.dict(os.environ,ENV),patch.object(training_cloud.urllib.request,'build_opener',return_value=opener) as build:
            self.assertTrue(training_cloud.api('/healthz')['ready'])
        self.assertIs(build.call_args.args[0],tokenfactory.NoRedirect)
        request=opener.open.call_args.args[0]
        self.assertEqual(request.full_url,'http://caretaker:8000/healthz')
        self.assertEqual(request.get_header('Authorization'),'Bearer local-test-worker')

    def test_commissioning_stays_required_and_tokens_remain_private(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,ENV):
            root=pathlib.Path(folder);state={}
            with self.assertRaisesRegex(ValueError,'equipment-plate'):
                serverless.deploy(state,{'port':9999,'target':75,'budget':12},root,'player')
            with patch.object(serverless,'cli',side_effect=AssertionError('No cloud calls')):
                serverless.deploy(state,{'port':8000,'target':75,'budget':12},root,'player')
                serverless.prewarm(root,'player');serverless.release(root,'player');serverless.reap(root)
            self.assertTrue(state['endpoint']['local'])
            self.assertNotIn(ENV['LOCAL_COOLING_TOKEN'],json.dumps(state))
            receipt=serverless.private_path(root,'local-cooling')
            self.assertEqual(receipt.stat().st_mode & 0o777,0o600)

    def test_saved_cloud_controller_cannot_be_called_in_local_mode(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,ENV):
            with self.assertRaisesRegex(ValueError,'Reconnect'):
                serverless.call({'endpoint':{'id':'old-cloud','url':'https://old.nebius.cloud'}},pathlib.Path(folder),'/healthz')


class LauncherTests(unittest.TestCase):
    def test_env_file_is_data_and_only_two_service_keys_are_read(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{},clear=True):
            path=pathlib.Path(folder)/'.env'
            path.write_text('NEBIUS_API_KEY="test-token"\nTAVILY_API_KEY=literal$(not-executed)\nNEBIUS_PRIVATE_KEY=never-copy\nCARETAKER_WORKER_URL=https://old.nebius.cloud\n')
            self.assertEqual(haunted_cli.read_keys(path),{'NEBIUS_API_KEY':'test-token','TAVILY_API_KEY':'literal$(not-executed)'})

    def test_stable_local_credentials_and_curated_environment(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(haunted_cli,'ROOT',pathlib.Path(folder)),patch.dict(os.environ,{'NEBIUS_PRIVATE_KEY':'private','DOCKER_HOST':'tcp://cloud','PUBLIC_DEPLOYMENT':'true'}):
            a=haunted_cli.compose_environment({'TAVILY_API_KEY':'example'},'haunted-test',8782)
            b=haunted_cli.compose_environment({},'haunted-test',8782)
            self.assertEqual(a['LOCAL_WORKER_TOKEN'],b['LOCAL_WORKER_TOKEN'])
            self.assertNotEqual(a['LOCAL_WORKER_TOKEN'],a['LOCAL_COOLING_TOKEN'])
            for key in ('NEBIUS_PRIVATE_KEY','DOCKER_HOST','PUBLIC_DEPLOYMENT'): self.assertNotIn(key,a)
            path=pathlib.Path(folder)/'.local-docker/haunted-test/worker-tokens.json'
            self.assertEqual(path.stat().st_mode & 0o777,0o600)


if __name__=='__main__': unittest.main()
