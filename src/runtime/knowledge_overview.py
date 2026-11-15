"""Bounded candidate overviews shared by live MCP and replay hosts."""
from copy import deepcopy
from pathlib import Path
import json

def chars(x):return len(json.dumps(x,ensure_ascii=False,separators=(',',':')))

def decision_entry(snapshot):
    """The configured overview provider owns the single assessment entry."""
    selected = [name for name, server in snapshot.get('servers', {}).items()
                if server.get('reading_trace', {}).get('candidate_overview', {}).get('prefetch')]
    if len(selected) > 1:
        raise ValueError('multiple_initial_overview_providers')
    return selected[0] if selected else None

def compact_candidates(material, store, max_chars=2000,max_parents=6, *, query_arguments=None):
    from knowledge_passages import table_preview, tok
    query = material if query_arguments is None else query_arguments
    terms = [tok(query.get(k, '')) for k in ('query', 'keywords', 'need')]
    unique=[];seen=set()
    for candidate in material.get('candidates',[]):
        identity=(candidate['entry_id'],candidate['revision'])
        if identity in seen:continue
        seen.add(identity);unique.append(candidate)
    result={'candidates':[],'candidate_coverage':{'total':len(unique),'returned':0,'complete':False}}
    for candidate in unique[:max_parents]:
        key=candidate['entry_id'];entry=store['entries'].get(key)
        if entry is None or entry['revision']!=candidate['revision']:raise ValueError('overview_revision_mismatch')
        if entry.get('status')!='active':raise ValueError('overview_inactive_entry')
        refs=[];parts=[];tables=[]
        for p in candidate.get('passages',[])[:3]:
            start,limit=p['offset'],p['limit']
            if type(start) is not int or type(limit) is not int or start<0 or limit<=0 or start+limit>len(entry['content']):
                raise ValueError('overview_invalid_source_span')
            part=entry['content'][start:start+limit];parts.append(part)
            ref=dict(offset=start,limit=limit)
            if p.get('heading'):ref['heading']=p['heading']
            table=table_preview(part,terms,source=entry['content'],offset=start);tables.append(table)
            ref['preview']=table if table is not None else part[:35]
            refs.append(ref)
        if not refs:continue
        labels=[]
        for tag in entry.get('tags',[])[:3]:
            value=store.get('tags',{}).get(tag,{}) if isinstance(tag,str) else tag
            labels.append(value.get('name',value.get('label',tag)) if isinstance(value,dict) else tag)
        item=dict(entry_id=key,revision=candidate['revision'],title=candidate['title'],
                  tags=labels,passages=refs)
        # Single-span entries retain their fuller excerpt. Multi-span menus use
        # each section's preview instead of privileging and repeating the first.
        if len(parts)==1:
            item['excerpt']=tables[0] if tables[0] is not None else parts[0][:100]
            item['passages']=[dict(offset=refs[0]['offset'],limit=refs[0]['limit'])]
        result['candidates'].append(item);result['candidate_coverage']['returned']=len(result['candidates'])
        if chars(result)>max_chars:
            result['candidates'].pop();result['candidate_coverage']['returned']=len(result['candidates']);break
    result['candidate_coverage']['complete']=len(result['candidates'])==len(unique)
    if chars(result)>max_chars:raise ValueError('overview_envelope_exceeds_budget')
    return result

