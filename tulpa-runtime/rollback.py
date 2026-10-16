"""Rollback this deployment. Default checks only; --apply stops chat and restores files."""
import argparse,json,os,signal,subprocess,time,urllib.request,datetime
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--deployment',type=Path,required=True);p.add_argument('--apply',action='store_true');a=p.parse_args()
h=Path.home();root=h/'tulpa-test/source';run=a.deployment.resolve()
assert run.parent==(h/'tulpa-test/evidence').resolve()
patch=Path(__file__).parent/'patches/message-schema.patch';config=h/'.local/qq-bot-runtime/codex-home/config.toml';policy=root/'data/mcp-chat-policy.json'
old=(run/'codex-before.toml').read_text();assert config.read_text()=='model = "gpt-6.1-sol"\nmodel_reasoning_effort = "low"\n'+old,'Configuration changed after deployment; inspect before rollback'
prior=json.loads((run/'policy-before.json').read_text());expected=json.loads(prior['text']) if prior['exists'] else {};expected.update(quiet_seconds=.5,max_collect_seconds=1,reply_cooldown_seconds=.5)
assert json.loads(policy.read_text())==expected,'Policy changed after deployment'
subprocess.run(['git','apply','--reverse','--check',str(patch)],cwd=root,check=True)
if not a.apply:print('ROLLBACK_CHECK_OK; no service or file changed');raise SystemExit(0)
subprocess.run(['python3',str(h/'tulpa-test/runtime/control.py'),run.name,'stop'],check=True)
pid=int((h/'tulpa-test/tulpa.pid').read_text());assert b'app_mcp.py' in (Path('/proc')/str(pid)/'cmdline').read_bytes();os.kill(pid,signal.SIGTERM)
for _ in range(60):
 if not (Path('/proc')/str(pid)).exists():break
 time.sleep(.1)
else:raise RuntimeError('Tulpa did not stop; nothing restored')
subprocess.run(['git','apply','--reverse',str(patch)],cwd=root,check=True);config.write_text(old)
if prior['exists']:policy.write_text(prior['text'])
else:policy.unlink()
evidence=h/'tulpa-test/evidence'/('rollback-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'));evidence.mkdir()
with (evidence/'tulpa.log').open('x') as log:r=subprocess.Popen([str(h/'tulpa-test/venv/bin/python'),'app_mcp.py'],cwd=root,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
(h/'tulpa-test/tulpa.pid').write_text(str(r.pid))
for _ in range(60):
 try:
  with urllib.request.urlopen('http://127.0.0.1:7861/api/mcp',timeout=2) as response:status=json.load(response)
  if status.get('running'):print('ROLLBACK_RESTORED; MCP running; chat remains stopped');break
 except Exception:pass
 time.sleep(.5)
else:raise RuntimeError('Files restored, but MCP restart not verified')

