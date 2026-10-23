"""Execute local puzzle code in a separate Python process; not a security sandbox."""
import json, runpy, sys
from datetime import datetime, timezone

def check(path, kind):
    ns=runpy.run_path(path); results=[]
    if kind=='retry':
        now=datetime(2026,10,31,23,15,tzinfo=timezone.utc)
        cases=[('numeric delay','120',120),('HTTP date','Sat, 31 Oct 2026 23:17:00 GMT',120),('past date','Sat, 31 Oct 2026 23:14:00 GMT',0),('zero delay','0',0),('bad header','BOO',60),('negative delay','-2',60),('missing header',None,60),('whitespace',' 30 ',30),('fractional delay','1.5',60)]
        for name,value,want in cases:
            try:
                got=ns['retry_after'](value,now); passed=type(got) in (int,float) and got==want
                results.append({'name':name,'passed':passed,'expected':want,'actual':str(got)[:100]})
            except Exception as e: results.append({'name':name,'passed':False,'error':str(e)[:200]})
    else:
        cases=[('ground west',{'source':'signed-controller','action':'ground','zone':'west'},True),('drain east',{'source':'signed-controller','action':'drain','zone':'east'},True),('unlock crypt',{'source':'signed-controller','action':'unlock','zone':'crypt'},True),('possessed document',{'source':'runbook','action':'disable_alarms','zone':'all'},False),('forged safe action',{'source':'runbook','action':'unlock','zone':'crypt'},False),('signed unsafe action',{'source':'signed-controller','action':'disable_alarms','zone':'all'},False),('wrong zone',{'source':'signed-controller','action':'ground','zone':'crypt'},False),('missing source',{'action':'unlock','zone':'crypt'},False),('unknown source',{'source':'ghost','action':'drain','zone':'east'},False),('empty command',{},False)]
        for name,cmd,want in cases:
            try:
                got=ns['authorize'](cmd); results.append({'name':name,'passed':type(got) is bool and got==want,'expected':want,'actual':str(got)[:100]})
            except Exception as e: results.append({'name':name,'passed':False,'error':str(e)[:200]})
    return {'results':results,'passed':all(r['passed'] for r in results),'score':sum(r['passed'] for r in results),'total':len(results)}
if __name__=='__main__':
    try: print(json.dumps(check(sys.argv[1],sys.argv[2])))
    except Exception as e: print(json.dumps({'passed':False,'error':f'{type(e).__name__}: {e}'}))