class CandidateOverview:
    """Apply the same bounded menu before charging and recording delivered text."""
    def __init__(self, config, budget):
        from knowledge_entries import EntryStore
        self.settings = config['reading_trace']['candidate_overview']
        if set(self.settings) - {'prefetch'}:
            raise ValueError('unknown_candidate_overview_field')
        if type(self.settings.get('prefetch', False)) is not bool:
            raise ValueError('invalid_candidate_overview_prefetch')
        env = config.get('env', {})
        self.store = EntryStore.for_reader(env['QQ_KNOWLEDGE_ENTRY_STORE'],
            env.get('QQ_KNOWLEDGE_ACCOUNT', ''), env.get('QQ_KNOWLEDGE_GROUP', ''),
            env.get('QQ_KNOWLEDGE_ROOT'))
        if budget is None:
            raise ValueError('candidate_overview_shared_budget_required')
        self.budget = budget

    def deliver(self, trace, token, tool, arguments, response, elapsed):
        from reading_result import body_of
        trace.complete(token, response, elapsed)
        projected = deepcopy(response)
        body = body_of(projected)
        if (tool == 'retrieve_knowledge_candidates' and isinstance(body.get('candidates'), list)
                and not projected.get('result', {}).get('isError')):
            pending = trace.task_budget(token.parent).state()[0] == 'pending_decision'
            task = json.loads((token.parent/'context.json').read_text(encoding='utf8'))
            plan = task.get('task_context', {}).get('query_plan') or {}
            count = max(1, len(plan.get('queries', []))) if pending else 1
            from knowledge_retrieval_policy import FINAL_LIMIT
            count = min(count, FINAL_LIMIT)
            limits = task['task_context']['decision_contract']['limits']
            max_characters = limits['max_characters']
            if max_characters <= 0:
                max_characters = 2000
            # Source comes from the bound reader. Only the upstream-authorized IDs are projected.
            data = self.store._load()
            data['entries'] = {k:v for k,v in data['entries'].items()
                if v['collection'] in self.store.collections and v['status'] == 'active'}
            compact = compact_candidates(body, data,
                max_chars=max_characters//count,
                max_parents=FINAL_LIMIT//count, query_arguments=arguments)
            projected['result'] = {'structuredContent':compact,
                'content':[{'type':'text','text':json.dumps(compact,ensure_ascii=False)}]}
        delivered = self.budget.deliver(self.budget.current(), tool, arguments, projected, elapsed)
        receipt = None
        for block in delivered.get('result', {}).get('content', []):
            if block.get('type') == 'text':
                try: receipt = json.loads(block['text']).get('knowledge_turn_budget', receipt)
                except (ValueError, AttributeError): pass
        final = trace.delivery(token, delivered)
        if receipt and isinstance(final.get('result', {}).get('structuredContent'), dict):
            final['result']['structuredContent']['knowledge_turn_budget'] = receipt
            final['result']['content'] = [{'type':'text','text':json.dumps(final['result']['structuredContent'],ensure_ascii=False)}]
        return final


def prefetch_assessment(result, application, trace, config, read):
    """Read an initial bounded overview through the ordinary MCP accounting path, once."""
    settings = config.get('reading_trace', {}).get('candidate_overview', {})
    if not settings.get('prefetch') or result.get('state') != 'pending_decision':
        return None
    plan = result.get('query_plan') or {}
    queries = plan.get('queries', [])
    if not queries or 'retrieve_knowledge_candidates' not in config.get('tools', []):
        return None
    folder = trace.folder(result['task_id'])
    destination = folder/'initial-overview.json'
    if destination.exists():
        return json.loads(destination.read_text(encoding='utf8'))
    import os
    claim = folder/'initial-overview.claim'
    try:
        descriptor = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(descriptor)
    except FileExistsError:
        return {'state':'pending_or_interrupted','reads':[], 'automatic_retry':False}
    # A failed/unknown read is retained; repeated assess never repeats it automatically.
    from research_trace import write_record
    outcome = {'state':'running','reads':[],'actor':'host_initial_overview',
               'coverage':{'requested':len(queries),'attempted':0,'completed':0}}
    write_record(destination, outcome)
    try:
        limit = application.context['policy']['decision_probe']['max_calls']
        for i, query in enumerate(queries[:limit]):
            if not trace.task_budget(folder).read_access('retrieve_knowledge_candidates')['can_read']:
                outcome['stop_reason'] = 'probe_budget_exhausted'
                break
            arguments = dict(purpose=query['purpose'], query=query['text'],
                _reading=dict(task_id=result['task_id'], purpose='targeted',
                    reason='读取本查询方向的候选概览以供裁决', relation=query['text'], query_index=i))
            if query['purpose'] == 'expression':
                arguments.update(keywords=query['keywords'],need=query['need'])
            value = read('retrieve_knowledge_candidates', arguments)
            body = value.get('structuredContent')
            if not isinstance(body,dict):
                body = {'error':'overview_read_failed','material':None}
            outcome['reads'].append(body)
            outcome['coverage']['attempted'] += 1
            if not value.get('isError') and 'material' in body and body['material'] is not None:
                outcome['coverage']['completed'] += 1
            write_record(destination,outcome)
            if value.get('isError'):
                outcome['stop_reason'] = 'read_failed'
                break
        outcome['state'] = ('complete' if outcome['coverage']['completed'] == len(queries) else 'incomplete')
        if outcome['state'] == 'incomplete' and 'stop_reason' not in outcome:
            outcome['stop_reason'] = 'probe_call_limit_or_missing_material'
    except Exception as error:
        outcome.update(state='incomplete',error_type=type(error).__name__)
    write_record(destination,outcome)
    return outcome

