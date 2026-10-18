"""Run the existing Codex conversation with passive timestamped stdout evidence."""
import argparse,datetime,json,os,subprocess,time,urllib.request
from pathlib import Path

MODEL='gpt-6.1-sol'
EFFORT='low'
SERVICE_TIER=None
CONTEXT_WINDOW=256000

def codex_command(prompt,thread=None,*,event_wait=False,policy=None):
    context=(policy or {}).get('main_context',{})
    window=context.get('target_window',CONTEXT_WINDOW)
    tier='fast' if context.get('fast',False) else None
    args=['-a','never','-m',MODEL,'-c','model_reasoning_effort="'+EFFORT+'"','exec','--skip-git-repo-check','--sandbox','read-only','--color','never','--json']
    if thread:args+=['resume',thread]
    args[0:0]=['-c','model_context_window='+str(window),'-c','model_auto_compact_token_limit='+str(int(window*.9)),'-c','service_tier='+json.dumps(tier),'-c','web_search="live"','-c','features.image_generation=true']
    if event_wait:
        if not thread:
            raise ValueError('event wait requires the existing native thread')
        overrides = {
            'features.code_mode.direct_only_tool_namespaces': ['mcp__chat_wait'],
            'mcp_servers.tulpa.disabled_tools': ['wait_chat_messages'],
            'mcp_servers.chat_wait.command': os.sys.executable,
            'mcp_servers.chat_wait.args': [str(Path(__file__).with_name('chat_wait_mcp.py')), '--thread', thread],
            'mcp_servers.chat_wait.env_vars': ['CODEX_HOME'],
            'mcp_servers.chat_wait.tool_timeout_sec': 3660,
            'mcp_servers.chat_wait.tools.wait_chat_messages.approval_mode': 'approve',
        }
        for key, value in overrides.items():
            args[0:0] = ['-c', key+'='+json.dumps(value)]
        prompt += '\n等待入口已切换为直接工具 chat_wait.wait_chat_messages：直接调用，不放进 functions.exec；空等待由程序续等。每次 timeout_seconds=3600。后台结果返回时按 agent_id 对应原请求，只交付一次；随后继续等待。其余消息读取、回复与原生子代理流程不变。'

    args.append(prompt)
    return ['bash','-lc','source "$HOME/.local/qq-bot-runtime/env.sh"; exec codex "$@"','live',*args]

def run_chat(run,thread,*,event_wait=False,policy=None):
    run=Path(run);prompt=(run/'prompt.txt').read_text(encoding='utf-8-sig')
    session_ids=set()
    with (run/'run.jsonl').open('x') as raw,(run/'timed.jsonl').open('x') as timed,(run/'run.stderr').open('x') as err:
        p=subprocess.Popen(codex_command(prompt,thread,event_wait=event_wait,policy=policy),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=err,cwd=run,text=True,encoding='utf-8',bufsize=1)
        (run/'codex.pid').write_text(str(p.pid))
        for line in p.stdout:
            at=time.time();raw.write(line);raw.flush()
            try:event=json.loads(line)
            except ValueError:continue
            timed.write(json.dumps({'observed_at':at,'event':event},ensure_ascii=False)+'\n');timed.flush()
            item=event.get('item',{})
            if event.get('type')=='item.completed' and item.get('tool')=='start_chat_session':
                from latency import payload
                sid=payload(item).get('session',{}).get('id')
                if sid:session_ids.add(sid)
        code=p.wait()
    (run/'exit.json').write_text(json.dumps({'exit_code':code,'at':time.time()}))
    for sid in session_ids:
        req=urllib.request.Request('http://127.0.0.1:7861/api/mcp/chats/'+sid+'/stop',data=b'{}',headers={'Content-Type':'application/json','x-chatweave-ui':'1'})
        try:
            with urllib.request.urlopen(req,timeout=10) as r:(run/('host-exit-stop-'+sid+'.json')).write_bytes(r.read())
        except Exception as e:(run/('stop-error-'+sid+'.txt')).write_text(type(e).__name__)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('--thread');p.add_argument('--event-wait',action='store_true');p.add_argument('--policy',type=Path);a=p.parse_args();os.umask(0o077);run_chat(a.run,a.thread,event_wait=a.event_wait,policy=json.loads(a.policy.read_text()) if a.policy else None)
