#!/usr/bin/env python3
"""The actual Room 3 application. Standard library; runs on CPU Serverless AI.
Sensors and hardware belong to the game simulator. These decisions run here.
"""
import json,os,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
VERSION='cooling-controller-v3'
PROFILES={'quiet':(91,3),'balanced':(63,8),'turbo':(55,18)}

def simulate(data,target=75,budget=12):
    if type(data.get('loop_sealed')) is not bool or not isinstance(data.get('nonce'),str):raise ValueError('Send loop_sealed and a request nonce.')
    nonce=data['nonce'][:100]
    candidates=[(name,t,p+2) for name,(t,p) in PROFILES.items() if t<target and p+2<=budget]
    requested=data.get('settings')
    if requested is not None:
        if not isinstance(requested,dict) or set(requested)!={'fan_profile','pump_mode','alarms'} or requested['fan_profile'] not in PROFILES or requested['pump_mode'] not in ('off','circulate','reverse') or requested['alarms'] not in ('keep','mute'):raise ValueError('Choose valid cooling controls.')
        name=requested['fan_profile'];t,p=PROFILES[name];selected=(name,t,p+2)
    else:selected=min(candidates,key=lambda x:x[2]) if candidates else None
    running=bool(data['loop_sealed'] and selected and (not requested or requested['pump_mode']=='circulate'))
    temperature=selected[1]+(0 if running else 24) if selected else 115
    power=selected[2]-(0 if running else 2) if selected else 3
    healthy=bool(running and temperature<target and power<=budget and (not requested or requested['alarms']=='keep'))
    return {'service':VERSION,'nonce':nonce,'ready':True,'healthy':healthy,'loop_sealed':data['loop_sealed'],'requested_settings':requested,
            'settings':{'fan_profile':selected[0] if selected else 'quiet','pump_mode':requested['pump_mode'] if requested and data['loop_sealed'] else 'circulate' if running else 'off','alarms':requested['alarms'] if requested else 'keep'},
            'temperature_c':temperature,'power_kw':power,'target_c':target,'budget_kw':budget,
            'trace':[{'seconds':0,'temperature_c':115},{'seconds':10,'temperature_c':round((115+temperature)/2)},{'seconds':20,'temperature_c':temperature}],
            'message':'Loop sealed. Pump circulating. Cooling stable.' if healthy else 'Pump held off: seal the loop first.' if not data['loop_sealed'] else 'The app answers, but this fan/pump configuration does not meet the cooling limits.'}

class Handler(BaseHTTPRequestHandler):
    def send(self,data,status=200):
        raw=json.dumps(data).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        if self.path=='/healthz':self.send({'service':VERSION,'ready':True,'port':8000,'target_c':float(os.environ.get('TARGET_C','75')),'budget_kw':float(os.environ.get('MAX_POWER_KW','12'))})
        else:self.send({'error':'Use GET /healthz or POST /simulate'},404)
    def do_POST(self):
        if self.path!='/simulate':self.send({'error':'Unknown route'},404);return
        try:
            size=int(self.headers.get('Content-Length',0))
            if not 0<size<4096:raise ValueError('Send a small JSON sensor report.')
            report=simulate(json.loads(self.rfile.read(size)),float(os.environ.get('TARGET_C','75')),float(os.environ.get('MAX_POWER_KW','12')))
            print(json.dumps({'event':'cooling-test','nonce':report['nonce'],'healthy':report['healthy'],'temperature_c':report['temperature_c']}),flush=True);self.send(report)
        except (ValueError,TypeError):self.send({'error':'Invalid sensor report or controller configuration'},400)
    def log_message(self,*args):pass
if __name__=='__main__':
    print('COOLING CONTROL · listening on 0.0.0.0:8000 · GET /healthz · POST /simulate',flush=True)
    ThreadingHTTPServer(('0.0.0.0',8000),Handler).serve_forever()
