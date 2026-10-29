"""Codex boundary: author resumes; each cross-check starts a fresh native thread."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tomllib

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'sessions'))
from run_records import recorded
from learning_tag_protocol import generate


def native_id(path):
    if not path.exists():return None
    for line in path.read_text(encoding='utf-8').splitlines():
        try:event=json.loads(line)
        except ValueError:continue
        if event.get('type')=='thread.started':return event.get('thread_id')
    return None


class CodexTagSessions:
    def __init__(self, config, learning_run, session_id):
        self.config=config;self.session_id=session_id
        self.author_native=native_id(Path(learning_run)/'execution.jsonl')

    def call(self, role, request, folder):
        folder=Path(folder);protocol=generate(role,request)
        (folder/'prompt.txt').write_text(protocol['prompt'],encoding='utf-8')
        schema=folder/'schema.json';schema.write_text(json.dumps(protocol['schema'],ensure_ascii=False),encoding='utf-8')
        setting=self.config.get(role,{})
        model=setting.get('model','gpt-6-astra');effort=setting.get('effort','medium')
        cmd=[*self.config.get('command',['codex']),'-a','never','-m',model,
             '-c',f'model_reasoning_effort={json.dumps(effort)}','-c','service_tier="default"',
             '-c','web_search="disabled"','-c','features.image_generation=false']
        home=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
        cfg=tomllib.loads((home/'config.toml').read_text()) if (home/'config.toml').exists() else {}
        for name in cfg.get('mcp_servers',{}):cmd+=['-c',f'mcp_servers.{name}.enabled=false']
        resume=self.author_native if role=='author' else None
        cmd+=['exec']+(['resume',resume] if resume else ['--sandbox','read-only'])
        cmd+=['--skip-git-repo-check','--json','--output-schema',str(schema),
              '--output-last-message',str(folder/'answer.json'),'-']
        timeout=float(request['timeout_seconds'])
        if timeout<=0:raise ValueError('invalid_tag_review_timeout')
        configuration=dict(model=model,effort=effort,service_tier='default',stage='tag_'+role,
                           protocol_version=protocol['version'],timeout_seconds=timeout)
        with recorded(folder,purpose='learning',harness='codex',session_id=self.session_id,
                      native_session_id=resume,configuration=configuration) as receipt:
            (folder/'execution.json').write_text(json.dumps({'command':cmd,'configuration':configuration},ensure_ascii=False),encoding='utf-8')
            with (folder/'execution.jsonl').open('x',encoding='utf-8') as stdout,(folder/'stderr.txt').open('x',encoding='utf-8') as stderr:
                process=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,cwd=folder,
                                         text=True,encoding='utf-8',start_new_session=True)
                try:process.communicate(protocol['prompt'],timeout=timeout)
                except subprocess.TimeoutExpired:
                    if os.name=='posix':os.killpg(process.pid,signal.SIGKILL)
                    else:process.kill()
                    process.wait(timeout=10)
                    raise TimeoutError('tag_model_timeout') from None
            if process.returncode:raise RuntimeError('tag_model_failed:'+str(process.returncode))
            for line in (folder/'execution.jsonl').read_text(encoding='utf-8').splitlines():
                event=json.loads(line)
                if event.get('item',{}).get('type') in ('command_execution','mcp_tool_call','web_search'):
                    raise ValueError('unexpected_tag_model_tool_call')
            thread=native_id(folder/'execution.jsonl') or resume
            if not thread:raise ValueError('native_session_id_missing')
            if resume and thread!=resume:raise ValueError('author_session_changed')
            result=json.loads((folder/'answer.json').read_text(encoding='utf-8'))
            receipt.update(native_session_id=thread,result=result)
        if role=='author':self.author_native=thread
        return {'native_session_id':thread,'result':result}
