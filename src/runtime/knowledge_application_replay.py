"""Review projections over actual application, tool and QQ receipt evidence."""
from copy import deepcopy
import hashlib
import json
from research_feedback import link_feedback, message_record, feedback_event_index


def _query_status(row):
    state=row.get('execution_state')
    if state in ('budget_blocked','failed'): return state
    if state=='completed': return 'executed'
    decision=row.get('decision_state','')
    if decision.startswith('skipped_'): return 'skipped'
    return state if state not in (None,'not_started') else decision or 'unknown'


def query_evidence(report, item=None, calls=()):
    """Review-only join. Trace read numbers are task-local; application call IDs are not."""
    from knowledge_query import QUERY_DECISION_VERSION
    item=item or {}
    source=item.get('report',{})
    audit=source.get('decision') or {}
    contract=report.get('knowledge_decision') or {}
    task=report.get('task_id') or audit.get('task_id')
    if audit.get('task_id')!=task: audit={}
    modern=(audit.get('decision_protocol')==QUERY_DECISION_VERSION or
            contract.get('protocol_version')==QUERY_DECISION_VERSION)
    rows=audit.get('queries',report.get('queries',contract.get('queries'))) if modern else None
    status=('recorded' if rows else 'no_query' if rows==[] and
            (audit.get('decision_id') or contract.get('decision_id')) else
            'pending' if modern else 'legacy_unattributed')
    result=dict(task_id=task,report_id=source.get('report_id'),status=status,
        action=audit.get('action'),target_event_ids=source.get('target_event_ids',[]),
        query_decisions=[],reads=[],materials={},applications=[],final_message_ids=[],
        feedback_ref=source.get('report_id'),feedback_attribution='unknown',
        explicit_feedback_event_ids=list(dict.fromkeys(str(f['message']['event_id'])
            for f in item.get('followups',[]) if f.get('message',{}).get('event_id') is not None)))
    queries={}
    routes={r['query_id']:r for r in report.get('query_routes',[]) if r.get('query_id')}
    for row in rows or []:
        if not row.get('query_id'):continue
        q={key:deepcopy(value) for key,value in row.items() if key in (
            'query_id','query_index','purpose','original_query','decision_state','execution_state',
            'execution_reason','reason','gate','subjective_inclination','learned_adjustment','expected_gain',
            'decision_order','decided_at','budget_at_decision','configuration_binding')}
        q.update(status=_query_status(row),trace_read_ids=[],application_read_ids=list(row.get('read_ids',[])))
        if 'original_query' not in q and q['query_id'] in routes:
            q['original_query']={k:v for k,v in routes[q['query_id']].items() if k in ('text','keywords','purpose','need')}
        queries[q['query_id']]=q
        result['query_decisions'].append(q)
    call_by_read={}
    for c in calls:
        obs=c.get('observation') or {}
        ref=obs.get('evidence_ref') or {}
        if task and ref.get('task_id')==task and ref.get('read_id') is not None:
            call_by_read.setdefault(str(ref['read_id']),{})[c['call_id']]=c
    def invocations(group):
        return [dict(call_id=c['call_id'],application_read_id=(c.get('observation') or {}).get('read_id'),
                    elapsed_seconds=(c.get('observation') or {}).get('elapsed_seconds')) for c in group.values()]
    seen=set()
    for read in report.get('reads',[]):
        rid=read.get('read_id')
        if rid is None or str(rid) in seen:continue
        seen.add(str(rid))
        q=queries.get((read.get('query_route') or {}).get('query_id'))
        if q is not None:q['trace_read_ids'].append(rid)
        delivered=(read.get('delivery') or {}).get('result') or {}
        payload=delivered.get('structuredContent') or {}
        material=None if delivered.get('isError') or payload.get('error') or payload.get('status')=='error' else payload.get('material')
        mid=None
        if material is not None:
            mid=hashlib.sha256(json.dumps(material,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            result['materials'].setdefault(mid,material)
        group=call_by_read.get(str(rid),{})
        c=next(iter(group.values()),{})
        aid=(c.get('observation') or {}).get('read_id') or (payload.get('knowledge_application') or {}).get('read_id')
        if q is not None and aid and aid not in q['application_read_ids']:q['application_read_ids'].append(aid)
        result['reads'].append(dict(trace_read_id=rid,query_id=q['query_id'] if q else None,
            tool=read.get('tool'),query_read_stage=read.get('query_read_stage'),
            call_id=c.get('call_id'),application_read_id=aid,elapsed_seconds=read.get('elapsed_seconds'),
            delivery_status=payload.get('status'),material_id=mid,application_calls=invocations(group)))
    # A links-only export has application receipts but no trace bodies. Preserve real
    # invocations without inventing either disclosure content or a charge.
    for rid,group in call_by_read.items():
        if rid in seen:continue
        c=next(iter(group.values()))
        obs=c.get('observation') or {}
        routing=c.get('request',{}).get('upstream',{}).get('_reading') or {}
        q=queries.get(routing.get('query_id'))
        if q is not None:q['trace_read_ids'].append((obs['evidence_ref'])['read_id'])
        result['reads'].append(dict(trace_read_id=(obs['evidence_ref'])['read_id'],query_id=q['query_id'] if q else None,
            call_id=c['call_id'],application_read_id=obs.get('read_id'),tool=c['tool'],
            elapsed_seconds=None,query_read_stage=None,delivery_status=None,material_id=None,
            application_calls=invocations(group)))
    by_application={aid:qid for qid,q in queries.items() for aid in q['application_read_ids']}
    contributors=set()
    for reply in item.get('replies',[]):
        if reply.get('state')!='SUCCEEDED' or reply.get('phase')!='final' or not reply.get('message_id'):continue
        mid=str(reply['message_id'])
        if mid in result['final_message_ids']:continue
        result['final_message_ids'].append(mid)
        owners={m['read_id']:m['reading']['task_id'] for m in reply.get('used_materials',[])
            if (m.get('reading') or {}).get('task_id')}
        for aid in dict.fromkeys(reply.get('used_read_ids') or []):
            if task and owners.get(aid,task)!=task:continue
            qid=by_application.get(aid)
            if qid:contributors.add(qid)
            result['applications'].append(dict(message_id=mid,application_read_id=aid,query_id=qid,
                declaration_scope='reply_plan',semantic_use='not_verified'))
    if len(contributors)>1:result['feedback_attribution']='joint_or_unknown'
    return result


def missing_decisions(unresolved):
    """Only linked successful sends without a recorded decision; never infer no_query."""
    groups={}
    for row in unresolved:
        r=row['reply']
        if (row.get('candidates') or r.get('report_refs') or r.get('phase')=='acknowledgement'
                or r.get('state')!='SUCCEEDED' or not r.get('message_id')):continue
        mid=str(r['message_id'])
        key=(r.get('conversation_id'),r.get('plan_id') or mid)
        group=groups.setdefault(key,dict(status='decision_missing',plan_id=r.get('plan_id'),
            conversation_id=r.get('conversation_id'),final_message_ids=[],phase_unknown_message_ids=[],
            query_decisions=[],receipts=[]))
        ids=group['final_message_ids' if r.get('phase')=='final' else 'phase_unknown_message_ids']
        if mid not in ids:
            ids.append(mid)
            group['receipts'].append({k:deepcopy(r.get(k)) for k in ('message_id','text','at','source','target_event_id')})
    return list(groups.values())


def review_bundle(record, feedback, *, cutoff, feedback_origin, final_report=None, feedback_window_seconds=3600,
                  feedback_observation=None):
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
            source={'kind':'knowledge_application','run_id':record['configuration']['run_id'],'reference':reference},
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
                phase=((plan['request'].get('declaration') or {}).get('phase','final') if plan else None),
                completion=((plan or {}).get('request',{}).get('declaration') or {}).get('completion'),
                research_association=observation.get('research_association'),source={'kind':'tool_receipt'}))
    linked=link_feedback(reports,replies,[*messages,*deepcopy(feedback)],conversation_id=conversation,cutoff=cutoff,
                         feedback_window_seconds=feedback_window_seconds,observation=feedback_observation)
    linked['feedback_events']=feedback_event_index(linked['items'])
    task_reports={v['report']['task_id']:v['report'] for v in record.get('research_tasks',[]) if v.get('report')}
    shared_materials={}
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
        task_ids=item['report']['task_ids']
        task=item['report']['decision'].get('task_id') or (task_ids[0] if len(task_ids)==1 else None)
        item['query_catalog']=query_evidence(task_reports.get(task,{'task_id':task}),item,related)
        bodies=item['query_catalog'].pop('materials')
        shared_materials.update(bodies)
        item['query_catalog']['material_ids']=list(bodies)
    result=dict(schema_version=1,configuration=record['configuration'],user_requests=messages,
        decisions=record['decisions'],calls=record['calls'],reads=record['reads'],research_tasks=record.get('research_tasks',[]),
        outputs=replies,feedback=linked,feedback_origin=feedback_origin,usage=record['usage'],
        catalog_materials=shared_materials,
        query_catalog=[i['query_catalog'] for i in linked['items']]+missing_decisions(linked['unresolved_replies']),
        quality_assessment=None,quality_status='requires_model_or_human_review')
    if final_report is not None:
        result['final_report']=deepcopy(final_report)
        result['applications']=validate_applications(result,final_report)
        for cat in result['query_catalog']:
            for declaration in cat.get('applications',[]):
                # Only an explicit excerpt in this particular sent bubble verifies
                # wording. Even an exact excerpt does not establish causal use.
                final=next((r for r in replies if str(r['message_id'])==declaration['message_id']
                            and r['state']=='SUCCEEDED' and r.get('conversation_id')==conversation),{})
                excerpts=[a['reply_excerpt'] for a in result['applications']
                          if a['read_id']==declaration['application_read_id'] and a['reply_status']=='sent']
                if excerpts:
                    declaration['matched_excerpts']=[e for e in excerpts if e in final.get('text','')]
                    declaration['excerpt_status']='present' if declaration['matched_excerpts'] else 'not_in_this_bubble'
    return result


