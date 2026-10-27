"""Resource lifecycle tests: one CPU controller, private receipts, safe cleanup."""
import copy,json,os,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import serverless

PROJECT='project-game'

def resource(id='aiendpoint-controller',state='RUNNING',name='haunted-cooling-controller',target=75):
    return {'metadata':{'id':id,'name':name,'parent_id':PROJECT,'created_at':'2026-10-26'},
            'spec':{'image':'python:3.12-slim','container_command':'python','args':'/opt/controller.py',
                    'ports':[{'container_port':8000}], 'injected_files':[{'container_path':'/opt/controller.py'}],
                    'auth_token':'private-controller-token','environment_variables':[{'name':'TARGET_C','value':str(target)},{'name':'MAX_POWER_KW','value':'12'}]},
            'status':{'state':state,'public_endpoints':['https://controller.example']}}

class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.runtime=Path(self.tmp.name);self.rows={};self.calls=[]
        self.env=patch.dict(os.environ,{'NEBIUS_PROJECT_ID':PROJECT,'NEBIUS_SUBNET_ID':'subnet-game'});self.env.start()
        self.mock=patch.object(serverless,'cli',side_effect=self.cli);self.mock.start()
    def tearDown(self):self.mock.stop();self.env.stop();self.tmp.cleanup()
    def cli(self,args):
        self.calls.append(args)
        action=args[2]
        if action=='list':return {'items':copy.deepcopy(list(self.rows.values()))}
        if action=='get':return copy.deepcopy(self.rows[args[3]])
        if action in ('start','stop'):
            self.rows[args[3]]['status']['state']='STARTING' if action=='start' else 'STOPPED';return {}
        if action=='create':
            if '--dry-run' in args:return {'validated':True}
            row=resource(id='aiendpoint-created',state='STARTING',name=args[args.index('--name')+1]);self.rows[row['metadata']['id']]=row
            return {'resource_id':row['metadata']['id']}
        raise AssertionError(args)
    def actions(self):return [x[2] for x in self.calls if '--dry-run' not in x]
    def test_first_shift_creates_once_second_shift_reuses_after_reset(self):
        p={};serverless.deploy(p,{},self.runtime,'shift-a');id=p['endpoint']['id']
        self.assertEqual(self.actions().count('create'),1)
        serverless.release(self.runtime,'shift-a').join(2)
        self.assertEqual(self.rows[id]['status']['state'],'STOPPED')
        p={};serverless.deploy(p,{},self.runtime,'shift-b')
        self.assertEqual(p['endpoint']['id'],id);self.assertTrue(p['endpoint']['reused'])
        self.assertEqual(self.actions().count('start'),1);self.assertEqual(self.actions().count('create'),1)
    def test_running_legacy_endpoint_is_adopted_without_allocation(self):
        row=resource(name='haunted-cooling-1793048154');self.rows[row['metadata']['id']]=row
        p={};serverless.deploy(p,{},self.runtime,'shift')
        self.assertEqual(self.actions(),['list','get']);self.assertEqual(p['endpoint']['state'],'RUNNING')
        self.assertNotIn('private-controller-token',json.dumps(p))
        self.assertNotIn('private-controller-token',json.dumps(serverless.pool_status(self.runtime)))
        path=serverless.private_path(self.runtime,row['metadata']['id']);self.assertEqual(path.stat().st_mode & 0o777,0o600)
    def test_stopped_legacy_resource_wakes_instead_of_creating(self):
        row=resource(state='STOPPED');self.rows[row['metadata']['id']]=row
        serverless.deploy({}, {},self.runtime,'shift');self.assertEqual(self.actions(),['list','get','start'])
    def test_cleanup_from_old_shift_never_stops_new_lease(self):
        row=resource();self.rows[row['metadata']['id']]=row
        serverless.deploy({}, {},self.runtime,'old');serverless.deploy({}, {},self.runtime,'new')
        serverless.release(self.runtime,'old').join(2)
        self.assertNotIn('stop',self.actions());self.assertEqual(self.rows[row['metadata']['id']]['status']['state'],'RUNNING')
    def test_reset_before_background_deploy_starts_prevents_allocation(self):
        serverless.release(self.runtime,'old').join(2)
        with self.assertRaisesRegex(ValueError,'ended'):serverless.deploy({}, {},self.runtime,'old')
        self.assertEqual(self.calls,[])
    def test_config_change_requires_explicit_replacement_and_stops_first(self):
        row=resource();self.rows[row['metadata']['id']]=row;p={}
        with self.assertRaisesRegex(ValueError,'different configuration'):serverless.deploy(p,{'target':70},self.runtime,'shift')
        self.assertNotIn('stop',self.actions());self.assertNotIn('create',self.actions())
        serverless.replace(p,{'target':70},self.runtime,'shift')
        self.assertLess(self.actions().index('stop'),self.actions().index('create'))
        self.assertEqual(self.rows[row['metadata']['id']]['status']['state'],'STOPPED')
    def test_invalid_config_never_stops_an_existing_controller(self):
        row=resource();self.rows[row['metadata']['id']]=row
        with self.assertRaises(ValueError):serverless.replace({'endpoint':{'id':row['metadata']['id']}},{'port':0},self.runtime,'shift')
        self.assertEqual(self.calls,[])
    def test_other_demo_and_controller_impostor_are_never_stopped(self):
        other=resource(id='cube',name='soma-kubecon-access-v2');fake=resource(id='fake',name='haunted-cooling-123');fake['spec']['args']='different-app.py'
        for row in (other,fake):self.rows[row['metadata']['id']]=row
        serverless.deploy({}, {},self.runtime,'shift')
        self.assertNotIn('stop',self.actions());self.assertEqual(other['status']['state'],'RUNNING')
        self.assertEqual(fake['status']['state'],'RUNNING')
    def test_one_running_controller_is_kept_and_only_older_game_copies_stop(self):
        for row in (resource(id='old',name='haunted-cooling-123'),resource(id='new',name='haunted-cooling-456')):self.rows[row['metadata']['id']]=row
        serverless.deploy({'endpoint':{'id':'new'}},{},self.runtime,'shift')
        self.assertEqual(self.rows['new']['status']['state'],'RUNNING');self.assertEqual(self.rows['old']['status']['state'],'STOPPED')
        self.assertNotIn('create',self.actions())
    def test_inflight_creation_reset_stops_the_new_resource(self):
        entered=threading.Event();resume=threading.Event();original=self.cli
        def slow(args):
            if args[2]=='create' and '--dry-run' not in args:entered.set();resume.wait(2)
            return original(args)
        with patch.object(serverless,'cli',side_effect=slow):
            worker=threading.Thread(target=serverless.deploy,args=({}, {},self.runtime,'old'));worker.start();self.assertTrue(entered.wait(2))
            cleanup=serverless.release(self.runtime,'old');resume.set();worker.join(2);cleanup.join(2)
        self.assertEqual(self.rows['aiendpoint-created']['status']['state'],'STOPPED')
    def test_failed_stop_is_visible_and_does_not_trigger_another_create(self):
        row=resource();self.rows[row['metadata']['id']]=row;serverless.deploy({}, {},self.runtime,'shift')
        original=self.cli
        def fail(args):
            if args[2]=='stop':raise ValueError('CPU stop failed; inspect console.')
            return original(args)
        with patch.object(serverless,'cli',side_effect=fail):serverless.release(self.runtime,'shift').join(2)
        self.assertIn('stop failed',serverless.pool_status(self.runtime)['cleanup_error']);self.assertNotIn('create',self.actions())
    def test_uncertain_creation_is_not_resubmitted_after_process_restart(self):
        serverless._write(self.runtime/'serverless/pending.json',{'name':'haunted-cooling-controller','project_id':PROJECT,'token':'private'})
        with self.assertRaisesRegex(ValueError,'no confirmed receipt'):serverless.deploy({}, {},self.runtime,'shift')
        self.assertNotIn('create',self.actions())
    def test_cpu_quota_error_is_actionable_and_redacts_cli_output(self):
        class Result:
            returncode=1;stderr='ResourceExhausted: Quota limit exceeded compute.instance.non-gpu.vcpu secret-token';stdout=''
        with patch.object(serverless.subprocess,'run',return_value=Result()),self.assertRaisesRegex(ValueError,'CPU quota is full') as error:
            # Bypass this fixture's cli mock to test the real wrapper.
            self.mock.temp_original(['ai','endpoint','create'])
        self.assertNotIn('secret-token',str(error.exception))

    def test_prewarm_without_an_existing_pool_never_allocates(self):
        serverless.prewarm(self.runtime,'early-player');self.assertEqual(self.calls,[])
    def test_prewarm_wakes_only_the_existing_current_app_and_claims_its_lease(self):
        row=resource(state='STOPPED',name=serverless.POOL_NAME);self.rows[row['metadata']['id']]=row
        serverless._remember({},row,self.runtime,'previous',shared=True);self.calls=[]
        serverless.prewarm(self.runtime,'early-player')
        self.assertEqual(self.actions(),['get','start'])
        pool=serverless._read(serverless._pool_path(self.runtime));self.assertIn('early-player',pool['leases']);self.assertEqual(pool['state'],'STARTING')
    def test_prewarm_does_not_trust_an_impostor_in_the_private_receipt(self):
        row=resource(state='STOPPED',name=serverless.POOL_NAME);self.rows[row['metadata']['id']]=row
        serverless._remember({},row,self.runtime,'previous',shared=True);self.rows[row['metadata']['id']]['spec']['args']='another-demo.py';self.calls=[]
        serverless.prewarm(self.runtime,'early-player');self.assertEqual(self.actions(),['get'])
        self.assertNotIn('early-player',serverless._read(serverless._pool_path(self.runtime))['leases'])
    def test_cancelled_shift_cannot_wake_a_controller(self):
        row=resource(state='STOPPED',name=serverless.POOL_NAME);self.rows[row['metadata']['id']]=row
        serverless._remember({},row,self.runtime,'previous',shared=True)
        with patch.object(serverless,'_cancelled',return_value=True):serverless.prewarm(self.runtime,'cancelled')
        self.assertEqual(self.calls,[])

class GameLifecycleTests(unittest.TestCase):
    def setUp(self):
        import server
        self.server=server;self.old=server.STATE;server.STATE=server.fresh()
    def tearDown(self):self.server.STATE=self.old
    def test_reset_releases_only_old_controller_and_keeps_a_fresh_incident(self):
        server=self.server;old=server.STATE['run_id'];server.STATE['noc']['submission']={'id':'keep-training-job'}
        server.STATE['plant']['endpoint']={'id':'only-controller'}
        with patch.object(serverless,'release') as release:
            server.Handler.action(None,'/api/host',{'action':'reset'})
        release.assert_called_once_with(server.RUNTIME,old,{'id':'only-controller'})
        self.assertNotEqual(server.STATE['run_id'],old);self.assertEqual(server.STATE['rooms'],[False]*3)
    def test_manual_escape_never_records_a_score_or_stops_controller(self):
        server=self.server;server.STATE['rooms']=[True,True,False]
        with patch.object(server.hosting,'record') as record,patch.object(serverless,'release') as release:
            with self.assertRaisesRegex(ValueError,'Only the caretaker'):server.Handler.action(None,'/api/plant/escape',{})
        record.assert_not_called();release.assert_not_called()

if __name__=='__main__':unittest.main()
