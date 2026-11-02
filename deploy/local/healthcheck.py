"""Container health checks use private environment credentials without printing them."""
import json, os, sys, urllib.request

service = sys.argv[1]
port = '8080' if service == 'web' else '8000'
token = os.environ.get('CARETAKER_WORKER_TOKEN' if service == 'worker' else 'SHARED_COOLING_TOKEN', '')
headers = {'Authorization': 'Bearer ' + token} if token else {}
with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:' + port + '/healthz', headers=headers), timeout=3) as response:
    data = json.load(response)
if not data.get('ready' if service != 'web' else 'ok'):
    raise SystemExit(1)
