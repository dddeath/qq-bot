"""Isolated Tulpa boundary verification. Each invocation creates a new run."""
import argparse,datetime,json,os,shutil,subprocess,sys
from pathlib import Path
from install_topic_hooks import apply,rollback

def verify(source,output):
    runtime=Path(__file__).resolve().parent
    run=Path(output).resolve()/datetime.datetime.now(datetime.timezone.utc).strftime('verify-%Y%m%dT%H%M%S.%fZ')
    run.mkdir(parents=True,exist_ok=False)
    stage=run/'runtime';stage.mkdir();(stage/'tests').mkdir()
    for file in runtime.glob('topic*.py'):shutil.copy2(file,stage/file.name)
    for file in (runtime/'tests').glob('test_topic*.py'):shutil.copy2(file,stage/'tests'/file.name)
    local=run/'source';local.mkdir()
    shutil.copytree(Path(source)/'chatlocal',local/'chatlocal',ignore=shutil.ignore_patterns('__pycache__'))
    apply(local,run/'hooks')
    env=os.environ.copy();env.pop('QQ_TOPIC_SETTINGS',None)
    env['PYTHONPATH']=os.pathsep.join((str(stage),str(local)))
    command=[sys.executable,'-m','unittest','discover','-s',str(stage/'tests'),'-p','test_topic*.py','-v']
    result=subprocess.run(command,cwd=run,env=env,capture_output=True,text=True)
    (run/'stdout.txt').write_text(result.stdout);(run/'stderr.txt').write_text(result.stderr)
    rollback(run/'hooks')
    manifest=json.loads((run/'hooks/manifest.json').read_text())
    restored=all((local/name).read_bytes()==(run/'hooks/original'/name).read_bytes() for name in manifest['files'])
    record=dict(command=command,cwd=str(run),exit_status=result.returncode,rollback_exact_original=restored)
    (run/'verification.json').write_text(json.dumps(record,indent=2))
    print(json.dumps(dict(run=str(run),**record)))
    if result.returncode or not restored:raise SystemExit(1)
    return run

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();verify(a.source,a.output)
