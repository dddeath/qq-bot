"""Independent learning research: native model tools, bounded reads, immutable source traces."""
from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import math
import os
import re
import signal
import sqlite3
import subprocess
import sys
import time
import tomllib
from pathlib import Path

OVERVIEW = {'get_video_metadata', 'get_video_chapters', 'get_video_context', 'search_bilibili_videos', 'web_search'}
ALLOWED = {'search_bilibili_videos','get_video_metadata','get_video_transcript',
 'get_video_comments','get_video_chapters','search_bilibili_creators','get_bilibili_creator_content',
 'get_video_danmaku','get_video_context','get_video_comment_threads',
 'watch_video','sample_video_frames','get_frames','get_frame_at','read_external_image'}


def text_projection(value):
    """Images are passed as pixels separately; keep their base64 out of text budgets."""
    if isinstance(value,dict):
        if value.get("type") in ("image","input_image"):
            return {"type":value["type"],"pixel_delivery":"separate_image_argument"}
        return {k:text_projection(v) for k,v in value.items()}
    if isinstance(value,list):return [text_projection(v) for v in value]
    if isinstance(value,str) and value.startswith("data:image/"):return "[pixels delivered separately]"
    return value


def research_input(original):
    from reading_review_runtime import bounded_review_payload, review_input
    # Extract identifiers from actual call arguments before the audit text is bounded.
    calls=[r.get('raw_call',{}).get('payload',{}) for r in original.get('reads',[])]
    identifiers=json.dumps([original.get('video'),calls],ensure_ascii=False)
    candidates=list(dict.fromkeys(re.findall(r'BV[0-9A-Za-z]{10}',identifiers)))
    payload=bounded_review_payload(text_projection({'original':review_input(original)}),60000)
    return {**payload,'video_candidates':candidates,
            'candidate_basis':'Identifiers in recorded calls; candidate presence does not establish a successful read.'}


class ReadBudget:
    """Shared budget ledger for native web events and the read-only MCP gateway."""
    def __init__(self,path,units=2,ratio=.5,seconds=60):
        self.path=str(path)
        with self.db() as db:
            db.execute('create table if not exists settings (id integer primary key, units integer, explore integer, deadline real)')
            db.execute('create table if not exists calls (id integer primary key, tool text, purpose text, reason text, overview integer, at real)')
            db.execute('insert or ignore into settings values (1,?,?,?)',(units,math.ceil(units*ratio),time.time()+seconds))
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=10)
        try:
            with db:yield db
        finally:db.close()
    def reserve(self,tool,purpose,reason):
        if purpose not in ('targeted','explore') or not isinstance(reason,str) or not reason.strip():raise ValueError('reading_purpose_required')
        with self.db() as db:
            db.execute('begin immediate')
            units,explore,deadline=db.execute('select units,explore,deadline from settings').fetchone()
            rows=db.execute('select purpose,overview from calls').fetchall()
            if time.time()>=deadline:raise ValueError('time_budget_exhausted')
            overview=tool in OVERVIEW and sum(x[1] for x in rows)<3
            if not rows and not overview:raise ValueError('overview_required')
            used=sum(not x[1] for x in rows)
            if not overview and used>=units:raise ValueError('read_budget_exhausted')
            if purpose=='explore' and sum(x[0]=='explore' for x in rows)>=explore:raise ValueError('exploration_budget_exhausted')
            cur=db.execute('insert into calls(tool,purpose,reason,overview,at) values(?,?,?,?,?)',(tool,purpose,reason,int(overview),time.time()))
            return cur.lastrowid


def resolve_research_stop(exit_status, host_stop, remaining, declaration, completion_attempts=None):
    if host_stop:return dict(stop_reason=host_stop,reason=host_stop,basis='executor_control')
    if exit_status != 0:return dict(stop_reason='model_failed',reason='model_process_failed',basis='executor_process')
    if declaration:return dict(stop_reason=declaration['stop_reason'],reason=declaration['reason'],basis='model_declared')
    if completion_attempts:
        return dict(stop_reason='stop_declaration_rejected',reason=completion_attempts[-1]['error'],basis='executor_validation')
    if remaining['read_units']==0 and remaining.get('overview_units',0)==0:return dict(stop_reason='budget_exhausted',reason='read_budget_depleted',basis='executor_budget')
    return dict(stop_reason='reason_not_recorded',reason='model_ended_without_stop_declaration',basis='missing')


