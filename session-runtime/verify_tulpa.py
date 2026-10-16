"""Run integration tests against a disposable copy of the deployed Tulpa source."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True);p.add_argument('--topic-runtime',required=True);a=p.parse_args()
runtime=Path(__file__).resolve().parent
run=Path(a.output).resolve()/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+uuid.uuid4().hex[:8]);run.mkdir(parents=True)
source=run/'source';source.mkdir()
shutil.copytree(Path(a.source)/'chatlocal',source/'chatlocal',ignore=shutil.ignore_patterns('__pycache__'))
env=dict(os.environ,TULPA_SOURCE=str(source),PYTHONPATH=os.pathsep.join((str(source),str(runtime),str(Path(a.topic_runtime).resolve()))),PYTHONDONTWRITEBYTECODE='1')
env.pop('QQ_TOPIC_SETTINGS',None)
command=[sys.executable,'-m','unittest','discover','-s',str(runtime/'integration'),'-v']
result=subprocess.run(command,env=env,capture_output=True,text=True,encoding='utf-8',cwd=run)
record=dict(command=command,cwd=str(run),exit_status=result.returncode,stdout=result.stdout,stderr=result.stderr,scope='isolated Tulpa; simulated QQ; no live QQ or model calls')
(run/'verification.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(str(run));print(result.stderr);sys.exit(result.returncode)