def validate_applications(bundle,final_report):
    """Validate declared material application against delivered reads and reply evidence."""
    from knowledge_decision import FINAL_REPORT_SCHEMA
    from jsonschema import Draft202012Validator
    from pathlib import Path
    errors=list(Draft202012Validator(FINAL_REPORT_SCHEMA).iter_errors(final_report))
    if errors:raise ValueError('invalid_final_report: '+errors[0].message)
    calls={c['call_id']:c for c in bundle['calls']}
    events={m['event_id'] for m in bundle['user_requests']}
    plans=[c for c in bundle['calls'] if c['tool']=='plan_chat_reply'
           and (c['observation'] or {}).get('plan_id')
           and c['request']['upstream'].get('message')==final_report['reply_text']]
    if not plans:raise ValueError('final_reply_not_linked')
    plan_ids={c['observation']['plan_id'] for c in plans}
    sent=[r for r in bundle['outputs'] if r['state']=='SUCCEEDED' and r.get('message_id') and r['plan_id'] in plan_ids]
    delivered=any(final_report['reply_text']==sep.join(r['text'] for r in sent if r['plan_id']==pid)
                  for pid in plan_ids for sep in ('','\n'))
    used=set().union(*(set((c['request'].get('declaration') or {}).get('used_read_ids',[])) for c in plans))
    result=[]
    for item in final_report['applications']:
        call=calls.get(item['read_id']);observed=(call or {}).get('observation') or {}
        if item['read_id'] not in used or observed.get('status')!='ok' or not observed.get('read_id'):
            raise ValueError('application_read_not_used')
        if set(item['context_event_ids'])-events:raise ValueError('application_context_not_delivered')
        if not item['reply_excerpt'] or item['reply_excerpt'] not in final_report['reply_text']:
            raise ValueError('application_excerpt_not_in_reply')
        ref=observed.get('evidence_ref') or {}
        material=None
        if ref.get('read_path'):
            read=json.loads(Path(ref['read_path']).read_text(encoding='utf-8'))
            material=read.get('delivery',{}).get('result',{}).get('structuredContent',{}).get('material')
        if not isinstance(material,dict):raise ValueError('application_material_missing')
        tags=set(material.get('tags',[]))
        for candidate in material.get('items',[]):tags.update(candidate.get('tags',[]))
        if set(item['tag_ids'])-tags:raise ValueError('application_tag_not_in_material')
        result.append({**deepcopy(item),'references_verified':True,
                       'reply_status':'sent' if delivered else 'preview',
                       'context_tag_relevance':'requires_model_or_human_review'})
    return result


def compare(baseline, candidate):
    """Observed action/cost differences only; no inferred semantic uplift."""
    def counts(report):
        return {'decisions':len(report['decisions']),'local_reads':len(report['reads']),
            'successful_sends':sum(r['state']=='SUCCEEDED' and bool(r['message_id']) for r in report['outputs']),
            'tool_elapsed_seconds':sum((c['observation'] or {}).get('elapsed_seconds',0) for c in report['calls'])}
    a,b=counts(baseline),counts(candidate)
    return dict(baseline=a,candidate=b,delta={key:b[key]-a[key] for key in a},
                semantic_gain=None,semantic_status='requires_paired_review')
