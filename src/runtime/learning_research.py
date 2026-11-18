"""Independent learning research: native model tools, bounded reads, immutable source traces."""
import datetime as dt
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import tomllib
from pathlib import Path

from knowledge_tools import RetrievalBinding
from reading_budget import ReadBudget, reading_budget_exhausted, OVERVIEW
from reading_tools import ALLOWED


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
    # Candidate identifiers are metadata; evidence is disclosed from the archive on demand.
    calls=[r.get('arguments',r.get('raw_call',{}).get('payload',{})) for r in original.get('reads',[])]
    identifiers=json.dumps([original.get('video'),calls],ensure_ascii=False)
    candidates=list(dict.fromkeys(re.findall(r'BV[0-9A-Za-z]{10}',identifiers)))
    return {'video_candidates':candidates,
            'candidate_basis':'Identifiers in recorded calls; candidate presence does not establish a successful read.'}


def resolve_research_stop(exit_status, host_stop, remaining, declaration, completion_attempts=None):
    if host_stop:return dict(stop_reason=host_stop,reason=host_stop,basis='executor_control')
    if exit_status != 0:return dict(stop_reason='model_failed',reason='model_process_failed',basis='executor_process')
    if declaration:return dict(stop_reason=declaration['stop_reason'],reason=declaration['reason'],basis='model_declared')
    if completion_attempts:
        return dict(stop_reason='stop_declaration_rejected',reason=completion_attempts[-1]['error'],basis='executor_validation')
    if reading_budget_exhausted(remaining):return dict(stop_reason='budget_exhausted',reason='read_budget_depleted',basis='executor_budget')
    return dict(stop_reason='reason_not_recorded',reason='model_ended_without_stop_declaration',basis='missing')


def research_summary(folder, declaration):
    """Keep a recorded conclusion available when the final assistant text is absent."""
    answer = folder / 'answer.txt'
    text = answer.read_text(encoding='utf-8') if answer.exists() else ''
    if text.strip():return text, 'model_final'
    if declaration:return declaration['conclusion'], 'completion_conclusion'
    return '', 'missing'


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


def research_servers(config, settings):
    """Resolve read services, taking knowledge scope from the host tool snapshot."""
    from copy import deepcopy
    servers = {k: deepcopy(v) for k, v in config.get('mcp_servers', {}).items()
               if k in ('bilibili_readonly', 'video_frames', 'external_image') and v.get('command')}
    snapshot_path = settings.get('tool_snapshot')
    if snapshot_path:
        snapshot = json.loads(Path(snapshot_path).read_text(encoding='utf-8'))
        selected = RetrievalBinding.select(snapshot['servers'], ambiguity='research_knowledge_provider_must_be_unique')
        if selected is None:
            raise ValueError('research_knowledge_provider_must_be_unique')
        name, provider = selected.name, selected.server
        if not provider.get('command') or provider.get('url'):
            raise ValueError('research_knowledge_requires_stdio')
        env = provider.get('env', {})
        for field, key in [('account', 'QQ_KNOWLEDGE_ACCOUNT'), ('group', 'QQ_KNOWLEDGE_GROUP')]:
            if settings.get(field) is not None and str(settings[field]) != env.get(key):
                raise ValueError('research_knowledge_scope_mismatch')
        if name in servers:
            raise ValueError('research_knowledge_server_name_conflict')
        server = deepcopy(provider)
        server.pop('reading_trace', None)
        server['tools'] = [tool for tool in server['tools'] if tool in ALLOWED]
        servers[name] = server
    return servers


