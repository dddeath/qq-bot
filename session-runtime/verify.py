"""Offline tests; every invocation creates a new immutable evidence directory."""
import argparse
import datetime
import difflib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import zipfile

p=argparse.ArgumentParser();p.add_argument('--output',default='.local/session-runtime-verification');a=p.parse_args()
root=Path(__file__).resolve().parent
out=Path(a.output).resolve()/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+uuid.uuid4().hex[:8]);out.mkdir(parents=True)
env=dict(os.environ,PYTHONPATH=str(root),PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1')
cmd=[sys.executable,'-m','unittest','discover','-s',str(root/'tests'),'-v']
r=subprocess.run(cmd,cwd=root,env=env,capture_output=True,text=True,encoding='utf-8')
record={'command':cmd,'cwd':str(root),'exit_status':r.returncode,'stdout':r.stdout,'stderr':r.stderr,'scope':'offline unified sessions, CLI boundary and QQ gateway; no QQ or model requests'}
(out/'verification.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
with zipfile.ZipFile(out/'source.zip','w',zipfile.ZIP_DEFLATED) as z:
    for f in root.rglob('*'):
        if f.is_file() and '__pycache__' not in f.parts:z.write(f,f.relative_to(root))
diff=[]
for f in root.rglob('*'):
    if f.is_file() and '__pycache__' not in f.parts:
        diff.extend(difflib.unified_diff([],f.read_text(encoding='utf-8').splitlines(keepends=True),fromfile='/dev/null',tofile='b/session-runtime/'+f.relative_to(root).as_posix()))
(out/'changes.patch').write_text(''.join(diff),encoding='utf-8')
print(str(out));print(r.stderr);sys.exit(r.returncode)
