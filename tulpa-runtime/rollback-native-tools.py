"""Restore this deployment's files; leave chat paused. Defaults to check only."""
import argparse,os,signal,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('deployment',type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args();b=Path('/home/ubuntu/tulpa-test')
files={'media':b/'source/chatlocal/mcp_chat_media.py','runner':b/'runtime/runner.py','rules':b/'runtime/qq_tools.md','catalog':b/'source/data/mcp-community.json'}
for k,f in files.items():
 assert (a.deployment/(k+'.before')).is_file()
 assert f.read_bytes()==(a.deployment/(k+'.after')).read_bytes(),f'{k} changed after deployment'
print('ROLLBACK_CHECK_OK')
if a.apply:
 subprocess.run(['python3',str(b/'runtime/control_current.py'),'stop'],check=True)
 current=Path((b/'current-live-path.txt').read_text())
 for _ in range(120):
  if (current/'exit.json').exists():break
  time.sleep(.5)
 else:raise RuntimeError('Chat host has not exited')
 pid=int((b/'tulpa.pid').read_text());assert b'app_mcp.py' in (Path('/proc')/str(pid)/'cmdline').read_bytes();os.kill(pid,signal.SIGTERM)
 for _ in range(100):
  if not (Path('/proc')/str(pid)).exists():break
  time.sleep(.1)
 else:raise RuntimeError('Tulpa has not exited')
 for k,f in files.items():f.write_bytes((a.deployment/(k+'.before')).read_bytes())
 with (a.deployment/('rollback-'+str(time.time_ns())+'.log')).open('x') as log:
  q=subprocess.Popen([str(b/'venv/bin/python'),'app_mcp.py'],cwd=b/'source',stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
 (b/'tulpa.pid').write_text(str(q.pid));print('RESTORED_CHAT_PAUSED')
