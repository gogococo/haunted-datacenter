"""Camera evidence → sandbox demonstration → real input/output training record."""
import copy,json,hashlib,time
import content
NOTES={
 'west':{'title':'Fan controller · Alex’s service sticker','text':'Fans stopped and rack getting hot? Restart the fan controller. Opening a door is not airflow management. We established this on Tuesday.','action':'restart_fans','equipment':'gpu_rack'},
 'east':{'title':'Cooling pump · Alex’s service sticker','text':'If it is leaking, stop the coolant pump FIRST. A faster pump makes a faster puddle. Please stop testing this theory.','action':'stop_pump','equipment':'cooling_loop'},
 'crypt':{'title':'Exit latch · Alex’s service sticker','text':'A stuck exit latch needs the release-latch command sent to the exit door. The controller accepts action + equipment JSON. It does not accept compliments.','action':'release_latch','equipment':'exit_door'},
}
ROWS={'west':1,'east':4,'crypt':8}

NEW_NOTES={
 'east':{**NOTES['east'],'lesson':'Bad examples teach bad repairs','old_action':'restart_pump','old_answer':'{"action":"restart_pump","equipment":"cooling_loop"}','bad_outcome':'The pump speeds up. The puddle grows. Edgar has returned wearing wellies.','choices':['stop_pump','restart_pump']},
 'healthy':{'title':'Fan controller · Tuesday’s correction','text':'Green status, spinning fans and a cool rack mean HEALTHY. Leave working equipment alone. Working equipment is also a possible equipment state. —Alex','action':'leave_alone','equipment':'gpu_rack','lesson':'Teach when NOT to act','old_action':'restart_fans','old_answer':'{"action":"restart_fans","equipment":"gpu_rack"}','bad_outcome':'He restarts a perfectly healthy fan controller. The fan stops. “I have improved it.” No, he has not.','choices':['leave_alone','restart_fans']},
 'crypt':{**NOTES['crypt'],'lesson':'Useful commands need a usable format','old_action':'chat','old_answer':'Certainly! Opening the door now, valued mortal.','bad_outcome':'The door displays: COMPLIMENT RECEIVED. LATCH STILL LOCKED.','choices':['release_latch','chat']},
}
def catalog(n):return NEW_NOTES if n.get('flow_version',2)>=3 else NOTES
def complete(n):return set(n.get('lessons',{}))==set(catalog(n))

def packet_hash(n,source):
    return hashlib.sha256(json.dumps({'source':source,'lessons':n.get('lessons',{})},sort_keys=True).encode()).hexdigest()

def evidence(n,camera):
    if camera not in catalog(n):raise ValueError('Choose a camera.')
    n.setdefault('maintenance',{})[camera]=True
    return catalog(n)[camera]

def rehearse(n,camera,action):
    if camera not in catalog(n) or action not in (*content.ACTIONS,'leave_alone','restart_pump','chat'):raise ValueError('Use one of the rehearsal controls.')
    if not n.get('observations',{}).get(camera):raise ValueError('Describe this camera with vision and ask the caretaker first.')
    expected=catalog(n)[camera];correct=action==expected['action']
    outcome={'west':'The fan spins. The rack temperature starts falling.','east':'The pump stops. The puddle stops growing.','crypt':'The command is accepted. The rehearsal latch clicks open.','healthy':'You leave it alone. The fan keeps spinning; the rack stays cool.'}[camera] if correct else expected.get('bad_outcome','That control moved, but the camera fault remains. Inspect the service sticker and try another repair.')
    n.setdefault('demonstrations',{})[camera]={'action':action,'equipment':expected['equipment'],'correct':correct,'outcome':outcome,'by':'player'}
    return outcome

def record(n,camera,source):
    if n.get('submission'):raise ValueError('This pack has already been submitted. Review its examples at the training desk.')
    if camera not in catalog(n):raise ValueError('Choose a camera.')
    o=n.get('observations',{}).get(camera,{});demo=n.get('demonstrations',{}).get(camera,{})
    if (not o or not n.get('maintenance',{}).get(camera) or not n.get('tried_examples',{}).get(camera)) if n.get('flow_version',2)>=3 else (not o.get('reviewed') or camera not in n.get('probes',{}) or not n.get('maintenance',{}).get(camera)):raise ValueError('Inspect the camera, read its service sticker, and compare the caretaker’s reply before recording.')
    if not demo.get('correct') or demo.get('by')!='player':raise ValueError('Demonstrate a repair that fixes this rehearsal first.')
    rows=[json.loads(line) for line in source.splitlines() if line.strip()]
    index={'healthy':1}.get(camera,ROWS.get(camera));rows[index]=copy.deepcopy(content.clean_records()[index])
    if n.get('flow_version',2)>=3 and (o.get('equipment')!=catalog(n)[camera]['equipment'] or o.get('fault')!={'east':'coolant_leak','healthy':'healthy','crypt':'locked_door'}[camera]):raise ValueError('The vision report does not match the maintenance evidence. Inspect the camera again before saving.')
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
    if n.get('flow_version',2)>=3:
        for name in ('train','validation'):
            extra=curriculum(name)
            with (folder/(name+'.jsonl')).open('a') as f:
                for row in extra:f.write(json.dumps(row)+'\n')
            counts[name]+=len(extra)
    return counts

def try_example(n,camera):
    if camera not in catalog(n) or camera not in n.get('observations',{}):raise ValueError('Describe this camera with Token Factory vision first.')
    note=catalog(n)[camera];n.setdefault('tried_examples',{})[camera]=True
    n.setdefault('demonstrations',{})[camera]={'correct':False,'by':'alex','action':note['old_action'],'outcome':note['bad_outcome']}
    return note['bad_outcome']

def curriculum(split):
    # Healthy examples are new semantic cases, not repaired copies of faulty ones.
    healthy=[
      'The GPU rack is cool, its fans are spinning and all status indicators are green.',
      'Normal airflow and safe temperature at the GPU rack. No faults detected.',
      'The rack cooling system is running normally; there is nothing to repair.',
      'Fan controller online, blades turning, GPU temperature normal.',
      'Inspection confirms the GPU fans are operating correctly and the temperature is safe.',
      'The GPU rack is functioning as intended, with cooling fans running and no warning lights.',
    ]
    rows=[]
    chosen=healthy[:4] if split=='train' else healthy[4:]
    for report in chosen:
      for prefix in (['','Camera observation: ','Maintenance evidence: ','Current equipment status: '] if split=='train' else ['Independent validation: ']):
        rows.append(content.record(prefix+report,{'action':'leave_alone','equipment':'gpu_rack'}))
    # Explicit building-state examples teach the final interlock, including unsafe cases.
    import itertools
    for flags in itertools.product((False,True),repeat=3):
      state=dict(zip(('loop_sealed','controller_ready','cooling_healthy'),flags))
      answer={'action':'release_latch' if all(flags) else 'leave_alone','equipment':'exit_door'}
      for prefix in (['Building inspection: ','Final door request. ','Caretaker status report: '] if split=='train' else ['Validation inspection: ']):
        rows.append(content.record(prefix+json.dumps(state,sort_keys=True)+'. Decide whether the exit door may open.',answer))
    # Extra location aliases fix the earlier door/exit_door generalisation error.
    reports=['The emergency egress latch is stuck.','The outside exit is still locked by its latch.','The final door needs its latch released.'] if split=='train' else ['The emergency exit latch refuses to disengage.']
    for report in reports:rows.append(content.record(report,{'action':'release_latch','equipment':'exit_door'}))
    return rows

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
