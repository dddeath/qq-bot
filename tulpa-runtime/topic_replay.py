"""Offline chronological replay. Providers return decisions; there is no QQ sender."""
import datetime
import json
import random
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from topic_state import TopicState
from topic_dialogue import interpret,dialogue_context


def write_json(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def new_run(root):
    path=Path(root)/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-'+uuid.uuid4().hex[:6])
    path.mkdir(parents=True,exist_ok=False)
    return path


def replay(messages, maintainer, main, output_root, *, state=None, seed=7, final_idle=True, member_profiles=None):
    state=state or TopicState()
    run=new_run(output_root)
    write_json(run/'input.json',messages)
    member_profiles=member_profiles or {}
    write_json(run/'member-profiles.json',member_profiles)
    write_json(run/'config.json',dict(group_limits=asdict(state.group_limits),topic_limits=asdict(state.topic_limits),
               message_chars=state.message_chars,max_topics=state.max_topics,idle_seconds=state.idle_seconds,
               stale_grace_seconds=state.stale_grace_seconds,participation_probability=state.participation_probability,
               mention_reply_probability=state.mention_reply_probability,context_reply_probability=state.context_reply_probability,
               bot_id=state.bot_id,seed=seed))
    rows=[];rng=random.Random(seed);seen=set();last=-float('inf')

    def recycle(now):
        for tid in sorted(state.expired_topics(now),key=lambda t:state.topics[t]['last_update']):
            deadline=state.topics[tid]['last_update']+state.idle_seconds
            state.retire_topic(tid,deadline,reason='idle',actor='main',pending_disposition='cancel')

    for original in messages:
        if original['at']<last:
            raise ValueError('input must be chronological')
        last=original['at']
        if original['id'] in seen:continue
        seen.add(original['id'])
        target=original.get('historical_reply_to') if original.get('is_self') else None
        if target:
            for q in state.view(last)['queue']:
                if q['message_id']==target and q['status'] in ('queued','responding','waiting_external','needs_revision'):
                    state.complete_reply(q['id'],last,outcome='historical_confirmed')
        recycle(last)
        m=state.receive(original);view=state.view(last)
        visible_senders={x['sender'] for x in view['messages']}
        profiles={qq:{key:profile[key] for key in ('participant_type','source') if key in profile}
                  for qq,profile in member_profiles.get(m.get('group'),{}).items() if qq in visible_senders}
        request=dict(message=m,topics=view['topics'],recent_messages=view['messages'],now=last,
                     dialogue_context=dialogue_context(m,view),participant_profiles=profiles)
        participant_type='self' if m.get('is_self') else profiles.get(m['sender'],{}).get('participant_type','unknown')
        start=time.monotonic();record=dict(message=m,assignment=None,decision=None,main_action=None,participant_type=participant_type)
        try:
            d=maintainer(request)
            direct,should_interject=interpret(d,m,view['messages'])
            reference=d.get('reply_to_message_id')
            record['reference_status']=('none' if reference is None else 'visible' if any(
                x['id']==reference for x in view['messages']) else 'missing_content')
            tid=d.get('topic_id')
            if tid is not None and tid not in state.topics:raise ValueError('unknown topic')
            record['maintainer_result']=d
            record['maintainer_elapsed_s']=round(time.monotonic()-start,4)
            if tid is None:
                start_main=time.monotonic()
                action=main(dict(**request,maintainer_result=d,queue=view['queue']))
                record['main_action']=action
                record['main_elapsed_s']=round(time.monotonic()-start_main,4)
                if action['action']=='create':
                    retire=action.get('retire_topic_id')
                    if retire:state.retire_topic(retire,last,reason='main_replacement',actor='main')
                    tid=state.create_topic(action['title'],last,actor='main')['id']
                elif action['action']=='reuse':
                    tid=action['topic_id']
                    if tid not in state.topics:raise ValueError('unknown main topic')
                elif action['action']!='defer':raise ValueError('invalid lifecycle action')
            if tid:
                record['assignment']=dict(topic_id=tid,title=state.topics[tid]['title'],maintainer_id=state.topics[tid]['maintainer_id'])
                record['decision']=state.assign(m['id'],tid,should_reply=should_interject,direct=direct,now=last,draw=rng.random(),reason=d.get('reason',''))
            else:
                source,probability=state.response_policy(m,should_reply=should_interject,direct=direct)
                record['decision']=dict(action='defer',reason='main deferred topic creation',
                                        response_source=source,probability=probability,draw=None)
            record['queue_checks']=[dict(id=q['id'],**state.check_reply(q['id'],last)) for q in state.view(last)['queue']]
        except Exception as e:
            record['error']=dict(type=type(e).__name__,message=str(e))
        rows.append(record)
        write_json(run/'results.partial.json',dict(messages=rows,qq_sends=0))
    if messages and final_idle:recycle(last+state.idle_seconds)
    report=dict(messages=rows,final_state=state.view(last+state.idle_seconds if final_idle and messages else last),
                qq_sends=0,simulation='decision_only_no_answers_or_tool_execution',
                errors=sum('error' in r for r in rows))
    report['response_sources']={}
    report['participant_types']={}
    for kind in ('human','ai','unknown','self'):
        items=[r for r in rows if r['participant_type']==kind]
        report['participant_types'][kind]=dict(messages=len(items),
            queued=sum((r.get('decision') or {}).get('action')=='reply' for r in items),errors=sum('error' in r for r in items))
    for source in ('mention','context','participation','none','self','error'):
        items=[r for r in rows if (r.get('decision') or {}).get('response_source','error')==source]
        report['response_sources'][source]=dict(messages=len(items),
            queued=sum((r.get('decision') or {}).get('action')=='reply' for r in items),
            deferred=sum((r.get('decision') or {}).get('action')=='defer' for r in items))
    write_json(run/'results.json',report)
    (run/'report.md').write_text(render_report(report),encoding='utf-8')
    return run


def render_report(report):
    def cell(value):return str(value).replace('|','\\|').replace('\n','<br>')
    lines=['# 群聊记录离线回放','',
           '原始消息按接收时间推进；仅产生分配、搭话与维护决策，没有生成群回复或执行搜索、生图。模型耗时为离线调用耗时。历史发送回执仅在对应机器人消息到达时关闭其原回应目标，标记historical_confirmed；这不代表新策略已发出回复。',
           '',f"消息数：{len(report['messages'])}；错误：{report['errors']}；QQ发送：{report['qq_sends']}。",'',
           '## 回应来源汇总','','| 来源 | 消息数 | 入队数 | 暂缓归属 |','|---|---|---|---|']
    labels={'mention':'QQ实际@','context':'上下文指向','participation':'普通主动插话','none':'未建议回应','self':'机器人自身','error':'错误'}
    for source,counts in report['response_sources'].items():
        lines.append(f"| {labels[source]} | {counts['messages']} | {counts['queued']} | {counts['deferred']} |")
    kinds={'human':'真人（已标记）','ai':'另一 AI','unknown':'未标记成员','self':'本机器人'}
    lines+=['','## 成员类型汇总','','| 成员类型 | 消息数 | 入队数 | 错误数 |','|---|---|---|---|']
    for kind,counts in report['participant_types'].items():
        lines.append(f"| {kinds[kind]} | {counts['messages']} | {counts['queued']} | {counts['errors']} |")
    lines+=['','## 分配和决策','', '| 时间 UTC+8 | 发言者及成员类型 | 原消息 | 分配 | 发言对象 | 交流意图 | 承接消息 | 建议主动插话 | 判断耗时(秒) | 回应来源 | 采用概率 | 抽样值 | 排队结果 | 依据 |','|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for r in report['messages']:
        m=dict(r['message']);m['sender']+=f" ({kinds[r['participant_type']]})"
        at=datetime.datetime.fromtimestamp(m['at'],datetime.timezone(datetime.timedelta(hours=8))).strftime('%H:%M:%S')
        a=r.get('assignment') or {};d=r.get('decision') or {}
        lines.append('| '+' | '.join(cell(x) for x in [at,m['sender'],m['text'],a.get('topic_id','未归属')+' '+a.get('title',''),r.get('maintainer_result',{}).get('addressee',''),r.get('maintainer_result',{}).get('intent',''),r.get('maintainer_result',{}).get('reply_to_message_id',''),r.get('maintainer_result',{}).get('should_interject',''),r.get('maintainer_elapsed_s',''),labels.get(d.get('response_source'),'错误'),d.get('probability',''),d.get('draw',''),d.get('action','error'),d.get('reason',r.get('error',''))])+' |')
    lines+=['','## 话题与维护者生命周期','','| 时间 UTC+8 | 动作 | 话题/窗口 | 维护者 | 原因/淘汰消息 |','|---|---|---|---|---|']
    for e in report['final_state']['maintenance']:
        at=datetime.datetime.fromtimestamp(e['at'],datetime.timezone(datetime.timedelta(hours=8))).strftime('%H:%M:%S')
        lines.append('| '+' | '.join(cell(v) for v in [at,e['event'],e.get('topic_id',e.get('scope','')),e.get('maintainer_id',''),e.get('reason',e.get('message_ids',''))])+' |')
    lines+=['','## 最终话题状态','']
    for t in report['final_state']['topics']:
        lines.append(f"- {t['id']} {t['title']}：维护者 {t['maintainer_id']}；版本 {t['version']}；工作窗口 {len(t['messages'])} 条。")
    lines+=['','话题空闲回收时，主控制层将尚未执行的回应目标标记cancelled并保留原因；回放不会把计划生成记作已经回复。']
    return '\n'.join(lines)+'\n'
