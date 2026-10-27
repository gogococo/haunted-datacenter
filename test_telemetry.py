import concurrent.futures, copy, json, os, sqlite3, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
import telemetry, server

class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.state=server.fresh();self.state.update(started=100,player_name='PRIVATE NAME')
        self.clock=patch.object(telemetry.time,'time',return_value=110);self.clock.start()
    def tearDown(self):self.clock.stop();self.temp.cleanup()
    def rows(self):
        with telemetry.connect(self.root) as db:return [json.loads(r[0]) for r in db.execute('SELECT payload FROM events ORDER BY at,rowid')]
    def test_default_is_local_only_and_key_never_exposed_in_status(self):
        self.assertFalse(telemetry.status(self.root)['enabled'])
        telemetry.configure(self.root,{'enabled':True,'region':'us','key':'phc_testing_public_token','project_url':'https://us.posthog.com/project/1'})
        status=telemetry.status(self.root);self.assertTrue(status['configured']);self.assertNotIn('key',status)
        with self.assertRaises(ValueError):telemetry.configure(self.root,{'enabled':True,'region':'private','key':'phc_testing_public_token'})
        with self.assertRaises(ValueError):telemetry.configure(self.root,{'enabled':True,'region':'us','project_url':'http://localhost/'})
    def test_events_are_anonymous_and_whitelisted(self):
        original=copy.deepcopy(self.state)
        self.state['sources']['dataset']='PRIVATE MODEL DATA'
        self.state['terminal_history']=[{'command':'SECRET COMMAND'}]
        telemetry.observe(self.root,self.state,new=True,visitor='33333333-3333-4333-8333-333333333333')
        telemetry.action(self.root,self.state,'/api/search',{'query':'PRIVATE SEARCH'},rejected=True)
        text=json.dumps(self.rows())
        for secret in (self.state['run_id'],'PRIVATE NAME','PRIVATE MODEL DATA','SECRET COMMAND','PRIVATE SEARCH','33333333-3333-4333-8333-333333333333'):self.assertNotIn(secret,text)
        self.assertFalse(self.rows()[0]['properties']['$process_person_profile'])
        self.assertEqual(self.state['rooms'],original['rooms'])
    def test_room_times_include_elapsed_and_visible_activity_without_duplicates(self):
        telemetry.observe(self.root,self.state,new=True)
        telemetry.activity(self.root,self.state,'1','speaker',True)
        with patch.object(telemetry.time,'time',return_value=130):telemetry.activity(self.root,self.state,'1','speaker',True)
        with patch.object(telemetry.time,'time',return_value=140):
            self.state['rooms'][0]=True;telemetry.observe(self.root,self.state);telemetry.observe(self.root,self.state)
        rows=[r for r in self.rows() if r['event']=='haunted_room_completed'];self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['properties']['elapsed_seconds'],30);self.assertEqual(rows[0]['properties']['active_seconds'],30)
    def test_offline_gap_is_not_counted_as_active_room_time(self):
        telemetry.activity(self.root,self.state,'2',visible=True)
        with patch.object(telemetry.time,'time',return_value=1000):telemetry.activity(self.root,self.state,'2',visible=True)
        self.state['rooms'][1]=True;telemetry.observe(self.root,self.state)
        self.assertEqual([r for r in self.rows() if r['event']=='haunted_room_completed'][0]['properties']['active_seconds'],0)
    def test_attempts_and_expiry_are_recorded_once(self):
        telemetry.observe(self.root,self.state,new=True)
        telemetry.attempt(self.root,self.state,'speaker',False);telemetry.attempt(self.root,self.state,'speaker',True);telemetry.attempt(self.root,self.state,'speaker',True)
        complete=[r for r in self.rows() if r['event']=='haunted_step_completed'];self.assertEqual(len(complete),1);self.assertEqual(complete[0]['properties']['attempts'],2)
        with patch.object(telemetry.time,'time',return_value=3000):telemetry.observe(self.root,self.state);telemetry.observe(self.root,self.state)
        self.assertEqual(sum(r['event']=='haunted_shift_expired' for r in self.rows()),1)
    def test_legacy_completion_does_not_invent_room_timings_or_new_start(self):
        self.state.update(rooms=[True]*3,escaped=True,finished=105)
        telemetry.observe(self.root,self.state)
        self.assertEqual([r['event'] for r in self.rows()],['haunted_shift_observed'])
    def test_debug_preview_does_not_record_a_game(self):
        telemetry.observe(self.root,server.fresh())
        with telemetry.connect(self.root) as db:self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],0)
    def test_identical_browser_can_start_two_distinct_games(self):
        visitor='33333333-3333-4333-8333-333333333333'
        telemetry.observe(self.root,self.state,new=True,visitor=visitor)
        other=copy.deepcopy(self.state);other['run_id']='44444444-4444-4444-8444-444444444444';telemetry.observe(self.root,other,new=True,visitor=visitor)
        rows=self.rows();self.assertEqual(rows[0]['properties']['distinct_id'],rows[1]['properties']['distinct_id']);self.assertNotEqual(rows[0]['properties']['game_id'],rows[1]['properties']['game_id'])
    def test_flush_failure_retains_event_and_retries_same_uuid(self):
        telemetry.configure(self.root,{'enabled':True,'region':'us','key':'phc_testing_public_token'})
        telemetry.observe(self.root,self.state,new=True);id=self.rows()[0]['uuid']
        with patch.object(telemetry,'urlopen',side_effect=OSError('offline')):telemetry.flush(self.root)
        self.assertEqual(telemetry.status(self.root)['pending_events'],1)
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with patch.object(telemetry,'urlopen',return_value=Response()) as send:
            telemetry.flush(self.root);request=send.call_args.args[0]
            self.assertEqual(request.full_url,'https://us.i.posthog.com/batch/')
            self.assertEqual(json.loads(request.data)['batch'][0]['uuid'],id)
        self.assertEqual(telemetry.status(self.root)['pending_events'],0)
    def test_storage_failure_does_not_break_game_actions(self):
        with patch.object(telemetry,'connect',side_effect=OSError('disk')):
            telemetry.observe(self.root,self.state,new=True);telemetry.action(self.root,self.state,'/api/search',{})
    def test_concurrent_players_have_separate_attempt_counts(self):
        def player(i):
            s=copy.deepcopy(self.state);s['run_id']=str(i);telemetry.observe(self.root,s,new=True)
            telemetry.attempt(self.root,s,'speaker',False);telemetry.attempt(self.root,s,'speaker',True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as workers:list(workers.map(player,range(12)))
        completed=[r for r in self.rows() if r['event']=='haunted_step_completed'];self.assertEqual(len(completed),12);self.assertTrue(all(r['properties']['attempts']==2 for r in completed))

if __name__=='__main__':unittest.main()
