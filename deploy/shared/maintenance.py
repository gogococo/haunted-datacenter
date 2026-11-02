"""Private migration control. Fixed backup roots; no shell or arbitrary file access."""
import hashlib,hmac,json,os,pathlib,shutil,sqlite3,tarfile,tempfile,threading,time,urllib.parse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOTS={'haunted':pathlib.Path('/mnt/persist'),'soma':pathlib.Path('/mnt/soma')}
TARGET=pathlib.Path('/tmp/migration-backups');TARGET.mkdir(exist_ok=True,mode=0o700)
JOBS={};LOCK=threading.Lock()
def make_backup(name):
    try:
        root=ROOTS[name];dest=TARGET/(name+'.tar.gz');manifest=[]
        with tempfile.TemporaryDirectory(prefix='consistent-sqlite-') as staging,tarfile.open(dest,'w:gz',compresslevel=1) as archive:
            for path in sorted(root.rglob('*')):
                if not path.is_file() or path.is_symlink() or 'shared-host' in path.relative_to(root).parts:continue
                rel=path.relative_to(root).as_posix()
                if rel.endswith(('-wal','-shm')):continue
                try:
                    with path.open('rb') as f:magic=f.read(16)
                    selected=pathlib.Path(staging)/hashlib.sha256(rel.encode()).hexdigest()
                    if magic==b'SQLite format 3\x00':
                        with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as db,sqlite3.connect(selected) as snapshot:
                            db.backup(snapshot)
                            if snapshot.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('SQLite backup failed integrity check')
                    else:shutil.copy2(path,selected)
                    digest=hashlib.sha256()
                    with selected.open('rb') as f:
                        for chunk in iter(lambda:f.read(1024*1024),b''):digest.update(chunk)
                    archive.add(selected,arcname=name+'/'+rel,recursive=False)
                    manifest.append({'path':rel,'size':selected.stat().st_size,'sha256':digest.hexdigest()})
                    selected.unlink()
                except FileNotFoundError:continue  # Atomic replacement during an online snapshot.
        checksum=hashlib.sha256()
        with dest.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):checksum.update(chunk)
        meta={'status':'ready','files':len(manifest),'bytes':dest.stat().st_size,'sha256':checksum.hexdigest(),'manifest':manifest}
        (TARGET/(name+'.json')).write_text(json.dumps(meta));dest.chmod(0o600)
        JOBS[name]=meta
    except Exception as error:JOBS[name]={'status':'failed','error':type(error).__name__}
class Handler(BaseHTTPRequestHandler):
    def json(self,data,status=200):
        raw=json.dumps(data).encode();self.send_response(status);self.send_header('Content-Length',str(len(raw)));self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
    def authorized(self):return bool(os.environ.get('TOKEN') and hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+os.environ['TOKEN']))
    def do_GET(self):
        if not self.authorized():self.json({'error':'Unauthorized'},401);return
        name=self.path.removeprefix('/backup/').split('.')[0]
        if self.path=='/healthz':
            memory=pathlib.Path('/proc/meminfo').read_text().splitlines() if pathlib.Path('/proc/meminfo').exists() else []
            self.json({'ok':True,'active':pathlib.Path(os.environ['ACTIVATION_FILE']).exists(),'memory':[v for v in memory if v.startswith(('MemTotal:','MemAvailable:'))]});return
        if name not in ROOTS:self.json({'error':'Not found'},404);return
        job=JOBS.get(name,{})
        if self.path.endswith('.tar.gz'):
            if job.get('status')!='ready':self.json({'error':'Backup not ready'},409);return
            path=TARGET/(name+'.tar.gz');self.send_response(200);self.send_header('Content-Length',str(path.stat().st_size));self.send_header('Content-Type','application/gzip');self.end_headers()
            with path.open('rb') as f:shutil.copyfileobj(f,self.wfile)
        else:self.json(job)
    def do_POST(self):
        if not self.authorized():self.json({'error':'Unauthorized'},401);return
        if self.path.startswith('/backup/'):
            name=self.path.removeprefix('/backup/')
            if name not in ROOTS:self.json({'error':'Not found'},404);return
            with LOCK:
                if JOBS.get(name,{}).get('status') in ('running','ready'):self.json({'status':JOBS[name]['status']});return
                JOBS[name]={'status':'running'};threading.Thread(target=make_backup,args=(name,),daemon=True).start()
            self.json({'status':'running'},202);return
        if self.path=='/activate':
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<4096:self.json({'error':'Invalid activation'},400);return
            cfg=json.loads(self.rfile.read(size))
            if set(cfg)!={'endpoint_id','name','cooling_url','worker_url'}:self.json({'error':'Invalid activation'},400);return
            for key in ('cooling_url','worker_url'):
                p=urllib.parse.urlparse(cfg[key])
                if p.scheme!='https' or not (p.hostname or '').endswith('.nebius.cloud') or p.username or p.password:self.json({'error':'Invalid URL'},400);return
            if not all(JOBS.get(k,{}).get('status')=='ready' for k in ROOTS):self.json({'error':'Back up both volumes first'},409);return
            path=pathlib.Path(os.environ['ACTIVATION_FILE']);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(cfg));tmp.chmod(0o600);tmp.replace(path)
            self.json({'activated':True});return
        self.json({'error':'Not found'},404)
    def log_message(self,*args):pass
if __name__=='__main__':ThreadingHTTPServer(('0.0.0.0',9000),Handler).serve_forever()
