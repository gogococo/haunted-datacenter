import hashlib,importlib.util,json,os,sqlite3,tarfile,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import serverless

ENV={'SHARED_COOLING_ENDPOINT_ID':'aiendpoint-test123','SHARED_COOLING_URL':'https://port8000-example.nebius.cloud',
     'SHARED_COOLING_TOKEN':'test-only-token','SHARED_HOST_NAME':'shared-demos-test','NEBIUS_PROJECT_ID':'project-test'}
def resource():
    return {'metadata':{'id':'aiendpoint-test123','name':'shared-demos-test','parent_id':'project-test'},
            'spec':{'environment_variables':[{'name':'SHARED_DEMO_HOST','value':'1'}],'ports':[{'container_port':8000}]},
            'status':{'state':'RUNNING','public_endpoints':[ENV['SHARED_COOLING_URL']]}}
class SharedHostTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.env=patch.dict(os.environ,ENV);self.env.start()
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def test_reset_idle_cleanup_and_prewarm_never_mutate_shared_host(self):
        with patch.object(serverless,'cli',side_effect=AssertionError('must not invoke cloud lifecycle')):
            serverless.release(self.root,'player',idle=False)
            serverless.release(self.root,'player',idle=True)
            serverless.prewarm(self.root,'player')
    def test_connect_checks_provider_identity_and_keeps_token_private(self):
        state={}
        with patch.object(serverless,'cli',return_value=resource()) as cli:
            serverless.deploy(state,{'port':8000,'target':75,'budget':12},self.root,'player',shared=True)
        self.assertEqual(cli.call_args.args[0],['ai','endpoint','get','aiendpoint-test123'])
        self.assertTrue(state['endpoint']['shared_host']);self.assertNotIn('test-only-token',json.dumps(state))
        self.assertEqual(serverless._read(serverless.private_path(self.root,'aiendpoint-test123'))['token'],'test-only-token')
    def test_wrong_plate_does_not_replace_host(self):
        with patch.object(serverless,'cli',side_effect=AssertionError('no lifecycle')):
            with self.assertRaisesRegex(ValueError,'equipment-plate'):
                serverless.deploy({}, {'port':8000,'target':99,'budget':12},self.root,'player',shared=True)
    def test_foreign_host_or_url_is_rejected(self):
        for field in ('project','name','url','marker','port'):
            row=resource()
            if field=='project':row['metadata']['parent_id']='another-project'
            elif field=='name':row['metadata']['name']='another-demo'
            elif field=='url':row['status']['public_endpoints']=['https://another.nebius.cloud']
            elif field=='marker':row['spec']['environment_variables']=[]
            else:row['spec']['ports']=[]
            with patch.object(serverless,'cli',return_value=row),self.assertRaisesRegex(ValueError,'identity'):
                serverless.shared_connect({}, {'port':8000,'target':75,'budget':12},self.root)
    def test_old_save_refresh_reconnects_and_requires_new_health_check(self):
        state={'endpoint':{'id':'aiendpoint-old'},'health':{'passed':True},'report':{'passed':True}}
        with patch.object(serverless,'cli',return_value=resource()):serverless.refresh(state,self.root)
        self.assertEqual(state['endpoint']['id'],'aiendpoint-test123');self.assertIsNone(state['health']);self.assertIsNone(state['report'])
    def test_shared_logs_are_only_cooling_app_logs(self):
        state={}
        with patch.object(serverless,'call',return_value={'lines':['cooling sample']}),patch.object(serverless,'cli',side_effect=AssertionError('no whole-host logs')):
            serverless.logs(state,self.root)
        self.assertEqual(state['cloud_logs'],'cooling sample')

class BackupTests(unittest.TestCase):
    def test_live_sqlite_backup_and_manifest_can_be_restored(self):
        spec=importlib.util.spec_from_file_location('migration_maintenance',Path(__file__).parent/'deploy/shared/maintenance.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'source';root.mkdir();target=Path(folder)/'backups';target.mkdir()
            (root/'scores').mkdir();(root/'scores/score.json').write_text('{"elapsed":123}')
            db=sqlite3.connect(root/'events.sqlite3');db.execute('PRAGMA journal_mode=WAL');db.execute('CREATE TABLE events(value)');db.execute('INSERT INTO events VALUES (42)');db.commit()
            (root/'outside').symlink_to('/etc/passwd')
            with patch.dict(module.ROOTS,{'haunted':root},clear=True),patch.object(module,'TARGET',target):module.make_backup('haunted')
            result=module.JOBS['haunted'];self.assertEqual(result['status'],'ready')
            self.assertEqual(result['sha256'],hashlib.sha256((target/'haunted.tar.gz').read_bytes()).hexdigest())
            restored=Path(folder)/'restore';restored.mkdir()
            with tarfile.open(target/'haunted.tar.gz') as archive:
                self.assertNotIn('haunted/outside',archive.getnames())
                for member in archive.getmembers():
                    self.assertTrue(member.isfile());self.assertNotIn('..',Path(member.name).parts);self.assertFalse(member.name.startswith('/'))
                    dest=restored/member.name;dest.parent.mkdir(parents=True,exist_ok=True)
                    with archive.extractfile(member) as source:dest.write_bytes(source.read())
            with sqlite3.connect(restored/'haunted/events.sqlite3') as backup:
                self.assertEqual(backup.execute('SELECT value FROM events').fetchone()[0],42)
                self.assertEqual(backup.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            for item in result['manifest']:
                self.assertEqual(item['sha256'],hashlib.sha256((restored/'haunted'/item['path']).read_bytes()).hexdigest())
            db.close()

if __name__=='__main__':unittest.main()
