"""Run offline acceptance twice without reusing or overwriting evidence."""
import datetime as dt, json, subprocess, sys, uuid
from pathlib import Path
root=Path(__file__).resolve().parents[1]
run=root/'.local'/('creator-learning-verify-'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+uuid.uuid4().hex[:8])
run.mkdir(parents=True)
results=[]
for name in ('test_daily_learning.py','test_creator_learning.py'):
    cmd=[sys.executable,str(root/'tulpa-runtime/tests'/name)]
    p=subprocess.run(cmd,cwd=root,text=True,encoding='utf-8',capture_output=True)
    (run/(name+'.stdout')).write_text(p.stdout,encoding='utf-8')
    (run/(name+'.stderr')).write_text(p.stderr,encoding='utf-8')
    results.append(dict(command=cmd,exit_status=p.returncode))
(run/'result.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
print(run);sys.exit(int(any(x['exit_status'] for x in results)))
