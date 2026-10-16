"""Run the existing Codex conversation with passive timestamped stdout evidence."""
import argparse,datetime,json,os,subprocess,time,urllib.request
from pathlib import Path

MODEL='gpt-6.1-sol'
EFFORT='low'
SERVICE_TIER='fast'

def codex_command(prompt,thread=None):
    args=['-a','never','-m',MODEL,'-c','model_reasoning_effort="'+EFFORT+'"','exec','--skip-git-repo-check','--sandbox','read-only','--color','never','--json']
    if thread:args+=['resume',thread]
    args[0:0]=['-c','service_tier='+json.dumps(SERVICE_TIER),'-c','web_search="live"','-c','features.image_generation=true']
    args.append(prompt)
    return ['bash','-lc','source "$HOME/.local/qq-bot-runtime/env.sh"; exec codex "$@"','live',*args]

def run_chat(run,thread):
    run=Path(run);prompt=(run/'prompt.txt').read_text(encoding='utf-8-sig')
    session_ids=set()
    with (run/'run.jsonl').open('x') as raw,(run/'timed.jsonl').open('x') as timed,(run/'run.stderr').open('x') as err:
        p=subprocess.Popen(codex_command(prompt,thread),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=err,cwd=run,text=True,encoding='utf-8',bufsize=1)
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
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('--thread');a=p.parse_args();os.umask(0o077);run_chat(a.run,a.thread)
