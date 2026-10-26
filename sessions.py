"""UUID bearer saves. Each game owns its state, lock and private artifact folder."""
import contextlib,contextvars,json,secrets,threading,time,uuid
from pathlib import Path

CURRENT=contextvars.ContextVar('haunted_game',default=None)
ADMIN=contextvars.ContextVar('haunted_admin',default=True)
_cache={}
_cache_lock=threading.RLock()

def identifier(value):
    try:
        parsed=uuid.UUID(str(value))
        if parsed.version!=4 or str(parsed)!=str(value).lower():raise ValueError()
        return str(parsed)
    except (ValueError,TypeError,AttributeError):raise ValueError('Use the UUID from your saved shift link.') from None

def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value));temp.chmod(0o600);temp.replace(path)

class Game:
    def __init__(self,root,state,token):
        self.root=Path(root);self.state=state;self.token=token;self.lock=threading.RLock()
        self.runtime=self.root/'runs'/identifier(state['run_id'])

@contextlib.contextmanager
def scope(game,admin=False):
    token=CURRENT.set(game);host=ADMIN.set(admin)
    try:yield
    finally:CURRENT.reset(token);ADMIN.reset(host)

def create(root,factory,name='',start=False):
    with _cache_lock:
        state=factory();state['player_name']=name
        if start:state['started']=time.time()
        game=Game(root,state,secrets.token_urlsafe(24))
        write(game.runtime/'access.json',{'token':game.token})
        write(game.runtime/'state.json',state)
        _cache[(str(Path(root).resolve()),state['run_id'])]=game
        return game

def get(root,value):
    id=identifier(value);key=(str(Path(root).resolve()),id)
    with _cache_lock:
        if key in _cache:return _cache[key]
        folder=Path(root)/'runs'/id
        try:
            state=json.loads((folder/'state.json').read_text());token=json.loads((folder/'access.json').read_text())['token']
            if state['run_id']!=id or not isinstance(token,str):raise ValueError()
        except (OSError,ValueError,KeyError):raise ValueError('That saved shift was not found. Check your UUID or start a new shift.') from None
        for area in ('noc','plant'):
            op=state.get(area,{}).get('operation') or {}
            if op.get('status')=='running':
                op.update(status='interrupted',message='The app restarted during this request. Refresh its cloud status before retrying.')
                state[area]['revision']=state[area].get('revision',0)+1
        game=Game(root,state,token);_cache[key]=game;return game
