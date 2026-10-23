"""Fetch the game's public clue with Tavily. A local draft is rehearsal-only."""
import html,json,os,re,subprocess
from pathlib import Path
from urllib.parse import urlparse
import switchboard

TITLE='Mabel’s midnight subscriber migration'
POST=Path(__file__).resolve().parent/'web'/'mabel-post.html'

def public_url():return os.environ.get('MABEL_POST_URL','').strip()

def saved_post():
 """An authored game object, never presented as a Tavily result."""
 text=re.sub(r'<style>.*?</style>','',POST.read_text(),flags=re.S)
 text=html.unescape(re.sub(r'<[^>]+>',' ',text));text=' '.join(text.split())
 return {'title':TITLE,'url':'/mabel-post.html','content':text,'topic':switchboard.DOOR_TOPIC,'kind':'saved-post'}

def article():
 return re.sub(r'<h1>.*?</h1>','',POST.read_text().split('<article>',1)[1].split('</article>',1)[0],flags=re.S)

def retrieve(archived=False,mode='live'):
 if archived:
  if mode!='rehearsal':raise ValueError('Live mode requires Tavily to fetch the public post.')
  text=re.sub(r'<style>.*?</style>','',POST.read_text(),flags=re.S)
  text=html.unescape(re.sub(r'<[^>]+>',' ',text));text=' '.join(text.split())
  return {'title':TITLE,'url':'/mabel-post.html','content':text,'topic':switchboard.DOOR_TOPIC,'kind':'rehearsal'}
 url=public_url();p=urlparse(url)
 if p.scheme!='https' or not p.hostname or p.username or p.password:raise ValueError('The clue post is not published yet. Set MABEL_POST_URL to its public HTTPS URL, or use the marked rehearsal draft.')
 result=subprocess.run(['tvly','extract',url,'--json'],capture_output=True,text=True,timeout=40)
 if result.returncode:raise ValueError('Tavily could not fetch Mabel’s post. Check CLI authentication and the public URL.')
 data=json.loads(result.stdout)
 source=next((x for x in data.get('results',[]) if x.get('url','').rstrip('/')==url.rstrip('/')),None)
 text=(source or {}).get('raw_content','')
 match=re.search(r'Door\s+latch\s+topic\s*:\s*[`\"\s]*([\w/-]+)',text,re.I)
 if not match or match.group(1)!=switchboard.DOOR_TOPIC:raise ValueError('The fetched post does not contain this incident’s door-latch topic. Check the published clue draft.')
 return {'title':TITLE,'url':url,'content':text[:12000],'topic':match.group(1),'kind':'tavily-extract'}
