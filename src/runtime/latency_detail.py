"""Read-only correlation of CLI delivery logs and native Codex tool lifecycles."""
import datetime
import json
import re
import math
import statistics
import uuid
from pathlib import Path

def delta(end, start):
    if not isinstance(end,(int,float)) or not isinstance(start,(int,float)): return None
    return round(end-start,6) if end>=start else None


def payload(item):
    result=item.get('result') or {}
    if isinstance(result.get('structured_content'),dict): return result['structured_content']
    for part in result.get('content',[]):
        if part.get('type')=='text':
            try: return json.loads(part['text'])
            except (ValueError,TypeError): pass
    return {}


def seconds(value):
    if isinstance(value, (float, int)): return value
    try: return datetime.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, AttributeError): return None


def output_text(value):
    if isinstance(value, str): return value
    if isinstance(value, list): return '\n'.join(x.get('text', '') for x in value if isinstance(x, dict))
    return ''


def native_lifecycles(records):
    tools = []; calls = {}; cells = {}; scope = 0
    compactions = []; compact_start = None; contexts = []; context_usage=[]
    for row in records:
        p = row.get('payload', {}); kind = p.get('type'); at = seconds(row.get('timestamp'))
        if kind == 'task_started':
            if compact_start is not None: compactions.append(dict(event='incomplete',start=compact_start,end=None,duration_s=None))
            scope += 1; cells = {}; calls = {}; compact_start = None
        if row.get('type') == 'turn_context':
            contexts.append({'at':at,'model':p.get('model'),'effort':p.get('effort',p.get('reasoning_effort'))})
        if kind=='token_count' and isinstance(p.get('info'),dict):
            info=p['info'];usage=info.get('last_token_usage') or {}
            context_usage.append(dict(at=at,model_context_window=info.get('model_context_window'),
                **{k:usage.get(k) for k in ('input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens','total_tokens')}))
        event_name = str(kind or row.get('type', ''))
        if 'compact' in event_name.lower():
            if event_name.endswith(('started', 'start')): compact_start = at
            else:
                compactions.append(dict(event=event_name, start=compact_start, end=at, duration_s=delta(at,compact_start)))
                compact_start = None
        if row.get('type') != 'response_item': continue
        cid = p.get('call_id')
        if kind in ('function_call', 'custom_tool_call'):
            body = p.get('arguments', p.get('input', '')); name = p.get('name', '')
            span = None
            if name.split('.')[-1] == 'wait':
                try: args = json.loads(body) if isinstance(body, str) else body
                except ValueError: args = {}
                span = cells.get(str(args.get('cell_id')))
                if span:
                    span['wait_count'] += 1
                    span['phases'].append(dict(phase='wait',at=at,call_id=cid))
                    gap = delta(at, span.get('last_output'))
                    if gap is not None: span['observation_gap_s'] += gap
            else:
                labels = []
                if re.search(r'(?:web__run|web\.run)\s*\(', str(body)) or name in ('web.run', 'web__run'): labels.append('search')
                if re.search(r'(?:image_gen__imagegen|image_gen\.imagegen)\s*\(', str(body)) or 'imagegen' in name: labels.append('image_generation')
                if labels:
                    span = dict(id=f'{scope}:{cid}', kinds=labels, start=at, end=None,
                                duration_s=None, status='incomplete', outcome='unknown', wait_count=0, observation_gap_s=0,
                                phases=[dict(phase='request',at=at,call_id=cid)])
                    tools.append(span)
            if span: calls[cid] = span
        elif kind in ('function_call_output', 'custom_tool_call_output') and cid in calls:
            span = calls.pop(cid); text = output_text(p.get('output'))
            running = re.search(r'Script running with cell ID\s+([^\s]+)', text)
            span['last_output'] = at
            span['phases'].append(dict(phase='yield' if running else 'result',at=at,call_id=cid))
            if running: cells[running.group(1)] = span
            else:
                span.update(end=at, duration_s=delta(at, span['start']), status='completed')
                span['outcome']='error_observed' if re.search(r'Failed to fetch|not accessible via this tool|Script failed|"isError"\s*:\s*true',text,re.I) else 'no_error_marker'
                for cell in list(cells):
                    if cells[cell] is span: del cells[cell]
    for span in tools:
        span.pop('last_output', None)
        span['observation_gap_s']=round(span['observation_gap_s'],6)
    if compact_start is not None: compactions.append(dict(event='incomplete',start=compact_start,end=None,duration_s=None))
    return {'tools': tools, 'compactions':compactions, 'contexts':contexts, 'context_usage':context_usage,
            'compaction_observation':'observed' if compactions else 'not_observed'}


def stats(values):
    values = sorted(v for v in values if v is not None)
    return dict(n=len(values), mean=round(statistics.mean(values),6) if values else None,
                **{f'p{p}':values[max(0, math.ceil(len(values)*p/100)-1)] if values else None for p in (50,90,95,99)},
                max=max(values) if values else None)


