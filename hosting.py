"""Optional host tools and durable, server-recorded leaderboard results."""
import base64, hashlib, hmac, json, math, os, secrets, threading, time, uuid
from http.cookies import SimpleCookie, CookieError
from pathlib import Path

COOKIE = 'haunted_host'
SHIFT_SECONDS = 45 * 60
_attempts = {}
_lock = threading.Lock()

def hosted(): return os.environ.get('PUBLIC_DEPLOYMENT', '').lower() == 'true'
def requires_login(): return hosted() or bool(os.environ.get('HOST_ACCESS_CODE'))

def validate_config():
    if requires_login():
        if len(os.environ.get('HOST_ACCESS_CODE', '')) < 12: raise ValueError('Set HOST_ACCESS_CODE to at least 12 characters.')
        if len(os.environ.get('SESSION_SECRET', '')) < 32: raise ValueError('Set SESSION_SECRET to at least 32 characters.')

def authenticated(headers):
    if not requires_login(): return True
    try:
        cookie = SimpleCookie(); cookie.load(headers.get('Cookie', ''))
        value, signature = cookie[COOKIE].value.split('.')
        expected = hmac.new(os.environ['SESSION_SECRET'].encode(), value.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature): return False
        data = json.loads(base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)))
        return data['purpose'] == 'host' and time.time() < data['expires']
    except (ValueError, KeyError, TypeError, CookieError): return False

def login(code, address):
    validate_config(); now = time.time()
    with _lock:
        for key in list(_attempts):
            if _attempts[key][0] < now - 60: del _attempts[key]
        attempts = _attempts.setdefault(address, [now, 0])
        if attempts[1] >= 6: raise ValueError('Too many attempts. Wait one minute and try again.')
        attempts[1] += 1
    if not hmac.compare_digest(str(code), os.environ.get('HOST_ACCESS_CODE', '')): raise ValueError('That host code did not match.')
    value = base64.urlsafe_b64encode(json.dumps({'purpose':'host', 'expires':now+12*3600, 'nonce':secrets.token_hex(12)}).encode()).decode().rstrip('=')
    signature = hmac.new(os.environ['SESSION_SECRET'].encode(), value.encode(), hashlib.sha256).hexdigest()
    return f'{COOKIE}={value}.{signature}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200' + ('; Secure' if hosted() else '')

def player_name(value):
    value = str(value).strip()
    if not 1 <= len(value) <= 40 or any(ord(c) < 32 or ord(c) == 127 for c in value): raise ValueError('Use a display name between 1 and 40 characters.')
    return value

def initialize(state):
    state.setdefault('run_id', str(uuid.uuid4()))
    state.setdefault('player_name', 'Night shift' if state.get('started') else '')
    state.setdefault('practice_reasons', [])
    return state

def clock(state, now=None):
    """Saved pauses count; time spent away from an unpaused game still elapses."""
    now = time.time() if now is None else now
    started = state.get('started')
    end = state.get('finished') or (state.get('pause_at') if state.get('paused') else now)
    elapsed = max(0, (end or now) - started - state.get('pause_total', 0)) if started else 0
    remaining = max(0, SHIFT_SECONDS - elapsed)
    expired = bool(started and not state.get('escaped') and remaining == 0)
    return {'remaining_seconds':remaining, 'expired':expired,
            'resumable':bool(started and not state.get('finished') and not state.get('escaped') and not expired)}

def practice(state, reason):
    initialize(state)
    if reason not in state['practice_reasons']: state['practice_reasons'].append(reason)

def record(state, runtime):
    """Called only by the final exit after the server-side game gates pass."""
    initialize(state)
    if not state.get('escaped') or state.get('rooms') != [True, True, True]: return None
    started, finished = state.get('started'), state.get('finished')
    if not started or not finished or not math.isfinite(finished-started) or finished <= started: return None
    n=state['noc']; job=n.get('submission') or {}; active=n.get('job') or {}; reasons=list(state['practice_reasons'])
    evidence = state.get('evidence') == 'tavily' and (state.get('board_citation') or {}).get('kind') == 'tavily-extract'
    trained = job.get('status') == 'succeeded' and job.get('id') and active.get('id') == job['id'] and not n.get('host_override')
    tested = (n.get('final') or {}).get('passed') and (state['plant'].get('report') or {}).get('passed') and (state['plant'].get('endpoint') or {}).get('id')
    if not evidence: reasons.append('Archived research')
    if not trained: reasons.append('Prepared model or host experiment')
    if not tested: reasons.append('Missing live release checks')
    result={'run_id':state['run_id'], 'name':player_name(state['player_name'] or 'Night shift'), 'elapsed_seconds':round(finished-started,3), 'finished_at':finished, 'ranked':not reasons, 'practice_reasons':sorted(set(reasons))}
    folder=Path(runtime)/'scores';folder.mkdir(parents=True,exist_ok=True)
    destination=folder/(str(uuid.UUID(state['run_id']))+'.json')
    if not destination.exists():
        temp=destination.with_suffix('.tmp');temp.write_text(json.dumps(result));temp.chmod(0o600);temp.replace(destination)
    return json.loads(destination.read_text())

def leaderboard(runtime):
    rows=[]
    for path in (Path(runtime)/'scores').glob('*.json'):
        try:
            row=json.loads(path.read_text())
            if row['ranked'] and math.isfinite(row['elapsed_seconds']) and row['elapsed_seconds'] > 0: rows.append({k:row[k] for k in ('run_id','name','elapsed_seconds','finished_at')})
        except (OSError,ValueError,KeyError,TypeError): continue
    rows.sort(key=lambda r:(r['elapsed_seconds'],r['finished_at'],r['run_id']))
    return [{**row,'rank':i+1} for i,row in enumerate(rows[:25])]

_new_shifts={}
def allow_new_shift(address):
    now=time.time()
    with _lock:
        for key in list(_new_shifts):
            _new_shifts[key]=[t for t in _new_shifts[key] if now-t<3600]
            if not _new_shifts[key]:del _new_shifts[key]
        times=_new_shifts.setdefault(address,[])
        if len(times)>=30:raise ValueError('Too many new shifts from this connection. Resume an existing UUID or try again later.')
        times.append(now)
