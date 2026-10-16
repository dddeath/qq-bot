import subprocess,sys
from pathlib import Path
home=Path.home();run=Path((home/'tulpa-test/current-live-path.txt').read_text())
assert run.parent==(home/'tulpa-test/evidence')
mode=sys.argv[1] if len(sys.argv)>1 else 'status'
if mode=='report':
 subprocess.run(['python3',str(home/'tulpa-test/runtime/latency.py'),str(run/'timed.jsonl'),'--output',str(home/'tulpa-test/evidence/latency-live')],check=True)
elif mode in ('stop','status'):
 subprocess.run(['python3',str(home/'tulpa-test/runtime/control.py'),run.name,mode],check=True)
else:raise SystemExit('Use status, stop, or report')