def autonomous_research(original,folder,limits,settings, *, task_mode="learning", task_context=None, needs=None, deadline=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    cfg=tomllib.loads((Path(os.environ['CODEX_HOME'])/'config.toml').read_text())
    servers=research_servers(cfg, settings)
    if not servers:raise RuntimeError('learning_read_tools_not_configured')
    node=settings.get('node')
    for name,server in servers.items():
        if name=='bilibili_readonly' and settings.get('bilibili_provider',{}).get('call_script'):
            server['command']=settings['bilibili_provider'].get('node',server['command'])
            server['args']=[str(Path(settings['bilibili_provider']['call_script']).with_name('server.mjs'))]
        if name in ('bilibili_readonly', 'video_frames', 'external_image'):
            server['env']={**server.get('env',{}),**settings.get('env',{})}
    external=Path(__file__).with_name('external_image.py')
    if external.exists():
        servers['external_image']={'command':settings.get('reading_review',{}).get('python',sys.executable),'args':[str(external)]}
    from research_trace import ResearchTrace
    payload=research_input(original)
    from review_materials import ReviewMaterials
    materials=ReviewMaterials.create(folder/'materials',{'original':original})
    payload['review_materials_directory']=str(materials.root)
    trace_config={'root':str(folder/'tasks'),'scope':original.get('context',{}).get('audit_scope','learning'),
                  'max_read_units':limits['max_read_units'],'exploration_budget_ratio':limits['exploration_budget_ratio'],
                  'timeout_seconds':limits['timeout_seconds'],
                  'native_sessions_directory':str(Path(os.environ['CODEX_HOME'])/'sessions')}
    if deadline is not None:trace_config['deadline']=deadline
    trace=ResearchTrace(trace_config)
    from reading_review_runtime import review_input
    goal=review_input(original)['goal_basis']['text']
    python=settings.get('reading_review',{}).get('python',sys.executable)
    context = task_context if task_context is not None else {
        'review_materials_directory':str(materials.root),
        'review_instructions':'先用 list_review_materials 查目录，读取原目标、停止结论与 research_feedback 中的群回复和评价关联。先选具体核验点，再按相关性展开原证据并执行补读，给实际补读与结论留出时间。read_review_material 用 pointer 或 next_offset 渐进展开；图片用 read_review_image。原证据读取不占联网补读次数，仍受当前补读时间限制；时间不足时用已取得材料收尾并声明停止原因。'}
    arguments={'goal':goal,'video':original.get('video'),'source':original.get('source') or {'kind':'review_extension' if task_mode=='learning' else 'chat_replay','original_task_id':original.get('task_id')},'task_mode':task_mode,'context':context,'budget':limits,'needs':needs or []}
    gateway={'servers':servers,'folder':str(folder.resolve()),'trace':trace_config}
    (folder/'gateway.json').write_text(json.dumps(gateway),encoding='utf-8')
    import asyncio
    async def begin():
        call=begin_research_mcp(folder/'gateway.json',arguments,python)
        return await asyncio.wait_for(call,max(.001,deadline-time.time())) if deadline is not None else await call
    protocol=asyncio.run(begin())
    task_id=protocol['task_id'];task_folder=trace.folder(task_id);budget=ReadBudget(task_folder/'budget.db')
    gateway['task_id']=task_id
    (folder/'gateway.json').write_text(json.dumps(gateway),encoding='utf-8')
    (folder/'mcp-input.json').write_text(json.dumps(arguments,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'mcp-result.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'prompt.txt').write_text(protocol['execution_prompt'],encoding='utf-8')
    from model_input_audit import write_audit
    write_audit(folder, protocol['execution_prompt'], surface='learning_research_prompt')
    payload['budget']=limits
    (folder/'input.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    cmd=[*settings.get('reading_review',{}).get('command',['codex']),'-a','never','-m',settings.get('reading_review',{}).get('model','gpt-6-astra'),
         '-c','model_reasoning_effort='+json.dumps(settings.get('reading_review',{}).get('reasoning_effort','medium')),'-c','service_tier="default"',
         '-c','web_search="live"','-c','features.image_generation=false','-c','features.shell_tool=false',
         '-c','features.mcp_tool_list_changed=true']
    for name in cfg.get('mcp_servers',{}):cmd+=['-c',f'mcp_servers.{name}.enabled=false']
    for tool in sorted(ALLOWED|{'begin_reading_task','declare_native_read','finish_reading_task'}):
        cmd+=['-c',f'mcp_servers.learning_reads.tools.{tool}.approval_mode="approve"']
    python=settings.get('reading_review',{}).get('python',sys.executable)
    from review_materials_mcp import cli_arguments
    cmd+=cli_arguments(materials.root,python,time.time()+trace.remaining(task_folder)['seconds'])
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
            if trace.remaining(task_folder)['seconds']<=0:stop='time_budget_exhausted'
            if stop:
                if os.name=='posix':os.killpg(proc.pid,signal.SIGTERM)
                else:proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name=='posix':os.killpg(proc.pid,signal.SIGKILL)
                    else:proc.kill()
                break
        code=proc.wait()
    execution_status=('timed_out' if stop=='time_budget_exhausted' else
                      'cancelled' if stop else 'completed' if code==0 else 'failed')
    execution={'command':cmd,'exit_status':code,'execution_status':execution_status,
               'elapsed_seconds':time.monotonic()-started,'stop_reason':stop}
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
    summary,summary_source=research_summary(folder,declaration)
    result={'execution_status':execution_status,
            'status':'completed' if code==0 and not stop and declaration and summary_source=='model_final' and not any(x['result']['status'] in ('pending','missing_output') for x in reads) else 'partial',
            'reads':reads,'stop_reason':stop_record['stop_reason'],
            'stop_record':stop_record,'summary':summary,'summary_source':summary_source,
            'elapsed_seconds':execution['elapsed_seconds'],'video_candidates':payload['video_candidates']}
    structured=trace.report(task_folder) if declaration else trace.finish(task_id,stop_record['stop_reason'],stop_record['reason'],result['summary'] or 'No final report returned.',basis=stop_record['basis'])
    result={**structured,**result}
    (folder/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
