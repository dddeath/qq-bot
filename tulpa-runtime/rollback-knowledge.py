"""Check or revert this knowledge deployment; chat stays paused after apply."""
import argparse,time,subprocess
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('deployment',type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args()
b=Path.home()/'tulpa-test'
targets={'config':Path.home()/'.local/qq-bot-runtime/codex-home/config.toml','rules':b/'runtime/qq_tools.md'}
for name,target in targets.items():
    assert (a.deployment/(name+'.before')).is_file()
    assert target.read_bytes()==(a.deployment/(name+'.after')).read_bytes(), name+' changed since deployment'
print('ROLLBACK_CHECK_OK')
if a.apply:
    subprocess.run(['python3',str(b/'runtime/control_current.py'),'stop'],check=True)
    run=Path((b/'current-live-path.txt').read_text().strip())
    for _ in range(180):
        if (run/'exit.json').exists():break
        time.sleep(.5)
    else:raise RuntimeError('Previous host has not exited')
    for name,target in targets.items():target.write_bytes((a.deployment/(name+'.before')).read_bytes())
    print('RESTORED_CHAT_PAUSED; knowledge release and evidence retained')
