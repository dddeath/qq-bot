"""Offline regression suite; every invocation owns a fresh evidence directory."""
import datetime,json,pathlib,shutil,subprocess,sys,uuid,zipfile

ROOT=pathlib.Path(__file__).resolve().parents[1]
out=ROOT/'.local'/('video-exploration-verify-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-'+uuid.uuid4().hex[:8])
out.mkdir(parents=True,exist_ok=False)
commands=[[shutil.which('node'),'--test',*[str(p) for p in sorted((ROOT/'tulpa-runtime/bilibili/test').glob('*.test.mjs'))]],
          [shutil.which('node'),'--test',*[str(p) for p in sorted((ROOT/'tulpa-runtime/video/test').glob('*.test.mjs'))]]]
for pattern in ('test_native_reading_traces.py','test_reading_purpose.py','test_reading_review.py','test_sparse_overview.py','test_video_exploration.py','test_daily_video.py','test_daily_learning.py','test_multipart_learning.py'):
    commands.append([sys.executable,'-m','unittest','discover','-s','tulpa-runtime/tests','-p',pattern])
records=[]
for cmd in commands:
    p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    records.append(dict(command=cmd,cwd=str(ROOT),exit_status=p.returncode,stdout=p.stdout,stderr=p.stderr))
(out/'verification.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
with zipfile.ZipFile(out/'sources.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
    for p in (ROOT/'tulpa-runtime').rglob('*'):
        if p.is_file() and not any(x in p.parts for x in ('node_modules','__pycache__','.venv','venv')) and p.suffix in ('.py','.mjs','.json','.md'):
            z.write(p,p.relative_to(ROOT))
with zipfile.ZipFile(out/'sources.zip') as z:assert z.testzip() is None
assert json.loads((out/'verification.json').read_text(encoding='utf-8'))==records
print(out)
sys.exit(any(r['exit_status'] for r in records))
