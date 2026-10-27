import copy, json, os, tempfile, threading, unittest, urllib.error, urllib.request
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import hosting, server

class ClockTests(unittest.TestCase):
    def test_resume_stops_at_exactly_45_minutes(self):
        state={'started':100}
        self.assertTrue(hosting.clock(state,2799)['resumable'])
        self.assertEqual(hosting.clock(state,2799)['remaining_seconds'],1)
        self.assertTrue(hosting.clock(state,2800)['expired'])
        self.assertFalse(hosting.clock(state,2800)['resumable'])
    def test_saved_pause_does_not_expire_while_away(self):
        state={'started':100,'paused':True,'pause_at':160,'pause_total':20}
        self.assertEqual(hosting.clock(state,10000)['remaining_seconds'],2660)
        self.assertTrue(hosting.clock(state,10000)['resumable'])
    def test_finished_game_cannot_resume_but_keeps_its_ending(self):
        result=hosting.clock({'started':100,'finished':200,'escaped':True},10000)
        self.assertFalse(result['resumable']);self.assertFalse(result['expired'])
    def test_unstarted_game_has_the_full_timer(self):
        result=hosting.clock({},10000)
        self.assertEqual(result['remaining_seconds'],2700)
        self.assertFalse(result['resumable']);self.assertFalse(result['expired'])

class ResultTests(unittest.TestCase):
    def state(self):
        s=server.fresh();s.update(escaped=True,rooms=[True]*3,player_name='Mabel',started=100,finished=160,evidence='tavily',board_citation={'kind':'tavily-extract'})
        s['noc'].update(submission={'id':'own-job','status':'succeeded'},job={'id':'own-job'},final={'passed':True})
        s['plant'].update(endpoint={'id':'own-endpoint'},report={'passed':True});return s
    def test_results_persist_and_are_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            s=self.state();one=hosting.record(s,d);s['finished']=999;two=hosting.record(s,d)
            self.assertEqual(one,two);self.assertEqual(hosting.leaderboard(Path(d))[0]['elapsed_seconds'],60)
            self.assertEqual(len(list((Path(d)/'scores').glob('*.json'))),1)
            self.assertNotIn('noc',hosting.leaderboard(d)[0])
            self.assertNotIn('run_id',hosting.leaderboard(d)[0])
            self.assertNotIn(s['run_id'],json.dumps(hosting.leaderboard(d)))
    def test_unfinished_and_forged_runs_do_not_rank(self):
        with tempfile.TemporaryDirectory() as d:
            s=self.state();s['rooms'][1]=False;self.assertIsNone(hosting.record(s,d))
            s=self.state();s['noc']['job']['id']='someone-elses-job';self.assertFalse(hosting.record(s,d)['ranked'])
            self.assertEqual(hosting.leaderboard(d),[])
    def test_pause_and_shortcuts_are_practice(self):
        for reason in ['Timer paused','Host solution used','Host model experiment']:
            with tempfile.TemporaryDirectory() as d:
                s=self.state();hosting.practice(s,reason);self.assertFalse(hosting.record(s,d)['ranked']);self.assertEqual(hosting.leaderboard(d),[])
    def test_new_runs_have_independent_ids_and_do_not_clear_scores(self):
        with tempfile.TemporaryDirectory() as d:
            hosting.record(self.state(),d);self.assertNotEqual(server.fresh()['run_id'],server.fresh()['run_id']);self.assertEqual(len(hosting.leaderboard(d)),1)
    def test_display_names_are_bounded(self):
        for bad in ['', ' '*3, 'x'*41, 'bad\nname']:
            with self.assertRaises(ValueError):hosting.player_name(bad)

class HostedHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old_runtime=server.RUNTIME;self.old_state=server.STATE
        server.RUNTIME=Path(self.temp.name);server.STATE=server.fresh();hosting._attempts.clear()
        self.env=patch.dict(os.environ,{'PUBLIC_DEPLOYMENT':'true','HOST_ACCESS_CODE':'test-host-access-code','SESSION_SECRET':'test-session-secret-with-at-least-32-characters'});self.env.start()
        self.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler);self.base=f'http://127.0.0.1:{self.http.server_port}'
        threading.Thread(target=self.http.serve_forever,daemon=True).start()
    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.env.stop();server.RUNTIME=self.old_runtime;server.STATE=self.old_state;self.temp.cleanup()
    def request(self,path,body=None,cookie=None):
        headers={'Content-Type':'application/json','X-Game-Token':server.TOKEN}
        if cookie:headers['Cookie']=cookie
        req=urllib.request.Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        with urllib.request.urlopen(req) as r:return json.load(r),dict(r.headers)
    def login(self):return self.request('/api/login',{'code':'test-host-access-code'})[1]['Set-Cookie'].split(';')[0]
    def test_host_cookie_selects_original_save_without_a_uuid(self):
        data,_=self.request('/api/state');self.assertFalse(data['has_session']);self.assertFalse(data['is_host'])
        with self.assertRaises(urllib.error.HTTPError) as e:self.request('/api/start',{'name':'Alex'})
        self.assertEqual(e.exception.code,401)
        cookie=self.login();data,_=self.request('/api/state',cookie=cookie);self.assertTrue(data['authenticated'])
        data,_=self.request('/api/start',{'name':'Alex'},cookie);self.assertEqual(data['state']['player_name'],'Alex')
    def test_forged_cookie_and_legacy_execution_are_rejected(self):
        self.assertFalse(self.request('/api/state',cookie='haunted_host=forged.bad')[0]['is_host'])
        with self.assertRaises(urllib.error.HTTPError) as e:self.request('/api/check',{'kind':'retry','source':'raise Exception()'},self.login())
        self.assertEqual(e.exception.code,403)
    def test_public_leaderboard_does_not_expose_control_state(self):
        self.assertEqual(self.request('/api/leaderboard')[0],{'entries':[]})
    def test_malformed_login_body_does_not_start_a_run(self):
        with self.assertRaises(urllib.error.HTTPError) as e:self.request('/api/login',[])
        self.assertEqual(e.exception.code,401);self.assertIsNone(server.STATE['started'])
    def test_login_cookie_is_secure_and_expired_cookie_fails(self):
        _,headers=self.request('/api/login',{'code':'test-host-access-code'});cookie=headers['Set-Cookie']
        for attribute in ['HttpOnly','Secure','SameSite=Strict']:self.assertIn(attribute,cookie)
        with patch.object(hosting.time,'time',return_value=hosting.time.time()+13*3600):self.assertFalse(hosting.authenticated({'Cookie':cookie.split(';')[0]}))

if __name__=='__main__':unittest.main()
