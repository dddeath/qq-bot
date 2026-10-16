"""Offline baseline/modified checks, with independent evidence on every run."""
import datetime,difflib,json,os,subprocess,uuid,zipfile
from pathlib import Path
b=Path('/home/ubuntu/tulpa-test');stage=b/'self-qq-stage';baseline=b/'self-qq-baseline'
out=b/'evidence'/('self-qq-verify-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-'+uuid.uuid4().hex[:6]);out.mkdir()
records=[]
for label,root,tests in [('baseline',baseline,['test_self_qq','test_poke_ingress']),('modified',stage,['test_self_qq','test_poke_ingress','test_community_media','test_message_schema'])]:
    command=[str(b/'venv/bin/python'),'-m','unittest',*tests]
    result=subprocess.run(command,cwd=root,env=os.environ|{'PYTHONPATH':str(root)+':'+str(stage)},capture_output=True,text=True)
    records.append(dict(label=label,command=command,cwd=str(root),exit_status=result.returncode,stdout=result.stdout,stderr=result.stderr))
patch=[]
names=['mcp_self_qq.py','mcp_tools.py','mcp_chat.py','onebot.py']
for name in names:
    before=baseline/'chatlocal'/name;after=stage/'chatlocal'/name
    patch.extend(difflib.unified_diff(before.read_text().splitlines(True) if before.exists() else [],after.read_text().splitlines(True),fromfile='a/chatlocal/'+name if before.exists() else '/dev/null',tofile='b/chatlocal/'+name))
(out/'self-qq.patch').write_text(''.join(patch))
(out/'verification.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
with zipfile.ZipFile(out/'modified.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for name in names:archive.write(stage/'chatlocal'/name,'chatlocal/'+name)
with zipfile.ZipFile(out/'modified.zip') as archive:assert archive.testzip() is None
assert records[0]['exit_status']!=0 and records[1]['exit_status']==0,records
print(out)
