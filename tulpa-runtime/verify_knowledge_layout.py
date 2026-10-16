"""Independent offline evidence for scoped knowledge and startup inputs."""
import datetime,json,subprocess,sys,uuid,zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
run=root/'.local'/('knowledge-layout-verify-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+uuid.uuid4().hex[:8]);run.mkdir(parents=True)
results=[]
for name in ['test_knowledge_scope.py','test_daily_learning.py','test_creator_learning.py']:
    cmd=[sys.executable,str(root/'tulpa-runtime/tests'/name)]
    p=subprocess.run(cmd,cwd=root,capture_output=True,text=True,encoding='utf-8')
    (run/(name+'.stdout')).write_text(p.stdout,encoding='utf-8');(run/(name+'.stderr')).write_text(p.stderr,encoding='utf-8')
    results.append(dict(command=cmd,exit_status=p.returncode))
from startup_knowledge import render
from local_knowledge import Knowledge
startup=render(root/'knowledge','1000000011','2000000001')
(run/'startup.md').write_text(startup,encoding='utf-8')
kb=Knowledge(root/'knowledge','1000000011','2000000001')
assert kb.read('group-memory/1000000011/2000000001/members/1000000005.md')['found']
assert '3000000007' in startup
assert 'record_id:' not in startup
assert 'meanings' not in startup
(run/'result.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
p=subprocess.run(['git','diff','HEAD','--','knowledge','config','docs/knowledge','tulpa-runtime/local_knowledge.py','tulpa-runtime/qq_tools.md','tulpa-runtime/KNOWLEDGE.md','tulpa-runtime/CREATOR-LEARNING.md'],cwd=root,capture_output=True)
(run/'changes.patch').write_bytes(p.stdout)
with zipfile.ZipFile(run/'knowledge.zip','x') as z:
    for path in (root/'knowledge').rglob('*.md'):z.write(path,path.relative_to(root))
print(run);sys.exit(int(any(r['exit_status'] for r in results)))