def overlap(intervals, start, end):
    if start is None or end is None: return None
    clips=sorted((max(a,start),min(b,end)) for a,b in intervals if a is not None and b is not None and min(b,end)>max(a,start))
    total=0; until=start
    for a,b in clips:
        total+=max(0,b-max(until,a)); until=max(until,b)
    return round(total,6)


def build_report(records, native_records=(), *, inbox=(), tail_seconds=60):
    """Correlate stable session/event IDs; overlap labels are observations, not causality."""
    native = native_lifecycles(native_records)
    messages={}; starts={}; plans={}; seen=set(); unmatched=[]
    def message(sid, msg):
        key=(sid,msg.get('id'))
        if key not in messages:
            qq=msg.get('timestamp')
            messages[key]=dict(session_id=sid,event_id=key[1],qq_message_id=msg.get('onebot_message_id'),
                timeline=dict(qq_sent=qq/1000 if isinstance(qq,(int,float)) else None,
                              receiver_received=msg.get('received_at'),host_delivered=None),plans=[],replies=[],attempts=[])
        return messages[key]
    for m in inbox:
        if not m.get('is_self'): message(m.get('session_id'),m)
    for row in records:
        at=row.get('observed_at'); ev=row.get('event',row); i=ev.get('item',{}); typ=ev.get('type'); tool=i.get('tool')
        args=i.get('arguments') or {}; sid=args.get('session_id'); key=i.get('id')
        if typ=='thread.started': starts={}
        if typ=='item.started': starts[key]=at; continue
        if typ!='item.completed' or not tool: continue
        r=payload(i)
        if tool in ('wait_chat_messages','get_chat_session'):
            sid=r.get('session_id') or r.get('session',{}).get('id') or sid
            for m in r.get('messages',r.get('context',{}).get('messages',[])):
                if m.get('is_self'): continue
                out=message(sid,m)
                if out['timeline']['host_delivered'] is None: out['timeline']['host_delivered']=at
        elif tool=='plan_chat_reply':
            target=r.get('decision',{}).get('target_event_id',args.get('target_event_id'))
            plan=dict(id=r.get('plan_id'),start=starts.get(key),end=at,target_event_id=target,state=r.get('state'),error_code=r.get('error_code'),reason=r.get('reason'))
            if r.get('plan_id'): plans[(sid,r['plan_id'])]=plan
            if target is not None: message(sid,{'id':target})['plans'].append(plan)
        elif tool=='send_chat_reply':
            plan=plans.get((sid,args.get('plan_id')),{});target=plan.get('target_event_id')
            attempt=dict(start=starts.get(key),end=at,state=r.get('state'),error_code=r.get('error_code'),reason=r.get('reason'))
            if target is not None: message(sid,{'id':target})['attempts'].append(attempt)
            else: unmatched.append(dict(session_id=sid,plan_id=args.get('plan_id'),**attempt))
            for bubble in r.get('bubbles',[]):
                receipt=bubble.get('receipt') or {}; res=receipt.get('result') or {}; mid=res.get('message_id')
                if mid is None or (sid,str(mid)) in seen: continue
                seen.add((sid,str(mid)))
                target=res.get('reply_to_event_id',target)
                message(sid,{'id':target})['replies'].append(dict(message_id=mid,kind=bubble.get('expression',{}).get('kind'),
                    send_started=starts.get(key),receipt_at=res.get('timestamp'),host_observed=at,
                    state=bubble.get('state',r.get('state'))))
    for m in messages.values():
        t=m['timeline']; replies=sorted(m['replies'],key=lambda r:r.get('receipt_at') or float('inf'))
        m['replies']=replies
        first=replies[0].get('receipt_at') if replies else None; last=replies[-1].get('receipt_at') if replies else None
        t.update(first_reply_receipt=first,last_reply_receipt=last)
        m['status']='replied' if replies else 'send_attempt_without_receipt' if m['attempts'] else 'delivered_without_reply' if t['host_delivered'] is not None else 'receiver_only'
        m['first_reply_s']=delta(first,t['qq_sent']);m['last_reply_s']=delta(last,t['qq_sent'])
        m['receiver_to_delivery_s']=delta(t['host_delivered'],t['receiver_received'])
        m['delivered_to_first_reply_s']=delta(first,t['host_delivered'])
        window=(t['receiver_received'],first)
        m['tool_intervals']=[]
        for span in native['tools']:
            amount=overlap([(span['start'],span['end'])],*window)
            if amount: m['tool_intervals'].append(dict(id=span['id'],kinds=span['kinds'],overlap_s=amount))
        m['tool_overlap_s']=overlap([(s['start'],s['end']) for s in native['tools']],*window)
        m['compaction_overlap_s']=overlap([(s['start'],s['end']) for s in native['compactions']],*window)
        m['tail_labels']=[]
        if m['first_reply_s'] is not None and m['first_reply_s']>=tail_seconds:
            labels=m['tail_labels']
            for kind in ('search','image_generation'):
                if any(kind in s['kinds'] for s in m['tool_intervals']): labels.append(kind+'_overlap')
            if m['compaction_overlap_s']: labels.append('compaction_overlap')
            if any(x.get('error_code')=='stale' or x.get('reason')=='stale' for x in m['plans']+m['attempts']): labels.append('stale_replanning')
            if (m['receiver_to_delivery_s'] or 0)>=tail_seconds/2: labels.append('delivery_queue')
            if replies and (delta(first,replies[0]['send_started']) or 0)>=tail_seconds/2: labels.append('send_receipt_wait')
            if not labels: labels.append('unattributed_host_interval')
        m['missing_timestamps']=[k for k,v in t.items() if v is None]
    result=list(messages.values())
    result.sort(key=lambda m:(m['timeline']['receiver_received'] or float('inf'),str(m['event_id'])))
    return dict(schema_version=1,messages=result,**native,unmatched_send_attempts=unmatched,
        summary=dict(messages=len(result),replied=sum(bool(m['replies']) for m in result),
                     first_reply_s=stats(m['first_reply_s'] for m in result),last_reply_s=stats(m['last_reply_s'] for m in result),
                     tail_threshold_s=tail_seconds,tail_count=sum(bool(m['tail_labels']) for m in result)),
        notes=['Tool lifecycle includes host observation/polling gaps; backend compute time is not exposed.',
               'Interval overlap does not prove which message caused a tool call; overlapping spans are unioned.',
               'Not observed compaction is not proof of no internal compression. Missing timestamps stay null.',
               'No reply is not automatically a failed reply. QQ client display time is not available.'])


