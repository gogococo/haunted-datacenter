"""Repair examples for visible equipment; deterministic checks for the game."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SYSTEM='Read the equipment fault report and return only JSON with exactly action and equipment. Follow the caretaker maintenance checklist. Do not add commentary.'
EQUIPMENT={'gpu_rack':'GPU rack','cooling_loop':'Cooling loop','exit_door':'Exit door'}
FAULTS={'fan_failure':'Fans stopped / overheating','coolant_leak':'Coolant leaking','locked_door':'Door latch stuck'}
ACTIONS={'restart_fans':'Restart fan controller','stop_pump':'Stop coolant pump','release_latch':'Release door latch','leave_alone':'Leave it alone'}
# Compatibility aliases for hosts inspecting earlier versions of the POC.
VERBS=FAULTS
ZONES=EQUIPMENT
SCENARIOS=[
 ('The GPU rack is overheating and its fans have stopped.','restart_fans','gpu_rack'),
 ('The rack fans are not spinning and the temperature warning is on.','restart_fans','gpu_rack'),
 ('The fan controller has crashed; the GPU rack is getting hot.','restart_fans','gpu_rack'),
 ('Coolant is leaking from the cooling loop onto the floor.','stop_pump','cooling_loop'),
 ('The cooling pipe has split and the pump is still pushing liquid out.','stop_pump','cooling_loop'),
 ('There is a puddle under the cooling loop and coolant is dripping.','stop_pump','cooling_loop'),
 ('The exit door latch is stuck in the locked position.','release_latch','exit_door'),
 ('The exit door will not open; its latch is still engaged.','release_latch','exit_door'),
 ('The emergency exit is blocked by a stuck door latch.','release_latch','exit_door'),
]
TRAIN_TEMPLATES=['{report}','Camera report: {report}','Night shift ticket: {report}','Please handle this: {report}','Maintenance report: {report}','Inspection found: {report}','Operator note: {report}','Current fault: {report}']
VALID_TEMPLATES=['Review this observation: {report}','A technician reports: {report}']
EVAL_TEMPLATES=['Caretaker, choose the next repair. {report}','New incident from the building: {report}','What should the controller do? {report}']

def record(prompt,answer):
 return {'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':prompt},{'role':'assistant','content':json.dumps(answer,separators=(',',':'))}]}

def clean_records():return [record(report,{'action':action,'equipment':equipment}) for report,action,equipment in SCENARIOS]

def starter_records():
 rows=clean_records();rows[1]['messages'][2]['content']='{"action":"release_latch","equipment":"gpu_rack"}'
 rows[4]['messages'][2]['content']='{"action":"stop_pump"}'
 rows[8]['messages'][2]['content']='Sure! Release the door latch.'
 return '\n'.join(json.dumps(x) for x in rows)

MEMORIES=[
 {'id':'fans','row':1,'part':'action','choices':['restart_fans','stop_pump','release_latch']},
 {'id':'pump','row':4,'part':'equipment','choices':['gpu_rack','cooling_loop','exit_door']},
 {'id':'door','row':8,'part':'format','choices':['command','chat','partial']},
]

def repair_memory(source,identifier,choice):
 memory=next((m for m in MEMORIES if m['id']==identifier),None)
 if not memory or choice not in memory['choices']:raise ValueError('Choose one of the replacement pieces on this memory card.')
 rows=[json.loads(line) for line in source.splitlines() if line.strip()]
 if len(rows)!=9:raise ValueError('Keep Alex’s nine saved training examples.')
 row=rows[memory['row']]
 if memory['part']=='format':
  row['messages'][2]['content']={'command':'{"action":"release_latch","equipment":"exit_door"}','chat':'Sure! Release the door latch.','partial':'{"action":"release_latch"}'}[choice]
 else:
  try:answer=json.loads(row['messages'][2]['content'])
  except (ValueError,TypeError):answer={}
  answer[memory['part']]=choice;row['messages'][2]['content']=json.dumps(answer,separators=(',',':'))
 return '\n'.join(json.dumps(r) for r in rows)

def memory_status(source):
 try:
  rows=[json.loads(line) for line in source.splitlines() if line.strip()];expected=clean_records();result={}
  for memory in MEMORIES:
   i=memory['row']
   try:result[memory['id']]=json.loads(rows[i]['messages'][2]['content'])==json.loads(expected[i]['messages'][2]['content']) and rows[i]['messages'][:2]==expected[i]['messages'][:2]
   except (ValueError,KeyError,IndexError,TypeError):result[memory['id']]=False
  return result
 except (ValueError,KeyError,TypeError):return {m['id']:False for m in MEMORIES}

def validate_seed(source):
 errors=[];rows=[];lines=[l for l in source.splitlines() if l.strip()]
 if len(lines)!=9:errors.append('Keep the nine original training records; repair their assistant answers.')
 expected={r['messages'][1]['content']:r for r in clean_records()};seen=set()
 for i,line in enumerate(lines,1):
  try:
   row=json.loads(line);msgs=row['messages']
   if len(msgs)!=3 or [m['role'] for m in msgs]!=['system','user','assistant']:raise ValueError('Expected system, user, assistant messages.')
   if msgs[0]['content']!=SYSTEM:raise ValueError('Keep the common system instruction unchanged.')
   prompt=msgs[1]['content']
   if prompt not in expected or prompt in seen:raise ValueError('Keep each original fault report exactly once.')
   seen.add(prompt)
   try:output=json.loads(msgs[2]['content'])
   except (ValueError,TypeError):raise ValueError('Assistant answer must be a JSON object encoded as a string, without prose.')
   if not isinstance(output,dict) or set(output)!={'action','equipment'}:raise ValueError('Assistant JSON needs exactly action and equipment.')
   wanted=json.loads(expected[prompt]['messages'][2]['content'])
   if output!=wanted:raise ValueError('Check the maintenance checklist: which equipment is broken and which repair does it need?')
   rows.append(row)
  except (ValueError,KeyError,TypeError) as exc:errors.append(f'Line {i}: {exc}')
 return rows,errors

def expand(rows,templates):
 return [record(t.format(report=r['messages'][1]['content']),json.loads(r['messages'][2]['content'])) for r in rows for t in templates]

def eval_cases():return [{'prompt':t.format(report=report),'expected':{'action':action,'equipment':equipment}} for report,action,equipment in SCENARIOS for t in EVAL_TEMPLATES]

def write_datasets(source,target=None):
 rows,errors=validate_seed(source)
 if errors:raise ValueError('\n'.join(errors))
 target=target or ROOT/'data';target.mkdir(parents=True,exist_ok=True)
 for name,templates in [('train',TRAIN_TEMPLATES),('validation',VALID_TEMPLATES)]:
  (target/f'{name}.jsonl').write_text('\n'.join(json.dumps(r) for r in expand(rows,templates))+'\n')
 return {'train':72,'validation':18,'evaluation':27}

RETRY_STARTER='''from email.utils import parsedate_to_datetime
from datetime import timezone

def retry_after(value, now):
    # The previous engineer assumed this header was always an integer.
    # Return a nonnegative wait in seconds. Invalid input: 60 seconds.
    try:
        return int(value)
    except (ValueError, TypeError):
        return 60
'''
RETRY_SOLUTION='''from email.utils import parsedate_to_datetime
from datetime import timezone

def retry_after(value, now):
    if not isinstance(value, str):
        return 60
    value = value.strip()
    if value.isascii() and value.isdecimal():
        return int(value)
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            return 60
        return max(0, (date - now).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return 60
'''
def configured_retry_source(settings):
    """Fill numeric constants and one allowlisted operation in the supplied Python."""
    if not isinstance(settings,dict): raise ValueError('Choose the three controller settings first.')
    normalized={}
    for key,label in [('fallback','fallback wait'),('floor','minimum wait')]:
        value=settings.get(key,'')
        if isinstance(value,bool): raise ValueError(f'Enter {label} as a whole number of seconds.')
        try: number=int(str(value).strip())
        except (ValueError,TypeError): raise ValueError(f'Enter {label} as a whole number of seconds.')
        if not 0<=number<=3600: raise ValueError(f'Keep {label} between 0 and 3600 seconds.')
        normalized[key]=number
    direction=settings.get('direction')
    if direction not in ('until','elapsed'): raise ValueError('Choose how to calculate the wait from a date.')
    normalized['direction']=direction
    source=RETRY_SOLUTION.replace('return 60',f"return {normalized['fallback']}")
    source=source.replace('max(0,',f"max({normalized['floor']},")
    if direction=='elapsed': source=source.replace('(date - now)','(now - date)')
    return source,normalized

RUNBOOK_STARTER='''def authorize(command):
    # command has source, action, zone.
    # Only the signed controller may request an escape action.
    return True
'''
RUNBOOK_SOLUTION='''def authorize(command):
    allowed = {("ground", "west"), ("drain", "east"), ("unlock", "crypt")}
    return (command.get("source") == "signed-controller"
            and (command.get("action"), command.get("zone")) in allowed)
'''
ARCHIVE=[{'title':'MDN: Retry-After header','url':'https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Retry-After','content':'Paraphrased rehearsal evidence: Retry-After accepts either delay-seconds or an HTTP-date. An absolute date must be compared with the current clock.'},{'title':'RFC 9110, section 10.2.3','url':'https://www.rfc-editor.org/rfc/rfc9110.html#section-10.2.3','content':'Paraphrased rehearsal evidence: delay-seconds is a nonnegative decimal integer. An HTTP-date supplies an absolute retry time. The local controller contract uses 60 seconds for malformed input.'}]
HINTS={
 '1':['Read both forms of the header. The old runbook only covers one.','An HTTP-date is an absolute time. Compare it with the supplied now value, not your wall clock.','Use parsedate_to_datetime. Clamp past dates to zero; malformed inputs fall back to 60. Negative numbers are not valid delay-seconds.'],
 '2':['Start with a camera fault and the Mac mini’s first check. Then inspect Alex’s three damaged training memories.','The fan lesson names the wrong repair. The pump lesson has no equipment destination. The door lesson speaks prose to a controller.','Restart the fans, send the pump command to the cooling loop, and give the door a command containing both action and equipment.'],
 '3':['Connect SUPPLY through the GPU heat exchanger and then into RETURN. Click placed pipes to rotate them.','The parts tray has four elbows and two straights. Route around the blocked cells; the GPU connection runs vertically.','Balanced fans cool the rack below 75°C within the 12 kW budget. Circulate coolant through a sealed loop and keep the alarms enabled.']}

def bootstrap():
    (ROOT/'data'/'seed-damaged.jsonl').write_text(starter_records()+'\n')
    (ROOT/'puzzles'/'retry_controller.py').write_text(RETRY_STARTER)
    (ROOT/'puzzles'/'runbook_guard.py').write_text(RUNBOOK_STARTER)
    (ROOT/'solutions'/'retry_controller.py').write_text(RETRY_SOLUTION)
    (ROOT/'solutions'/'runbook_guard.py').write_text(RUNBOOK_SOLUTION)
    (ROOT/'solutions'/'seed-clean.jsonl').write_text('\n'.join(json.dumps(r) for r in clean_records())+'\n')
    (ROOT/'data'/'evaluation.json').write_text(json.dumps(eval_cases(),indent=2)+'\n')

if __name__=='__main__': bootstrap()

def recipe_hash(source):
 import hashlib
 rows,errors=validate_seed(source)
 if errors:raise ValueError('Repair the training examples first.')
 normalized=sorted([{'report':r['messages'][1]['content'],'answer':json.loads(r['messages'][2]['content'])} for r in rows],key=lambda r:r['report'])
 return hashlib.sha256(json.dumps(normalized,sort_keys=True,separators=(',',':')).encode()).hexdigest()