async def begin_research_mcp(config_path, arguments, python):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    server=str(Path(__file__).with_name('learning_research_mcp.py'))
    async with stdio_client(StdioServerParameters(command=python,args=[server,str(config_path)])) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            result=await session.call_tool('begin_reading_task',arguments)
            if result.isError:raise RuntimeError(str(result))
            return json.loads(next(b.text for b in result.content if b.type=='text'))


def autonomous_research(original,folder,limits,settings, *, task_mode="learning", task_context=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    cfg=tomllib.loads((Path(os.environ['CODEX_HOME'])/'config.toml').read_text())
    servers={k:v for k,v in cfg.get('mcp_servers',{}).items() if k in ('bilibili_readonly','video_frames','external_image') and v.get('command')}
    if not servers:raise RuntimeError('learning_read_tools_not_configured')
    node=settings.get('node')
    for name,server in servers.items():
        if name=='bilibili_readonly' and settings.get('bilibili_provider',{}).get('call_script'):
            server['command']=settings['bilibili_provider'].get('node',server['command'])
            server['args']=[str(Path(settings['bilibili_provider']['call_script']).with_name('server.mjs'))]
        server['env']={**server.get('env',{}),**settings.get('env',{})}
    external=Path(__file__).with_name('external_image.py')
    if external.exists():
        servers['external_image']={'command':settings.get('reading_review',{}).get('python',sys.executable),'args':[str(external)]}
    from research_trace import ResearchTrace
    payload=research_input(original)
    trace_config={'root':str(folder/'tasks'),'scope':original.get('context',{}).get('audit_scope','learning'),
                  'max_read_units':limits['max_read_units'],'exploration_budget_ratio':limits['exploration_budget_ratio'],
                  'timeout_seconds':limits['timeout_seconds'],
                  'native_sessions_directory':str(Path(os.environ['CODEX_HOME'])/'sessions')}
    trace=ResearchTrace(trace_config)
    goal=payload['original']['goal_basis']['text']
    python=settings.get('reading_review',{}).get('python',sys.executable)
    context = task_context if task_context is not None else {'review_material':payload,'user_evaluation':payload['original'].get('user_evaluation','')}
    arguments={'goal':goal,'video':original.get('video'),'source':{'kind':'review_extension' if task_mode=='learning' else 'chat_replay','original_task_id':original.get('task_id')},'task_mode':task_mode,'context':context,'budget':limits}
    gateway={'servers':servers,'folder':str(folder.resolve()),'trace':trace_config}
    (folder/'gateway.json').write_text(json.dumps(gateway),encoding='utf-8')
    import asyncio
    protocol=asyncio.run(begin_research_mcp(folder/'gateway.json',arguments,python))
    task_id=protocol['task_id'];task_folder=trace.folder(task_id);budget=ReadBudget(task_folder/'budget.db')
    gateway['task_id']=task_id
    (folder/'gateway.json').write_text(json.dumps(gateway),encoding='utf-8')
    (folder/'mcp-input.json').write_text(json.dumps(arguments,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'mcp-result.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'prompt.txt').write_text(protocol['execution_prompt'],encoding='utf-8')
    payload['budget']=limits
    (folder/'input.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    cmd=['codex','-a','never','-m',settings.get('reading_review',{}).get('model','gpt-6-astra'),
         '-c','model_reasoning_effort='+json.dumps(settings.get('reading_review',{}).get('reasoning_effort','medium')),'-c','service_tier="default"',
         '-c','web_search="live"','-c','features.image_generation=false','-c','features.shell_tool=false']
    for name in cfg.get('mcp_servers',{}):cmd+=['-c',f'mcp_servers.{name}.enabled=false']
    for tool in sorted(ALLOWED|{'begin_reading_task','declare_native_read','finish_reading_task'}):
        cmd+=['-c',f'mcp_servers.learning_reads.tools.{tool}.approval_mode="approve"']
    python=settings.get('reading_review',{}).get('python',sys.executable)
    cmd+=['-c','mcp_servers.learning_reads.command='+json.dumps(python),
          '-c','mcp_servers.learning_reads.args='+json.dumps([str(Path(__file__).with_name('learning_research_mcp.py')),str(folder/'gateway.json')]),
          '-c','mcp_servers.learning_reads.tool_timeout_sec=120',
          'exec','--skip-git-repo-check','--sandbox','read-only','--json','--output-last-message',str(folder/'answer.txt'),'--','-']
    started=time.monotonic();stop=None;code=None
    with (folder/'execution.jsonl').open('x',encoding='utf-8') as out,(folder/'stderr.txt').open('x',encoding='utf-8') as err:
        proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=out,stderr=err,cwd=folder,text=True,encoding='utf-8',start_new_session=True)
        proc.stdin.write(protocol['execution_prompt']);proc.stdin.close()
        while proc.poll() is None:
            time.sleep(.2)
            events=[]
            for line in (folder/'execution.jsonl').read_text(encoding='utf-8').splitlines():
                try:events.append(json.loads(line))
                except ValueError:pass
            web={e.get('item',{}).get('id') for e in events if e.get('item',{}).get('type')=='web_search'}
            with budget.db() as db:reserved=db.execute("select count(*) from calls where tool='web_search'").fetchone()[0]
            if len(web)>reserved:stop='web_search_without_reserved_budget'
            if time.monotonic()-started>=limits['timeout_seconds']:stop='time_budget_exhausted'
            if stop:
                if os.name=='posix':os.killpg(proc.pid,signal.SIGTERM)
                else:proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name=='posix':os.killpg(proc.pid,signal.SIGKILL)
                    else:proc.kill()
                break
        code=proc.wait()
    execution={'command':cmd,'exit_status':code,'elapsed_seconds':time.monotonic()-started,'stop_reason':stop}
    (folder/'execution-result.json').write_text(json.dumps(execution),encoding='utf-8')
    events=[]
    for line in (folder/'execution.jsonl').read_text(encoding='utf-8').splitlines():
        try:events.append(json.loads(line))
        except ValueError:pass
    from native_web_trace import NativeWebRecorder
    recorder=NativeWebRecorder(trace)
    native_thread=None
    for event in events:
        if event.get('type')=='thread.started':native_thread=event.get('thread_id')
        if native_thread:recorder.observe(native_thread,event,task_id=task_id)
    from native_web_trace import sync_native_reads
    sync_native_reads(trace,task_id,Path(os.environ['CODEX_HOME'])/'sessions',native_thread_id=native_thread)
    recorder.close(task_id)
    reads=[]
    for path in sorted(task_folder.glob('read-*.json')):
        row=json.loads(path.read_text(encoding='utf-8'));row['read_id']=len(reads)+1;reads.append(row)
    declaration_path=task_folder/'completion.json'
    declaration=json.loads(declaration_path.read_text(encoding='utf-8')) if declaration_path.exists() else None
    stop_record=resolve_research_stop(code,stop,trace.remaining(task_folder),declaration,trace.report(task_folder)['completion_attempts'])
    result={'execution_status':'completed' if code==0 else 'failed',
            'status':'completed' if code==0 and not any(x['result']['status'] in ('pending','missing_output') for x in reads) and stop_record['stop_reason'] not in ('reason_not_recorded','stop_declaration_rejected') else 'partial',
            'reads':reads,'stop_reason':stop_record['stop_reason'],
            'summary':(folder/'answer.txt').read_text(encoding='utf-8') if (folder/'answer.txt').exists() else '',
            'elapsed_seconds':execution['elapsed_seconds'],'video_candidates':payload['video_candidates']}
    structured=trace.report(task_folder) if declaration else trace.finish(task_id,stop_record['stop_reason'],stop_record['reason'],result['summary'] or 'No final report returned.',basis=stop_record['basis'])
    result={**structured,**result}
    (folder/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
