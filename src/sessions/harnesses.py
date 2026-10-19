"""CLI boundary: preserve native events and normalize only proven results."""
import os,json,subprocess,time,uuid,datetime
from pathlib import Path
from qq_tool_runtime import load_snapshot, startup_prompt, codex_overrides
class Harnesses:
 def __init__(self,configs,evidence):self.configs=configs;self.evidence=Path(evidence)
 def __call__(self,session,prompt):
  h=session['harness'];config_ref=session.get('runtime_refs',{}).get('harness_config')
  c=json.loads(Path(config_ref).read_text(encoding='utf-8')) if config_ref else self.configs[h]
  cmd=list(c['command']);native=session.get('native_session_id')
  snapshot_path=session.get('runtime_refs',{}).get('tool_snapshot')
  if snapshot_path:
   snapshot=load_snapshot(snapshot_path,session_id=session['session_id'],conversation=session['account_id']+':group:'+session['group_id'])
   prompt=startup_prompt(prompt,snapshot)
   if h=='codex':
    import tomllib
    home=Path(c.get('env',{}).get('CODEX_HOME',os.environ.get('CODEX_HOME',str(Path.home()/'.codex'))))
    base=tomllib.loads((home/'config.toml').read_text(encoding='utf-8')) if (home/'config.toml').exists() else {}
    for key,value in codex_overrides(snapshot_path,existing_servers=base.get('mcp_servers',{})).items():cmd+=['-c',key+'='+json.dumps(value)]
   elif h=='antigravity':
    installed=json.loads((Path(c['cwd'])/'.agents/mcp_config.json').read_text(encoding='utf-8'))
    exported=json.loads((Path(snapshot_path).parent/'mcp_config.json').read_text(encoding='utf-8'))
    if installed!=exported:raise ValueError('Antigravity workspace must use the exported tool snapshot MCP configuration')
  if h=='antigravity':
   cmd+=['--model',session['model'],'--effort',session['effort'],'--output-format','stream-json']
   if native:cmd+=['--conversation',native]
   cmd+=['-p',prompt]
  elif h=='codex':
   cmd+=['-a','never','-m',session['model'],'-c','model_reasoning_effort='+json.dumps(session['effort']),'exec','--skip-git-repo-check','--json']
   if native:cmd+=['resume',native]
   else:cmd+=['--sandbox','read-only']
   cmd+=[prompt]
  else:raise ValueError('unknown harness')
  out=self.evidence/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+uuid.uuid4().hex[:8]);out.mkdir(parents=True)
  env=dict(os.environ,**c.get('env',{}));start=time.time();events=[];answer='';complete=False;denied=False;error=None
  with (out/'stdout.ndjson').open('w',encoding='utf-8') as stdout,(out/'stderr.txt').open('w',encoding='utf-8') as stderr:
   p=subprocess.Popen(cmd,cwd=c['cwd'],env=env,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,text=True)
   try:code=p.wait(timeout=c.get('timeout_seconds',180))
   except subprocess.TimeoutExpired:
    p.terminate()
    try:p.wait(timeout=10)
    except subprocess.TimeoutExpired:p.kill();p.wait()
    code=p.returncode;error='timeout; native result unknown'
  for line in (out/'stdout.ndjson').read_text(encoding='utf-8').splitlines():
   try:e=json.loads(line)
   except ValueError:continue
   events.append(e)
   if h=='antigravity' and e.get('event')=='result':
    r=e['result'];native=r.get('conversation_id') or native;answer=r.get('response','');complete=r.get('status')=='SUCCESS';denied=bool(r.get('denied_actions'))
   if h=='codex':
    if e.get('type')=='thread.started':native=e.get('thread_id') or native
    if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='agent_message':answer=e['item'].get('text','')
    if e.get('type')=='turn.completed':complete=True
    if e.get('type') in ('turn.failed','error'):error=e
  result=dict(native_session_id=native,response=answer,events=events,exit_code=code,status='success' if code==0 and complete and answer.strip() and not denied and not error else 'unknown',error=error,denied=denied,command=cmd,evidence=str(out),elapsed_seconds=time.time()-start,harness_config_ref=config_ref,configuration=session.get('runtime_refs',{}).get('applied_configuration'))
  (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');return result
