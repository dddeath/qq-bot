"""Review projections over actual application, tool and QQ receipt evidence."""
from copy import deepcopy
import hashlib
import json
from research_feedback import link_feedback, message_record


def review_bundle(record, feedback, *, cutoff, feedback_origin, feedback_window_seconds=3600):
    """Reuse QQ feedback linking; missing sends, usage and motives remain missing."""
    conversation=record['configuration']['conversation_id']
    reports=[]
    for decision in record['decisions']:
        reference=decision.get('decision_id') or decision.get('task_id')
        if not reference:continue
        version=hashlib.sha256(json.dumps(decision,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        calls=[c for c in record['calls'] if reference in c['decision_ids']]
        tasks={decision['task_id']} if decision.get('task_id') else set()
        for call in calls:
            observed=call.get('observation') or {}
            if call['tool']=='begin_reading_task' and observed.get('status')=='ok' and observed.get('task_id'):
                tasks.add(observed['task_id'])
        reports.append(dict(report_id=reference,version=version,
            record_origin='knowledge_application_decision' if decision.get('decision_id') else 'knowledge_application_task',
            text=decision['objective'],
            at=min((c['started_at'] for c in calls),default=cutoff),conversation_id=conversation,
            session_id=record['configuration']['session_id'],run_id=record['configuration']['run_id'],
            task_ids=sorted(tasks),target_event_ids=decision.get('target_event_ids',[]),
            decision=deepcopy(decision)))
    by_id={r['report_id']:r for r in reports}
    plans={}
    material_calls={c['call_id']:c for c in record['calls'] if (c['observation'] or {}).get('status')=='ok'}
    replies=[]
    messages=[]
    for turn in record['turns']:
        body=turn['event'].get('payload',turn['event'])
        for message in [*body.get('messages',[]),*(body.get('input_batch') or {}).get('messages',[])]:
            if not isinstance(message,dict):continue
            if message.get('conversation_id',conversation)!=conversation:continue
            eid=message.get('event_id',message.get('id'))
            if eid is not None:
                normalized=message_record(message,event_id=eid,conversation_id=conversation,at=turn['at'],
                    source={'kind':'host_delivered_event','turn_id':turn['turn_id']})
                if normalized not in messages:messages.append(normalized)
    for call in record['calls']:
        observation=call['observation'] or {}
        if call['tool']=='plan_chat_reply' and observation.get('status')=='ok' and observation.get('plan_id'):
            plans.setdefault(observation['plan_id'],call)
        if call['tool']!='send_chat_reply':continue
        plan=plans.get(observation.get('plan_id'))
        used=((plan or {}).get('request',{}).get('declaration') or {}).get('used_read_ids',[])
        materials=[]
        for read_id in used:
            material=material_calls.get(read_id)
            if material is None:
                materials.append({'read_id':read_id,'status':'missing'})
                continue
            evidence=(material['observation'] or {}).get('evidence_ref')
            materials.append(dict(read_id=read_id,tool=material['tool'],status='delivered',
                evidence_ref=deepcopy(evidence) if evidence else {'kind':'application_call','call_id':read_id},
                reading=deepcopy(material['request']['upstream'].get('_reading'))))
        for bubble in observation.get('bubbles',[]):
            receipt=bubble.get('receipt') or {}; value=receipt.get('result') or {}
            refs=[{'report_id':rid,'version':by_id[rid]['version']} for rid in (plan or {}).get('decision_ids',[]) if rid in by_id]
            replies.append(dict(message_id=value.get('message_id'),state=receipt.get('state'),
                conversation_id=value.get('conversation_id'),text=value.get('content',''),
                at=value.get('timestamp',observation.get('finished_at')),target_event_id=value.get('reply_to_event_id'),
                report_refs=refs,plan_id=observation.get('plan_id'),call_id=call['call_id'],bubble_index=bubble.get('index'),
                used_read_ids=used,used_materials=materials,
                phase=((plan or {}).get('request',{}).get('declaration') or {}).get('phase','final'),
                completion=((plan or {}).get('request',{}).get('declaration') or {}).get('completion'),
                research_association=observation.get('research_association'),source={'kind':'tool_receipt'}))
    linked=link_feedback(reports,replies,[*messages,*deepcopy(feedback)],conversation_id=conversation,cutoff=cutoff,
                         feedback_window_seconds=feedback_window_seconds)
    for item in linked['items']:
        rid=item['report']['report_id']
        related=[c for c in record['calls'] if rid in c['decision_ids'] and c['started_at']<=cutoff]
        turn_ids={c['turn_id'] for c in related} | {item['report']['decision'].get('turn_id')}
        item['delivered_context']=[dict(turn_id=t['turn_id'],at=t['at'],
            messages=[m for m in messages if m['source']['turn_id']==t['turn_id']],
            coverage={key:t['event'].get('payload',t['event'])[key] for key in
                ('gap_count','gap_note','read_through_id','has_more') if key in t['event'].get('payload',t['event'])})
            for t in record['turns'] if t['turn_id'] in turn_ids and t['at']<=cutoff]
        item['reply_plans']=[deepcopy(c) for c in related if c['tool']=='plan_chat_reply']
        plan_ids={(c.get('observation') or {}).get('plan_id') for c in item['reply_plans']} - {None}
        item['send_calls']=[deepcopy(c) for c in record['calls'] if c['tool']=='send_chat_reply'
            and c['started_at']<=cutoff and c['request']['upstream'].get('plan_id') in plan_ids]
        item['send_attempts']=[deepcopy(r) for r in replies if r.get('at') is not None and r['at']<=cutoff
                               and any(ref['report_id']==rid for ref in r['report_refs'])]
        item['material_usage_status']='declared_by_model; semantic_application_requires_review'
    return dict(schema_version=1,configuration=record['configuration'],user_requests=messages,
        decisions=record['decisions'],calls=record['calls'],reads=record['reads'],research_tasks=record.get('research_tasks',[]),
        outputs=replies,feedback=linked,feedback_origin=feedback_origin,usage=record['usage'],
        quality_assessment=None,quality_status='requires_model_or_human_review')


def compare(baseline, candidate):
    """Observed action/cost differences only; no inferred semantic uplift."""
    def counts(report):
        return {'decisions':len(report['decisions']),'local_reads':len(report['reads']),
            'successful_sends':sum(r['state']=='SUCCEEDED' and bool(r['message_id']) for r in report['outputs']),
            'tool_elapsed_seconds':sum((c['observation'] or {}).get('elapsed_seconds',0) for c in report['calls'])}
    a,b=counts(baseline),counts(candidate)
    return dict(baseline=a,candidate=b,delta={key:b[key]-a[key] for key in a},
                semantic_gain=None,semantic_status='requires_paired_review')
