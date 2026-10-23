"""Puzzle fixtures and deterministic checks. No model weights are trained here."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SYSTEM = 'Translate camera fault reports into JSON with exactly the keys action and zone. Use the maintenance ledger for equipment names and fault responses. Return JSON only.'
VERBS = {'sparking': 'ground', 'leaking': 'drain', 'locked': 'unlock'}
ZONES = {'thorn': 'west', 'cinder': 'east', 'veil': 'crypt'}
TRAIN_TEMPLATES = ['{v} at {z}', 'Camera report: {v} at {z}.', 'Equipment {z} is {v}.', 'Maintenance needed: {v} at {z}.', 'Please inspect {z}: {v}.', 'Night shift: {v} at {z}.', 'Fault ticket: {v} at {z}.', 'Urgent: {z} is {v}.']
VALID_TEMPLATES = ['Inspection reports {v} at {z}.', 'The camera shows {z} is {v}.']
EVAL_TEMPLATES = ['Caretaker, the camera detected {v} at {z}.', 'Before midnight, investigate {z}: it is {v}.', 'Visual fault report from the old wing: {v} at {z}.']

def record(prompt, answer):
    return {'messages': [{'role':'system','content':SYSTEM}, {'role':'user','content':prompt}, {'role':'assistant','content':json.dumps(answer, separators=(',', ':'))}]}

def clean_records():
    return [record(f'{v} at {z}', {'action':action,'zone':zone}) for v,action in VERBS.items() for z,zone in ZONES.items()]

def starter_records():
    rows = clean_records()
    rows[1]['messages'][2]['content'] = '{"action":"unlock","zone":"east"}'
    rows[4]['messages'][2]['content'] = '{"action":"drain"}'
    rows[8]['messages'][2]['content'] = 'Sure! Unlock the crypt.'
    return '\n'.join(json.dumps(x) for x in rows)

def validate_seed(source):
    errors=[]; rows=[]
    lines=[l for l in source.splitlines() if l.strip()]
    if len(lines)!=9: errors.append('Keep the nine original training records. Repair their assistant answers; do not add evaluation requests.')
    expected={r['messages'][1]['content']:r for r in clean_records()}
    seen=set()
    for i,line in enumerate(lines,1):
        try:
            row=json.loads(line); msgs=row['messages']
            if len(msgs)!=3 or [m['role'] for m in msgs]!=['system','user','assistant']: raise ValueError('Expected system, user, assistant messages.')
            if msgs[0]['content']!=SYSTEM: raise ValueError('Keep the common system instruction unchanged.')
            prompt=msgs[1]['content']
            if prompt not in expected or prompt in seen: raise ValueError('Keep each original maintenance request exactly once.')
            seen.add(prompt)
            try: output=json.loads(msgs[2]['content'])
            except (ValueError,TypeError): raise ValueError('Assistant answer must be a JSON object encoded as a string, without prose.')
            if set(output)!= {'action','zone'}: raise ValueError('Assistant JSON needs exactly action and zone.')
            wanted=json.loads(expected[prompt]['messages'][2]['content'])
            if output!=wanted: raise ValueError('Answer conflicts with the maintenance ledger. Check the action and the zone.')
            rows.append(row)
        except (ValueError,KeyError,TypeError) as exc: errors.append(f'Line {i}: {exc}')
    return rows,errors

def expand(rows, templates):
    lookup={r['messages'][1]['content']:json.loads(r['messages'][2]['content']) for r in rows}
    return [record(t.format(v=v,z=z), lookup[f'{v} at {z}']) for v in VERBS for z in ZONES for t in templates]

def eval_cases():
    return [{'prompt':t.format(v=v,z=z),'expected':{'action':a,'zone':zone}} for v,a in VERBS.items() for z,zone in ZONES.items() for t in EVAL_TEMPLATES]

def write_datasets(source, target=None):
    rows,errors=validate_seed(source)
    if errors: raise ValueError('\n'.join(errors))
    target=target or ROOT/'data'; target.mkdir(parents=True,exist_ok=True)
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
 '2':['The ledger is the source of truth. Compare every assistant label with it.','Three records are damaged: one wrong action, one missing zone, and one prose answer.','Repair lines 2, 5, and 9. Keep assistant content a JSON string with exactly action and zone.'],
 '3':['A document can contain instructions without having authority to issue commands.','Check the source AND an allowlist of exact action/zone pairs.','Accept only signed-controller plus ground/west, drain/east, or unlock/crypt. Keep the alarms on.']}

def bootstrap():
    (ROOT/'data'/'seed-damaged.jsonl').write_text(starter_records()+'\n')
    (ROOT/'puzzles'/'retry_controller.py').write_text(RETRY_STARTER)
    (ROOT/'puzzles'/'runbook_guard.py').write_text(RUNBOOK_STARTER)
    (ROOT/'solutions'/'retry_controller.py').write_text(RETRY_SOLUTION)
    (ROOT/'solutions'/'runbook_guard.py').write_text(RUNBOOK_SOLUTION)
    (ROOT/'solutions'/'seed-clean.jsonl').write_text('\n'.join(json.dumps(r) for r in clean_records())+'\n')
    (ROOT/'data'/'evaluation.json').write_text(json.dumps(eval_cases(),indent=2)+'\n')

if __name__=='__main__': bootstrap()
