"""Passive Codex JSONL latency analysis. No network calls or message sending."""
import argparse, datetime, json, statistics, uuid
from pathlib import Path

def payload(item):
    r=item.get('result') or {}
    if r.get('structured_content') is not None:return r['structured_content']
    for c in r.get('content',[]):
        if c.get('type')=='text':
            try:return json.loads(c['text'])
            except (ValueError,TypeError):pass
    return {}

def delta(end,start):
    if not isinstance(end,(float,int)) or not isinstance(start,(float,int)):return None
    return round(end-start,6) if end>=start else None

def analyze(records):
    messages={}; starts={}; plans={}; replies=[]; rejected=[]; seen=set()
    for row in records:
        at=row.get('observed_at');ev=row.get('event',row);i=ev.get('item',{});tool=i.get('tool');args=i.get('arguments') or {};sid=args.get('session_id');key=i.get('id')
        if ev.get('type')=='item.started':starts[key]=at;continue
        if ev.get('type')!='item.completed' or not tool:continue
        r=payload(i)
        if tool in ('wait_chat_messages','get_chat_session'):
            sid=r.get('session_id') or r.get('session',{}).get('id') or sid
            for m in r.get('messages',r.get('context',{}).get('messages',[])):
                if not m.get('is_self'):messages.setdefault((sid,m['id']),{'message':m,'delivery':at})
        elif tool=='plan_chat_reply' and r.get('plan_id'):
            plans[r['plan_id']]={'start':starts.get(key),'end':at,'target':r.get('decision',{}).get('target_event_id',args.get('target_event_id'))}
        elif tool=='send_chat_reply':
            if r.get('state')!='SUCCEEDED':rejected.append({'state':r.get('state'),'error_code':r.get('error_code'),'plan_id':args.get('plan_id'),'observed_at':at})
            p=plans.get(args.get('plan_id'),{})
            for b in r.get('bubbles',[]):
                receipt=b.get('receipt') or {};res=receipt.get('result') or {};mid=res.get('message_id')
                if mid is None or (sid,str(mid)) in seen:continue
                seen.add((sid,str(mid)))
                target=res.get('reply_to_event_id',p.get('target'));m=messages.get((sid,target),{});msg=m.get('message',{})
                qq=msg.get('timestamp');qq=qq/1000 if isinstance(qq,(float,int)) else None
                received=msg.get('received_at');delivery=m.get('delivery');sent=res.get('timestamp');sendstart=starts.get(key)
                stages={'qq_to_receiver':delta(received,qq),'receiver_to_host_delivery':delta(delivery,received),'host_delivery_to_plan':delta(p.get('start'),delivery),'plan_tool':delta(p.get('end'),p.get('start')),'plan_to_send':delta(sendstart,p.get('end')),'send_to_receipt':delta(sent,sendstart),'receipt_to_host':delta(at,sent)}
                replies.append({'session_id':sid,'target_event_id':target,'message_id':mid,'kind':b.get('expression',{}).get('kind'),'state':b.get('state',r.get('state')),'segments_s':stages,'server_e2e_s':delta(sent,qq),'receiver_to_receipt_s':delta(sent,received),'operation_to_receipt_s':delta(sent,receipt.get('created')),'client_display_s':None})
    def stats(values):
        v=sorted(x for x in values if x is not None)
        return {'n':len(v),'mean':round(statistics.mean(v),4),'p50':round(statistics.median(v),4),'max':max(v)} if v else {'n':0,'mean':None,'p50':None,'max':None}
    first=[];groups=set()
    for r in replies:
        k=(r['session_id'],r['target_event_id'])
        if k not in groups:groups.add(k);first.append(r)
    return {'replies':replies,'rejections':rejected,'summary':{'replied_targets':len(first),'server_e2e_s':stats(r['server_e2e_s'] for r in first),'receiver_to_receipt_s':stats(r['receiver_to_receipt_s'] for r in first),'first_reply_segments_s':{k:stats(r['segments_s'][k] for r in first) for k in ['qq_to_receiver','receiver_to_host_delivery','host_delivery_to_plan','plan_tool','plan_to_send','send_to_receipt','receipt_to_host']}},'notes':['Host times are CLI event observation times, not raw model compute time.','QQ timestamp is second-resolution and may differ from server clock.','No client display timestamp is inferred.','Average covers replied targets only; rejections reported separately.']}

def write_report(root,report):
    d=Path(root)/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-'+uuid.uuid4().hex[:6]);d.mkdir(parents=True,exist_ok=False)
    p=d/'latency.json';p.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');return p

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('trace',type=Path);parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    records=[]
    for line in args.trace.read_text(encoding='utf-8-sig').splitlines():
        try:records.append(json.loads(line))
        except ValueError:pass
    result=analyze(records);path=write_report(args.output,result);print(json.dumps({'report':str(path),'summary':result['summary'],'rejections':len(result['rejections'])},ensure_ascii=False))
