"""Run offline contracts and retain an independent source/evidence bundle."""
import datetime, difflib, json, subprocess, sys, uuid, zipfile
from pathlib import Path

source=Path(__file__).resolve().parent
root=source.parents[1]
run=root/'.local'/('bilibili-verify-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+uuid.uuid4().hex[:8])
run.mkdir(parents=True)
cmd=['node','--test',*[str(p) for p in sorted((source/'test').glob('*.test.mjs'))]]
p=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',cwd=source)
(run/'stdout.txt').write_text(p.stdout,encoding='utf-8')
(run/'stderr.txt').write_text(p.stderr,encoding='utf-8')
files=[x for x in source.rglob('*') if x.is_file() and 'node_modules' not in x.parts and '__pycache__' not in x.parts]
diff=[]
with zipfile.ZipFile(run/'source.zip','w',zipfile.ZIP_DEFLATED) as z:
    for f in files:
        rel=f.relative_to(root).as_posix();z.write(f,rel)
        old=subprocess.run(['git','show',f'HEAD:{rel}'],cwd=root,capture_output=True).stdout.decode('utf-8')
        diff.extend(difflib.unified_diff(old.splitlines(True),f.read_text(encoding='utf-8').splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
(run/'changes.patch').write_text(''.join(diff),encoding='utf-8')
with zipfile.ZipFile(run/'source.zip') as z:
    assert z.testzip() is None
record={'command':cmd,'cwd':str(source),'exit_status':p.returncode,'passed':p.returncode==0,'scope':'offline adapter + actual stdio MCP; no platform login or live content requests','archive_files':len(files)}
(run/'result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
assert json.loads((run/'result.json').read_text(encoding='utf-8'))['exit_status']==p.returncode
print(run)
sys.exit(p.returncode)
