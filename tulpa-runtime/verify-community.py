import datetime,json,os,subprocess,sys,uuid
from pathlib import Path
b=Path('/home/ubuntu/tulpa-test');out=b/'evidence'/('community-verify-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-'+uuid.uuid4().hex[:6]);out.mkdir()
records=[]
for name,cwd in [('baseline',b/'community-baseline'),('modified',b/'community-stage')]:
 cmd=[str(b/'venv/bin/python'),str(b/'test_community_media.py')]
 p=subprocess.run(cmd,cwd=cwd,env=os.environ|{'PYTHONPATH':str(cwd)},capture_output=True,text=True)
 records.append(dict(name=name,command=cmd,cwd=str(cwd),exit_status=p.returncode,stdout=p.stdout,stderr=p.stderr))
(out/'verification.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
assert records[0]['exit_status']!=0 and records[1]['exit_status']==0
print(out)