def save_report(root, report):
    directory=Path(root)/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-'+uuid.uuid4().hex[:6])
    directory.mkdir(parents=True,exist_ok=False)
    (directory/'timeline.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    s=report['summary']; lines=['# 消息时延报告','',f"消息：{s['messages']}；已回复：{s['replied']}；长尾阈值：{s['tail_threshold_s']} 秒；长尾：{s['tail_count']}。",'',
        '首条回复耗时（秒，QQ 时间至服务端回执）：',json.dumps(s['first_reply_s'],ensure_ascii=False),'',
        f"搜索/生图生命周期：{len(report['tools'])}；压缩观测：{report['compaction_observation']}。",'',
        '## 最慢的已回复消息','', '| 会话 / 事件 | 首条秒数 | 末条秒数 | 标签 |','|---|---:|---:|---|']
    for m in sorted(report['messages'],key=lambda x:x['first_reply_s'] or 0,reverse=True)[:20]:
        if m['first_reply_s'] is not None: lines.append(f"| {m['session_id']} / {m['event_id']} | {m['first_reply_s']} | {m['last_reply_s']} | {', '.join(m['tail_labels'])} |")
    lines+=['','## 观测边界','']+['- '+n for n in report['notes']]
    (directory/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return directory


def load_jsonl(path):
    rows=[]; invalid=0
    with Path(path).open(encoding='utf-8-sig') as stream:
        for line in stream:
            try: rows.append(json.loads(line))
            except ValueError: invalid+=1
    return rows, invalid


def main():
    import argparse
    import sqlite3
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace',action='append',required=True,type=Path)
    parser.add_argument('--native',type=Path)
    parser.add_argument('--inbox-db',type=Path)
    parser.add_argument('--session',action='append',help='Optional exact Tulpa session ID filter')
    parser.add_argument('--tail-seconds',type=float,default=60)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args(); records=[]; sources=[]
    for path in args.trace:
        rows,bad=load_jsonl(path); records+=rows
        sources.append(dict(path=str(path),rows=len(rows),invalid_lines=bad))
    records.sort(key=lambda r:r.get('observed_at') or 0)
    native=[]
    if args.native:
        native,bad=load_jsonl(args.native);sources.append(dict(path=str(args.native),rows=len(native),invalid_lines=bad))
    sessions=set(args.session or [])
    if not sessions:
        sessions={r.get('event',{}).get('item',{}).get('arguments',{}).get('session_id') for r in records}
        sessions.discard(None)
    inbox=[]
    if args.inbox_db:
        with sqlite3.connect(args.inbox_db.resolve().as_uri()+'?mode=ro',uri=True) as db:
            for ident,sid,body in db.execute('SELECT id,session_id,payload FROM chat_inbox'):
                if sid not in sessions: continue
                m=json.loads(body);m.update(id=ident,session_id=sid);inbox.append(m)
    if args.session:
        records=[r for r in records if not r.get('event',{}).get('item',{}).get('tool') or r['event']['item'].get('arguments',{}).get('session_id') in sessions]
    report=build_report(records,native,inbox=inbox,tail_seconds=args.tail_seconds)
    report['sources']=sources;report['generated_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    directory=save_report(args.output,report)
    print(json.dumps(dict(directory=str(directory),summary=report['summary']),ensure_ascii=False))


if __name__=='__main__': main()
