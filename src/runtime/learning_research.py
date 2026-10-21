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


PROMPT='''你是独立学习研究员，直接调用已开放的只读检索工具，不派子代理。
从真实轨迹的 BV 号或链接重新检索。video_candidates 供定位，多个候选结合目标依据自行选择。
先用廉价基础概览确认标题、作者、分P、简介与章节，再选择补读。
user_evaluation 仅是用户评价原文，goal_basis 是目标依据；自行判断需要核对的内容，不补造旧读取目的。
调用工具时填写 reading_purpose(targeted/explore) 和 reading_reason。定向须与目标高度相关；探索可旁支，转定向时说明与目标的关系。
可以自行选择网页搜索、B站资料、字幕、评论/楼中楼、弹幕、概览和定点画面。图片实际返回后才算看过。
共用本轮预算。基础概览最多3次，其余按 max_read_units 计数；失败也消耗预算。探索比例为上限。视频准备、抽帧、读取图各算一次调用，优先复用原轨迹中已有的有效资源标识。
网页搜索也占预算，搜索前用 learning_reads 的 declare_web_search 记录目的并预留一次额度，每次预留只对应一次搜索。不要调用命令行或修改文件。
既有材料足够时可以少量探索，但不要求耗尽预算。无新信息或额度不足就结束。只提出建议，不修改线上配置。
最终用中文给出核对结果、新信息、原结果的修正及仍缺的材料，并引用本轮 read_id；未能补读明确说明。'''


def autonomous_research(original,folder,limits,settings):
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
                  'timeout_seconds':limits['timeout_seconds']}
    trace=ResearchTrace(trace_config)
    goal=payload['original']['goal_basis']['text']
    task_id=trace.begin(goal,video=original.get('video'),source={'kind':'review_extension','original_task_id':original.get('task_id')})
    task_folder=trace.folder(task_id);budget=ReadBudget(task_folder/'budget.db')
    (folder/'gateway.json').write_text(json.dumps({'servers':servers,'folder':str(folder.resolve()),'trace':trace_config,'task_id':task_id}),encoding='utf-8')
    payload['budget']=limits
    (folder/'input.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    cmd=['codex','-a','never','-m',settings.get('reading_review',{}).get('model','gpt-6-astra'),
         '-c','model_reasoning_effort="medium"','-c','service_tier="default"',
         '-c','web_search="live"','-c','features.image_generation=false','-c','features.shell_tool=false']
    for name in cfg.get('mcp_servers',{}):cmd+=['-c',f'mcp_servers.{name}.enabled=false']
    for tool in sorted(ALLOWED|{'declare_web_search'}):
        cmd+=['-c',f'mcp_servers.learning_reads.tools.{tool}.approval_mode="approve"']
    python=settings.get('reading_review',{}).get('python',sys.executable)
    cmd+=['-c','mcp_servers.learning_reads.command='+json.dumps(python),
          '-c','mcp_servers.learning_reads.args='+json.dumps([str(Path(__file__).with_name('learning_research_mcp.py')),str(folder/'gateway.json')]),
          '-c','mcp_servers.learning_reads.tool_timeout_sec=120',
          'exec','--skip-git-repo-check','--sandbox','read-only','--json','--output-last-message',str(folder/'answer.txt'),'--','-']
    started=time.monotonic();stop=None;code=None
    with (folder/'execution.jsonl').open('x',encoding='utf-8') as out,(folder/'stderr.txt').open('x',encoding='utf-8') as err:
        proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=out,stderr=err,cwd=folder,text=True,encoding='utf-8',start_new_session=True)
        proc.stdin.write(PROMPT+'\n'+json.dumps(payload,ensure_ascii=False));proc.stdin.close()
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
    web_events=[e for e in events if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='web_search']
    # Native events lack the reservation's read_id; retain them without inferred pairing.
    if web_events:
        (task_folder/'unassociated-native-events.json').write_text(
            json.dumps(web_events,ensure_ascii=False,indent=2),encoding='utf-8')
    for path in task_folder.glob('read-*.json'):
        row=json.loads(path.read_text(encoding='utf-8'))
        if row['result']['status']=='pending':
            row['result']={'status':'missing_output','images':[]};row['elapsed_seconds']=None
            row['missing_reason']='native_event_read_id_unavailable' if row['tool']=='web_search' else 'no_completion_recorded'
            path.write_text(json.dumps(row,ensure_ascii=False),encoding='utf-8')
    reads=[]
    for path in sorted(task_folder.glob('read-*.json')):
        row=json.loads(path.read_text(encoding='utf-8'));row['read_id']=len(reads)+1;reads.append(row)
    result={'status':'completed' if code==0 else 'partial','reads':reads,'stop_reason':stop or ('completed' if code==0 else 'model_failed'),
            'summary':(folder/'answer.txt').read_text(encoding='utf-8') if (folder/'answer.txt').exists() else '',
            'elapsed_seconds':execution['elapsed_seconds'],'video_candidates':payload['video_candidates']}
    structured=trace.finish(task_id,result['stop_reason'],stop or 'model_execution_ended',result['summary'] or 'No final report returned.')
    result={**structured,**result}
    (folder/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
