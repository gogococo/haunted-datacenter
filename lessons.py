"""Camera evidence → sandbox demonstration → real input/output training record."""
import copy,json,hashlib,time
import content
NOTES={
 'west':{'title':'Fan controller · Alex’s service sticker','text':'Fans stopped and rack getting hot? Restart the fan controller. Opening a door is not airflow management. We established this on Tuesday.','action':'restart_fans','equipment':'gpu_rack'},
 'east':{'title':'Cooling pump · Alex’s service sticker','text':'If it is leaking, stop the coolant pump FIRST. A faster pump makes a faster puddle. Please stop testing this theory.','action':'stop_pump','equipment':'cooling_loop'},
 'crypt':{'title':'Exit latch · Alex’s service sticker','text':'A stuck exit latch needs the release-latch command sent to the exit door. The controller accepts action + equipment JSON. It does not accept compliments.','action':'release_latch','equipment':'exit_door'},
}
ROWS={'west':1,'east':4,'crypt':8}

def complete(n):return set(n.get('lessons',{}))==set(NOTES)

def packet_hash(n,source):
    return hashlib.sha256(json.dumps({'source':source,'lessons':n.get('lessons',{})},sort_keys=True).encode()).hexdigest()

def evidence(n,camera):
    if camera not in NOTES:raise ValueError('Choose a camera.')
    n.setdefault('maintenance',{})[camera]=True
    return NOTES[camera]

def rehearse(n,camera,action):
    if camera not in NOTES or action not in content.ACTIONS:raise ValueError('Use one of the rehearsal controls.')
    if not n.get('observations',{}).get(camera,{}).get('reviewed'):raise ValueError('Describe this camera with vision and ask the caretaker first.')
    expected=NOTES[camera];correct=action==expected['action']
    outcome={'west':'The fan spins. The rack temperature starts falling.','east':'The pump stops. The puddle stops growing.','crypt':'The rehearsal latch clicks open.'}[camera] if correct else 'That control moved, but the camera fault remains. Inspect the service sticker and try another repair.'
    n.setdefault('demonstrations',{})[camera]={'action':action,'equipment':expected['equipment'],'correct':correct,'outcome':outcome,'by':'player'}
    return outcome

def record(n,camera,source):
    if n.get('submission'):raise ValueError('This pack has already been submitted. Review its examples at the training desk.')
    if camera not in NOTES:raise ValueError('Choose a camera.')
    o=n.get('observations',{}).get(camera,{});demo=n.get('demonstrations',{}).get(camera,{})
    if not o.get('reviewed') or camera not in n.get('probes',{}) or not n.get('maintenance',{}).get(camera):raise ValueError('Inspect the camera, read its service sticker, and compare the caretaker’s reply before recording.')
    if not demo.get('correct') or demo.get('by')!='player':raise ValueError('Demonstrate a repair that fixes this rehearsal first.')
    rows=[json.loads(line) for line in source.splitlines() if line.strip()]
    rows[ROWS[camera]]=copy.deepcopy(content.clean_records()[ROWS[camera]])
    answer={k:demo[k] for k in ('action','equipment')}
    n.setdefault('lessons',{})[camera]={'observation':o['observation'],'input':o['request'],'answer':answer,'camera_request_id':o['inference'].get('request_id'),'recorded_at':time.time()}
    n['report']=None;n.pop('final',None)
    return '\n'.join(json.dumps(r) for r in rows)

def write_pack(n,source,folder):
    if not complete(n):raise ValueError('Record all three camera rehearsals before submitting training.')
    counts=content.write_datasets(source,folder)
    with (folder/'train.jsonl').open('a') as f:
        for lesson in n['lessons'].values():f.write(json.dumps(content.record(lesson['input'],lesson['answer']))+'\n')
    counts['train']+=len(n['lessons']);counts['recorded_demonstrations']=len(n['lessons'])
    return counts

def try_probe(n,camera):
    probe=n.get('probes',{}).get(camera)
    if not probe or camera not in NOTES:raise ValueError('Ask the caretaker about this camera first.')
    try:answer=json.loads(probe['output'])
    except (ValueError,TypeError):answer=None
    shape=isinstance(answer,dict) and set(answer)=={'action','equipment'} and all(isinstance(v,str) for v in answer.values())
    readable=shape and probe.get('finish_reason')=='stop' and answer['action'] in content.ACTIONS and answer['equipment'] in content.EQUIPMENT
    correct=bool(readable and all(answer[k]==NOTES[camera][k] for k in ('action','equipment')))
    outcome='The rehearsal controller accepts the command. The fault clears.' if correct else 'Controller rejected the command packet. The fault remains.' if not readable else 'The controller ran that command, but this fault remains. Check its action and destination.'
    n.setdefault('demonstrations',{})[camera]={'action':answer.get('action','') if shape else '', 'equipment':answer.get('equipment','') if shape else '', 'correct':correct,'by':'caretaker','outcome':outcome}
    return outcome
