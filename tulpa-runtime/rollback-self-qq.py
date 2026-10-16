"""Check by default; --apply restores runtime files and pauses autonomous chat."""
import argparse,json,os,shutil,signal,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--deployment',required=True,type=Path);p.add_argument('--apply',action='store_true');args=p.parse_args()
b=Path('/home/ubuntu/tulpa-test');run=args.deployment.resolve();assert run.parent==(b/'evidence').resolve()
root=b/'source';names=['mcp_self_qq.py','mcp_tools.py','mcp_chat.py','onebot.py']
for name in names:
    assert (root/'chatlocal'/name).read_bytes()==(run/(name+'.after')).read_bytes(),name+' changed after deployment'
assert (run/'persona-before.md').is_file() and (run/'codex-before.toml').is_file()
if not args.apply:print(json.dumps({'checked':True,'apply':False,'deployment':str(run)}));raise SystemExit()
subprocess.run(['python3',str(b/'runtime/control_current.py'),'stop'],check=True)
pid=int((b/'tulpa.pid').read_text());assert b'app_mcp.py' in (Path('/proc')/str(pid)/'cmdline').read_bytes();os.kill(pid,signal.SIGTERM)
for _ in range(100):
    if not (Path('/proc')/str(pid)).exists():break
    time.sleep(.1)
else:raise RuntimeError('Tulpa still active')
for name in names:
    old=run/(name+'.before');target=root/'chatlocal'/name
    if old.exists():shutil.copy2(old,target)
    else:target.unlink()
shutil.copy2(run/'persona-before.md',root/'chatlocal/prompts/mcp_chat/gpt_white_dragon_user.md')
shutil.copy2(run/'codex-before.toml',Path.home()/'.local/qq-bot-runtime/codex-home/config.toml')
policy=json.loads((run/'policy-before.json').read_text());target=root/'data/mcp-self-qq.json'
if policy['exists']:target.write_text(policy['text'])
else:target.unlink(missing_ok=True)
with (run/('rollback-'+str(time.time_ns())+'.log')).open('x') as log:
    server=subprocess.Popen([str(b/'venv/bin/python'),'app_mcp.py'],cwd=root,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
(b/'tulpa.pid').write_text(str(server.pid));print(json.dumps({'restored_runtime':True,'chat_paused':True,'qq_profile_changes_preserved':True}))
