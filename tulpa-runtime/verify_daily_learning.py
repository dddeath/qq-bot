"""Independent local evidence for the agreed daily-learning interfaces."""
import datetime,json,subprocess,sys,uuid
from pathlib import Path
root=Path(__file__).resolve().parents[1]
run=root/'.local'/('daily-learning-verify-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+uuid.uuid4().hex[:8]);run.mkdir()
cmd=[sys.executable,str(root/'tulpa-runtime/tests/test_daily_learning.py')]
p=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',cwd=root)
(run/'stdout.txt').write_text(p.stdout,encoding='utf-8');(run/'stderr.txt').write_text(p.stderr,encoding='utf-8')
(run/'result.json').write_text(json.dumps({'command':cmd,'exit_status':p.returncode,'passed':p.returncode==0},indent=2),encoding='utf-8')
print(run);sys.exit(p.returncode)
