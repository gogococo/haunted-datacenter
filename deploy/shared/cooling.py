"""Authenticated shared-host binding for the same Room 3 controller."""
import collections,hmac,json,os,sys
sys.path.insert(0,'/app')
from cloud_controller import Handler,ThreadingHTTPServer
LINES=collections.deque(maxlen=40)
class SharedController(Handler):
    def authorized(self):return hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+os.environ['SHARED_COOLING_TOKEN'])
    def send(self,data,status=200):
        if isinstance(data,dict) and 'nonce' in data:
            LINES.append(json.dumps({k:data[k] for k in ('nonce','healthy','temperature_c','power_kw') if k in data}))
        super().send(data,status)
    def do_GET(self):
        if not self.authorized():self.send({'error':'Unauthorized'},401);return
        if self.path=='/logs':self.send({'lines':list(LINES)});return
        super().do_GET()
    def do_POST(self):
        if not self.authorized():self.send({'error':'Unauthorized'},401);return
        super().do_POST()
if __name__=='__main__':ThreadingHTTPServer(('0.0.0.0',8000),SharedController).serve_forever()
