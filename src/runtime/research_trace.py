"""Opt-in tool-boundary evidence for scoped research tasks."""
import asyncio
import base64
import datetime as dt
import json
import time
import uuid
from pathlib import Path
from reading_budget import ReadBudget, reading_budget_exhausted


CONTROL_TOOLS = ['begin_reading_task', 'finish_reading_task', 'declare_native_read']


class ControlArgumentsError(ValueError):
    def __init__(self, tool, issues):
        self.details = dict(error='invalid_control_parameters', tool=tool, issues=issues,
                            next_action='Correct these fields and retry with the same task_id when present.')
        super().__init__(json.dumps(self.details, ensure_ascii=False))

    def tool_result(self):
        return dict(isError=True, content=[dict(type='text', text=str(self))],
                    structuredContent=self.details)


def write_record(path, value):
    staging = path.with_name('.' + uuid.uuid4().hex + '.tmp')
    staging.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    for attempt, delay in enumerate((0.02, 0.05, 0.1, 0)):
        try:
            staging.replace(path)
            return
        except PermissionError as error:
            if getattr(error, 'winerror', None) not in (5, 32) or attempt == 3:
                raise
            time.sleep(delay)


class ResearchTrace:
    def __init__(self, config):
        self.config = config
        self.root = Path(config['root'])
        self.root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def for_servers(cls, config, servers, *, index_policy=None):
        from knowledge_tools import RetrievalBinding
        from startup_knowledge import render_binding
        bound = RetrievalBinding.select(servers, ambiguity='ambiguous_startup_knowledge_provider')
        return cls({**config, 'knowledge_index': render_binding(bound, application_policy=index_policy),
                    'knowledge_protocol': bound.mode if bound else 'none',
                    'knowledge_semantic': bound.semantic if bound else False})

    def folder(self, task_id):
        if not isinstance(task_id, str) or len(task_id) != 32 or any(c not in '0123456789abcdef' for c in task_id):
            raise ValueError('invalid_reading_task_id')
        folder = self.root / task_id
        if not (folder / 'context.json').is_file():
            raise ValueError('unknown_reading_task')
        return folder

    def begin(self, goal, video=None, source=None, task_mode="reading", context=None, budget=None, needs=None, query_plan=None):
        return self._begin(uuid.uuid4().hex, goal, video, source, task_mode, context, budget, needs, query_plan)

    def begin_once(self, task_id, arguments):
        """Caller serializes one decision; a retry preserves its task and elapsed budget."""
        if len(task_id)!=32 or any(c not in '0123456789abcdef' for c in task_id):
            raise ValueError('invalid_reading_task_id')
        folder=self.root/task_id
        if not (folder/'context.json').exists():
            self._begin(task_id, **arguments)
        else:
            context=json.loads((folder/'context.json').read_text(encoding='utf-8'))
            if context['audit_scope']!=self.config['scope']:
                raise ValueError('reading_scope_mismatch')
            limits=context['budget']
            elapsed=time.time()-dt.datetime.fromisoformat(context['recorded_at']).timestamp()
            if not context.get('task_context',{}).get('decision_contract'):
                ReadBudget(folder/'budget.db', limits['max_read_units'],limits['exploration_budget_ratio'],
                           max(0,limits['timeout_seconds']-elapsed),context['execution_policy'],now=time.time)
            if not (folder/'protocol.json').exists():
                from reading_protocol import generate
                write_record(folder/'protocol.json',generate(task_id,context))
        self.report(folder)
        return {'task_id':task_id,**json.loads((folder/'protocol.json').read_text(encoding='utf-8')),
                'budget_remaining':self.remaining(folder)}

    def validate_application_budget(self, requested=None):
        requested={} if requested is None else requested
        if not isinstance(requested,dict):raise ValueError('invalid_reading_budget')
        for key,default in (('max_read_units',10),('timeout_seconds',300)):
            limit=self.config.get(key,default);value=requested.get(key,limit)
            if type(value) not in (int,float):raise ValueError('invalid_reading_budget')
            if value>limit:raise ValueError('reading_budget_exceeds_application_limit:'+key)

    def validate_begin(self, goal, video=None, source=None, task_mode="reading", context=None, budget=None, needs=None, query_plan=None):
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError('reading_goal_required')
        if task_mode not in ('reading', 'learning') or (context is not None and not isinstance(context, dict)):
            raise ValueError('invalid_reading_task_context')
        if 'query_plan' in (context or {}):
            raise ValueError('query_plan_requires_top_level_parameter')
        if query_plan is not None:
            from knowledge_decision import validate_query_plan
            validate_query_plan(query_plan)
        if needs is not None and (not isinstance(needs, list) or any(n not in ('expression','reference','profile') for n in needs)):
            raise ValueError('invalid_reading_needs')
        limits = {k: self.config.get(k, default) for k, default in
                  [('max_read_units', 10), ('exploration_budget_ratio', .2), ('timeout_seconds', 300)]}
        if budget is not None:
            if not isinstance(budget, dict) or set(budget)-set(limits):raise ValueError('invalid_reading_budget')
            limits.update(budget)
        if (type(limits['max_read_units']) is not int or limits['max_read_units'] < 1
                or not 0 <= limits['exploration_budget_ratio'] <= 1 or limits['timeout_seconds'] <= 0):
            raise ValueError('invalid_reading_budget')
        if self.config.get('deadline') is not None:
            limits['timeout_seconds'] = min(limits['timeout_seconds'], self.config['deadline']-time.time())
            if limits['timeout_seconds'] <= 0:raise ValueError('time_budget_exhausted')
        return limits

    def _begin(self, task_id, goal, video=None, source=None, task_mode="reading", context=None, budget=None, needs=None, query_plan=None):
        limits=self.validate_begin(goal,video,source,task_mode,context,budget,needs,query_plan)
        if query_plan is not None:
            context=dict(context or {},query_plan=query_plan)
        from knowledge_application import policy, GAIN_PROTOCOL_VERSION
        application=policy(self.config.get('knowledge_application'))
        folder=self.root/task_id
        folder.mkdir(exist_ok=True)
        context = dict(goal=goal, video=video, task_mode=task_mode, needs=list(dict.fromkeys(needs or [])), task_context=context or {}, audit_scope=self.config['scope'],
                       task_source='task_entry', request_source=source, budget=limits,
                       recorded_at=dt.datetime.now(dt.timezone.utc).isoformat())
        context['knowledge_index'] = self.config.get('knowledge_index', '')
        context['knowledge_protocol'] = self.config.get('knowledge_protocol', 'legacy')
        context['knowledge_semantic'] = self.config.get('knowledge_semantic', False)
        if application['enabled']:
            context['knowledge_application']=application
            if application['strategy'] == 'gain':
                context['gain_protocol_version'] = GAIN_PROTOCOL_VERSION
        context['execution_policy'] = {'max_targeted_units': min(18, limits['max_read_units']),
                                       'finalization_reserve_seconds': min(60, limits['timeout_seconds'] * .2),
                                       'video_poll_max_calls': 10, 'video_poll_timeout_seconds': 180}
        if context['task_context'].get('decision_contract'):
            configured=context['task_context']['decision_contract']['limits']
            context['budget']={'max_read_units':configured['total_calls'],'timeout_seconds':configured['total_seconds']}
            context['execution_policy']={'uniform_material_calls':True,'finalization_reserve_seconds':configured['reserve_seconds']}
        write_record(folder / 'context.json', context)
        if context['task_context'].get('decision_contract'):
            from decision_read_budget import DecisionReadBudget
            DecisionReadBudget(folder/'budget.db',context['task_context']['decision_contract'])
        else:
            ReadBudget(folder / 'budget.db', limits['max_read_units'],
                       limits['exploration_budget_ratio'], limits['timeout_seconds'], context['execution_policy'],now=time.time)
        from reading_protocol import generate
        write_record(folder/'protocol.json', generate(task_id, context))
        self.report(folder)
        return task_id

    def remaining(self, folder):
        return self.task_budget(folder).remaining()

    def task_budget(self,folder):
        context=json.loads((folder/'context.json').read_text(encoding='utf-8'))
        if context.get('task_context',{}).get('decision_contract'):
            from decision_read_budget import DecisionReadBudget
            return DecisionReadBudget(folder/'budget.db')
        return ReadBudget(folder/'budget.db', now=time.time)

    def read_timeout(self,path):
        ledger=self.task_budget(path.parent)
        return ledger.timeout() if hasattr(ledger,'timeout') else ledger.remaining()['read_seconds']

    def prepare(self, tool, arguments):
        args = dict(arguments)
        purpose = args.pop('_reading', None)
        if not isinstance(purpose, dict):
            raise ValueError('reading_context_required')
        folder = self.folder(purpose.get('task_id'))
        self.expire_pending(folder)
        if (folder / 'completion.json').exists():
            raise ValueError('reading_task_closed')
        relation = purpose.get('relation')
        if not isinstance(relation, str) or not relation.strip():
            raise ValueError('reading_relation_required')
        from knowledge_query import ROUTED, resolve
        if tool == 'retrieve_knowledge_candidates':
            from knowledge_query import validate_candidate_arguments
            validate_candidate_arguments(**args)
        route = None
        if tool in ROUTED:
            context=json.loads((folder/'context.json').read_text(encoding='utf8'))
            route=resolve(tool,args,purpose,context['task_context'].get('query_plan'),context.get('needs',[]))
        before = self.remaining(folder)
        ledger=self.task_budget(folder)
        index = ledger.reserve(tool, purpose.get('purpose'), purpose.get('reason'), args)
        record = dict(read_id=index, tool=tool, arguments=args,
                      action={'kind': tool, 'purpose': purpose['purpose']},
                      purpose_record={'question': purpose['reason'], 'relation_reason': relation,
                                      'prior_observation': purpose.get('prior_observation'),
                                      'source': 'model_declared_before_call'},
                      budget_before=before, started_at=time.time(),
                      result={'status': 'pending', 'images': []})
        if route is not None:record['query_route']=route
        if hasattr(ledger,'state'):record['decision_state']=ledger.state()[0]
        path = folder / f'read-{index:03d}.json'
        write_record(path, record)
        return path, args

    def complete(self, path, response, elapsed):
        record = json.loads(path.read_text(encoding='utf-8'))
        body = response.get('result', {})
        content = body.get('content', [])
        record['result'] = dict(status='error' if response.get('error') or body.get('isError') else 'ok',
                                text='\n'.join(c.get('text', '') for c in content if c.get('type') == 'text'),
                                images=[])
        if response.get('error'):
            record['result']['error'] = response['error']
        if 'structuredContent' in body:
            record['result']['structured_content'] = body['structuredContent']
        from reading_result import RETRIEVAL_META
        diagnostics = body.get('_meta', {}).get(RETRIEVAL_META)
        if diagnostics is not None:
            record['result']['retrieval_diagnostics'] = diagnostics
        for n, item in enumerate(content):
            if item.get('type') != 'image':
                continue
            extension = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}.get(item.get('mimeType'), 'img')
            image = path.with_name(path.stem + f'-{n}.{extension}')
            image.write_bytes(base64.b64decode(item['data'], validate=True))
            record['result']['images'].append({'path': str(image), 'mime_type': item.get('mimeType')})
        record.update(finished_at=time.time(), elapsed_seconds=elapsed,
                      budget_remaining=self.remaining(path.parent))
        write_record(path, record)
        self.expire_pending(path.parent)
        self.report(path.parent)

    def expire_pending(self,folder):
        if (folder/'completion.json').exists():return
        ledger=self.task_budget(folder)
        if hasattr(ledger,'state') and ledger.state()[0]=='pending_decision' and ledger.remaining()['total_seconds']<=0:
            if any(json.loads(p.read_text(encoding='utf-8'))['result']['status']=='pending' for p in folder.glob('read-*.json')):
                return
            self.finish(folder.name,'cancelled','decision_missing: total task time exhausted',
                        '保留已读材料；未收到最终裁决。',basis='executor_control')

    async def execute(self, tool, arguments, invoke):
        """Execute one model-selected read; the transport supplies actual MCP output."""
        try:
            path, args = self.prepare(tool, arguments)
        except ValueError as exc:
            self.reject(tool, arguments, exc)
            raise
        started = time.monotonic()
        try:
            remaining = self.remaining(path.parent)
            timeout = self.read_timeout(path)
            if tool == 'watch_video':
                poll = remaining.get('video_polls',{}).get(ReadBudget.video_key(args))
                if poll is not None:timeout = min(timeout,poll['seconds'])
            response = await asyncio.wait_for(invoke(tool, args), timeout)
        except Exception as exc:
            self.complete(path, {'error': {'message': str(exc), 'type': type(exc).__name__}}, time.monotonic()-started)
            raise
        return self.complete_and_deliver(path, response, time.monotonic()-started)

    def complete_and_deliver(self, path, response, elapsed):
        """Record the upstream response before constructing the caller's projection."""
        self.complete(path, response, elapsed)
        return self.delivery(path, response)

    def evidence_reference(self, path):
        """Locate an executed read using the executor's own task and read IDs."""
        record = json.loads(path.read_text(encoding='utf-8'))
        return {'kind':'research_task','task_id':path.parent.name,
                'path':str(path.parent/'report.json'),'read_id':record['read_id'],'read_path':str(path)}

    def delivery(self, path, response):
        """Persist the same bounded result and budget receipt sent to the caller."""
        from reading_result import model_response
        response = model_response(response)
        record = json.loads(path.read_text(encoding='utf-8'))
        ledger=self.task_budget(path.parent)
        if hasattr(ledger,'disclose'):
            from reading_result import body_of
            raw=body_of(response)
            failed=bool(response.get('error') or response.get('result',{}).get('isError') or raw.get('error'))
            material,coverage=ledger.disclose(record['read_id'],None if failed else raw)
            # Only the current delivery is model-visible. The recorded upstream
            # response may contain material rejected by the disclosure budget.
            current_text='\n'.join(block.get('text','') for block in response.get('result',{}).get('content',[]) if block.get('type')=='text')
            error=(response.get('error') or raw.get('error') or current_text or 'reading_tool_failed') if failed else None
            if failed:coverage.update(complete=False,next_offset=None)
            if not failed and material is None:error='probe_material_does_not_fit: commit with existing evidence'
            if error is not None and not isinstance(error,str):error=json.dumps(error,ensure_ascii=False)
            value={'task_id':path.parent.name,'read_id':str(record['read_id']),
                   'status':'error' if failed else 'partial' if not coverage['complete'] else 'ok',
                   'material':material,'coverage':{k:coverage[k] for k in ('complete','next_offset')},
                   'budget_remaining':ledger.remaining(),'error':error}
            images=[block for block in response.get('result',{}).get('content',[]) if block.get('type')=='image']
            response={'jsonrpc':response.get('jsonrpc','2.0'),'id':response.get('id'),'result':{
                'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)},*images],
                'structuredContent':value,'isError':failed}}
            record['disclosure']=coverage
            write_record(path,record);self.record_delivery(path,response)
            return response
        if 'result' in response:
            response['result'].setdefault('content', []).insert(0, {'type':'text','text':json.dumps({
                'read_id':record['read_id'], 'budget_remaining':self.remaining(path.parent)})})
        projected = json.loads(json.dumps(response))
        images = iter(record['result'].get('images', []))
        for block in projected.get('result', {}).get('content', []):
            if block.get('type') == 'image':
                block.pop('data', None)
                block['artifact'] = next(images, None)
        self.audit_delivery(path, response)
        record['delivery'] = projected
        write_record(path, record)
        self.report(path.parent)
        return response

    def reject(self, tool, arguments, error):
        purpose = arguments.get('_reading') or {}
        try:
            folder = self.folder(purpose.get('task_id'))
        except ValueError:
            return
        if (folder / 'completion.json').exists():
            return
        write_record(folder / ('rejected-' + uuid.uuid4().hex + '.json'),
                     {'tool': tool, 'arguments': arguments, 'error': str(error), 'timestamp': time.time(),
                      'upstream_called': False, 'budget_charged': False})
        self.report(folder)

    def audit_delivery(self, path, response):
        from model_input_audit import audit_input
        record = dict(read_record=path.name, **audit_input(response, surface='research_tool_result'))
        with (path.parent / 'input-audit.jsonl').open('a', encoding='utf8') as out:
            out.write(json.dumps(record, ensure_ascii=False)+'\n')

    def record_delivery(self,path,response):
        """Retain the final caller-visible envelope, including application references."""
        self.audit_delivery(path, response)
        record=json.loads(path.read_text(encoding='utf-8'))
        projected=json.loads(json.dumps(response))
        images=iter(record['result'].get('images',[]))
        for block in projected.get('result',{}).get('content',[]):
            if block.get('type')=='image':
                block.pop('data',None);block['artifact']=next(images,None)
        record['delivery']=projected
        write_record(path,record);self.report(path.parent)

    def finish(self, task_id, stop_reason, reason, conclusion, *, basis='model_declared'):
        folder = self.folder(task_id)
        if not all(isinstance(x, str) and x.strip() for x in (stop_reason, reason, conclusion)):
            raise ValueError('reading_completion_required')
        if any(json.loads(p.read_text(encoding='utf-8'))['result']['status'] == 'pending'
               for p in folder.glob('read-*.json')):
            raise ValueError('reading_calls_pending')
        if basis == 'model_declared' and stop_reason not in ('sufficient','budget_exhausted','no_readable_material','cancelled'):
            raise ValueError('invalid_stop_reason')
        remaining = self.remaining(folder)
        ledger=self.task_budget(folder)
        if hasattr(ledger,'state') and ledger.state()[0]=='pending_decision' and stop_reason!='cancelled':
            raise ValueError('knowledge_decision_pending: commit or cancel')
        exhausted=(remaining['total_calls']==0 or remaining['read_seconds']<=0 or remaining['total_seconds']<=0) if 'total_calls' in remaining else reading_budget_exhausted(remaining)
        if stop_reason == 'budget_exhausted' and not exhausted:
            raise ValueError('budget_not_exhausted: '+json.dumps(remaining))
        completion = dict(stop_reason=stop_reason, reason=reason, conclusion=conclusion,
                          basis=basis, budget_remaining=self.remaining(folder),
                          timestamp=time.time())
        with (folder / 'completion.json').open('x', encoding='utf-8') as out:
            json.dump(completion, out, ensure_ascii=False)
        if hasattr(ledger,'decide'):
            ledger.decide('closed',False)
            decision_path=folder/'decision.json'
            decision=json.loads(decision_path.read_text(encoding='utf-8')) if decision_path.exists() else {}
            write_record(decision_path,{**decision,'state':'closed'})
        return self.report(folder)

    def report(self, folder):
        context = json.loads((folder / 'context.json').read_text(encoding='utf-8'))
        reads = [json.loads(p.read_text(encoding='utf-8')) for p in sorted(folder.glob('read-*.json'))]
        completion = json.loads((folder / 'completion.json').read_text(encoding='utf-8')) if (folder / 'completion.json').exists() else None
        report = dict(schema_version=1, record_origin='exploration_executor', task_id=folder.name,
                      recorded_at=context['recorded_at'], captured_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                      context=context, user_request=context['goal'], video=context['video'], reads=reads,
                      decisions=[{'read_id': r['read_id'], 'purpose_record': r['purpose_record'],
                                  'budget_remaining': r['budget_before']} for r in reads],
                      completion=completion, stop_reason=completion['stop_reason'] if completion else None,
                      rejected_calls=[json.loads(p.read_text(encoding='utf-8')) for p in sorted(folder.glob('rejected-*.json'))],
                      completion_attempts=sorted([json.loads(p.read_text(encoding='utf-8')) for p in folder.glob('completion-attempt-*.json')],key=lambda a:a['timestamp']),
                      trace_coverage='executor_calls',
                      limitations=([f"read_{r['read_id']}:{r['result']['status']}" for r in reads
                                    if r['result']['status'] in ('pending', 'missing_output', 'unassociated_native_event')]
                                   + ([] if completion else ['task_not_finished'])))
        plan=context.get('task_context',{}).get('query_plan')
        if plan:
            report['query_routes']=[dict(q,query_index=i,read_ids=[r['read_id'] for r in reads
                if r.get('query_route',{}).get('query_index')==i]) for i,q in enumerate(plan['queries'])]
        if (folder/'decision.json').exists():report['knowledge_decision']=json.loads((folder/'decision.json').read_text(encoding='utf-8'))
        # Separate proxies may finish reads concurrently; each evidence file remains authoritative.
        write_record(folder / 'report.json', report)
        return report

    def schemas(self, tools, *, require_context=True):
        result = []
        for tool in tools:
            tool = json.loads(json.dumps(tool))
            schema = tool['inputSchema']
            schema.setdefault('properties', {})['_reading'] = {
                'type': 'object', 'properties': {
                    'task_id': {'type': 'string', 'description': 'Opaque task_id returned by begin_reading_task; reuse unchanged for reads and completion.'}, 'purpose': {'type': 'string', 'enum': ['targeted', 'explore'], 'description': 'targeted addresses the task goal; explore checks unexpanded material. Classify by purpose, not tool type.'},
                    'reason': {'type': 'string', 'description': 'Short factual basis for this action or stopping reason.'}, 'relation': {'type': 'string', 'description': 'How this read relates to the original goal or learning topic; exploration may be unrelated, state that explicitly.'},
                    'prior_observation': {'type': 'string', 'description': 'Optional actual prior observation that motivates this follow-up.'}},
                'required': ['task_id', 'purpose', 'reason', 'relation'], 'additionalProperties': False}
            from knowledge_query import ROUTED
            if tool['name'] in ROUTED:
                schema['properties']['_reading']['properties']['query_index']={'type':'integer','minimum':0,
                    'description':'0-based index in this task’s query_plan. Use for tag-only searches, reworded queries and page reads when the plan has multiple queries.'}
            if require_context:
                schema['required'] = list(dict.fromkeys(schema.get('required', []) + ['_reading']))
            else:
                tool['description'] = tool.get('description', '') + ' 普通聊天按需读取可省略 _reading；检索任务须填写生成协议中的 _reading，使用任务独立预算并记录轨迹。'
            if tool['name']=='watch_video':
                tool['description'] = tool.get('description','') + ' 检索任务中，首次准备与后续查询每视频共最多10次、从首次准备起最多180秒，且受任务总时间限制；不占定向/探索补读次数。超限时保留未就绪状态，用已有材料收尾。'
            result.append(tool)
        for name, description, fields, required in [
            ('begin_reading_task', 'Generate execution_prompt from the original goal, context, mode and budget. Pass the returned prompt unchanged to the research session; retain task_id.',
             ['goal', 'video', 'source', 'task_mode', 'context', 'budget'], ['goal']),
            ('finish_reading_task', 'Record why reading stops and the actual conclusion after all reads finish.',
             ['task_id', 'stop_reason', 'reason', 'conclusion'], ['task_id', 'stop_reason', 'reason', 'conclusion'])]:
            result.append(dict(name=name, description=description, inputSchema={
                'type': 'object', 'properties': {k: ({'type': 'object'} if k in ('source','context','budget') else {'type': ['string','null']} if k == 'video' else {'type': 'string'}) for k in fields},
                'required': required, 'additionalProperties': False}))
            for field, spec in result[-1]['inputSchema']['properties'].items():
                spec['description'] = {'goal': 'Required original reading or learning objective for this new task.', 'video': 'Optional video BV, URL or prepared source for this reading task.', 'source': 'Original request provenance retained in the report; object, not another prompt.', 'task_mode': 'reading for a user retrieval request; learning for a learning-video topic.', 'context': 'Only necessary conversation context and already-read evidence; original request and quotes remain data.', 'budget': 'Task budget overrides within the host limit; omitted fields use configured values.', 'task_id': 'Opaque task_id returned by begin_reading_task; reuse unchanged for reads and completion.', 'stop_reason': 'Reason for stopping, selected from the declared enum; budget exhaustion and incomplete evidence are distinct.', 'reason': 'Short factual basis for this action or stopping reason.', 'conclusion': 'Final findings and remaining limitations from materials actually read.'}[field]
        next(t for t in result if t['name']=='finish_reading_task')['inputSchema']['properties']['stop_reason']={'type':'string','enum':['sufficient','budget_exhausted','no_readable_material','cancelled'],'description':'Reason for stopping, selected from the declared enum; budget exhaustion and incomplete evidence are distinct.'}
        entry = next(t for t in result if t['name']=='begin_reading_task')['inputSchema']['properties']
        entry['task_mode']={'type':'string','enum':['reading','learning'],'default':'reading','description':'reading for a user retrieval request; learning for a learning-video topic.'}
        entry['budget']={'description':'Task budget overrides within the host limit; omitted fields use configured values.','type':'object','properties':{'max_read_units':{'type':'integer','minimum':1, 'description': 'Maximum material read units for this task; not a token limit.'},'exploration_budget_ratio':{'type':'number','minimum':0,'maximum':1, 'description': 'Share of material read budget reserved for exploration, from 0 to 1.'},'timeout_seconds':{'type':'number','exclusiveMinimum':0, 'description': 'Task wall-clock budget in seconds, including finalization.'}},'additionalProperties':False}
        entry['context']={'type':'object','description':'Necessary preceding context and verbatim user evaluation.'}
        from knowledge_decision import QUERY_PLAN_SCHEMA
        entry['query_plan']=dict(QUERY_PLAN_SCHEMA,description='Initial needs and queries. Expression carries text (scene clue), keywords (relation) and need (complete intent); information carries text. Indices follow array order.')
        entry['needs']={'type':'array','items':{'type':'string','enum':['expression','reference','profile']},
                        'description':'Expression/context need, factual information gap, or member identity need; may overlap.'}
        result.append(dict(name='declare_native_read', description='Reserve a native web read before execution. For exec, execute the returned native_input verbatim; its reading token binds actual call-ID results at finish. Do not reuse the token.', inputSchema={
            'type':'object','properties':{'task_id':{'type':'string', 'description': 'Opaque task_id returned by begin_reading_task; reuse unchanged for reads and completion.'},'native_tool':{'type':'string','enum':['exec'], 'description': 'Native execution tool name; this adapter currently accepts exec only.'},
                'native_input':{'type':'string', 'description': 'Original exec source for a native web read. Execute the returned native_input verbatim to preserve call association.'},'purpose':{'type':'string','enum':['targeted','explore'], 'description': 'targeted addresses the task goal; explore checks unexpanded material. Classify by purpose, not tool type.'},
                'reason':{'type':'string', 'description': 'Short factual basis for this action or stopping reason.'},'relation':{'type':'string', 'description': 'How this read relates to the original goal or learning topic; exploration may be unrelated, state that explicitly.'}},
            'required':['task_id','native_tool','native_input','purpose','reason','relation'],'additionalProperties':False}))
        return result

    def validate_control(self, name, arguments, *, schema=None):
        from jsonschema import Draft202012Validator
        if schema is None:
            schema = next(t['inputSchema'] for t in self.schemas([]) if t['name'] == name)
        errors = sorted(Draft202012Validator(schema).iter_errors(arguments),
                        key=lambda error: (str(list(error.absolute_path)), error.validator))
        if not errors:
            return
        issues = []
        for error in errors[:8]:
            issue = dict(path=list(error.absolute_path), rule=error.validator)
            if error.validator == 'required':
                issue['missing_fields'] = [k for k in error.validator_value if k not in error.instance]
            elif error.validator == 'additionalProperties':
                issue['unexpected_fields'] = sorted(set(error.instance) - set(error.schema.get('properties', {})))
            elif error.validator in ('type', 'enum', 'const', 'minimum', 'maximum', 'minLength'):
                issue['expected'] = error.validator_value
            else:
                issue['instruction'] = 'Follow the inputSchema for this field in tools/list.'
            if issue not in issues:
                issues.append(issue)
        rejected = ControlArgumentsError(name, issues)
        # Scope-level audit: a rejected task_id is not trusted for task attribution.
        write_record(self.root / ('control-rejected-' + uuid.uuid4().hex + '.json'),
                     dict(tool=name, arguments=arguments, result=rejected.details,
                          timestamp=time.time(), executed=False, budget_charged=False))
        raise rejected

    def control(self, name, arguments):
        self.validate_control(name, arguments)
        if name == 'begin_reading_task':
            task_id = self.begin(**arguments)
            return {'task_id': task_id, **json.loads((self.folder(task_id)/'protocol.json').read_text(encoding='utf-8')), 'budget_remaining': self.remaining(self.folder(task_id))}
        if name == 'declare_native_read':
            from native_web_trace import NativeWebRecorder
            return NativeWebRecorder(self).reserve(**arguments)
        import os
        from native_web_trace import sync_native_reads
        sessions=self.config.get('native_sessions_directory')
        if not sessions and os.environ.get('CODEX_HOME'):
            sessions=str(Path(os.environ['CODEX_HOME'])/'sessions')
        if sessions:sync_native_reads(self,arguments['task_id'],sessions)
        try:
            report = self.finish(**arguments)
        except ValueError as exc:
            folder=self.folder(arguments['task_id'])
            write_record(folder / ('completion-attempt-' + uuid.uuid4().hex + '.json'),
                         {'arguments':arguments,'error':str(exc),'status':'rejected','timestamp':time.time()})
            self.report(folder)
            raise
        return {'recorded': True, 'stop_reason': report['stop_reason'],
                'reads': len(report['reads']), 'budget_remaining': report['completion']['budget_remaining']}
