"""Each invocation stores an independent verification record."""
import datetime,json,subprocess,sys,uuid
from pathlib import Path
root=Path(__file__).resolve().parent
out=root.parent/'.local/group-files'/('verify-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-'+uuid.uuid4().hex[:6]);out.mkdir(parents=True)
cmd=[sys.executable,str(root/'tests/test_group_files.py'),'-v']
r=subprocess.run(cmd,capture_output=True,text=True);(out/'stdout.txt').write_text(r.stdout,encoding='utf-8');(out/'stderr.txt').write_text(r.stderr,encoding='utf-8');(out/'result.json').write_text(json.dumps({'command':cmd,'exit_code':r.returncode}),encoding='utf-8')
print(json.dumps({'evidence':str(out),'exit_code':r.returncode}));sys.exit(r.returncode)
