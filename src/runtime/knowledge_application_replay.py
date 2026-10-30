"""Review projections over actual application, tool and QQ receipt evidence."""
from copy import deepcopy
import hashlib
import json
from research_feedback import link_feedback


def review_bundle(record, feedback, *, cutoff, feedback_origin):
    """Reuse QQ feedback linking; missing sends, usage and motives remain missing."""
    conversation=record['configuration']['conversation_id']
    reports=[]
    for decision in record['decisions']:
        version=hashlib.sha256(json.dumps(decision,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        calls=[c for c in record['calls'] if decision['decision_id'] in c['decision_ids']]
        reports.append(dict(report_id=decision['decision_id'],version=version,
            record_origin='knowledge_application_decision',text=decision['objective'],
            at=min((c['started_at'] for c in calls),default=cutoff),conversation_id=conversation,
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
            eid=message.get('event_id',message.get('id'))
            if eid is not None:
                messages.append(dict(event_id=str(eid),text=message.get('text',message.get('content','')),
                    at=message.get('at',turn['at']),conversation_id=message.get('conversation_id',conversation),
                    source={'kind':'host_delivered_event','turn_id':turn['turn_id']}))
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
                report_refs=refs,plan_id=observation.get('plan_id'),call_id=call['call_id'],
                used_read_ids=used,used_materials=materials,
                completion=((plan or {}).get('request',{}).get('declaration') or {}).get('completion'),
                research_association=observation.get('research_association'),source={'kind':'tool_receipt'}))
    linked=link_feedback(reports,replies,[*messages,*deepcopy(feedback)],conversation_id=conversation,cutoff=cutoff)
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
