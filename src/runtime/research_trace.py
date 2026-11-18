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
        self.application = None
        self.root = Path(config['root'])
        self.root.mkdir(parents=True, exist_ok=True)

    def bind_application(self, application):
        self.application=application
        return self

    def query_context(self, folder):
        from knowledge_decision import QUERY_DECISION_VERSION, query_task
        context=json.loads((folder/'context.json').read_text(encoding='utf-8'))
        if context.get('task_context',{}).get('decision_contract',{}).get('version')!=QUERY_DECISION_VERSION:
            return None
        if self.application is None:raise ValueError('query_application_required')
        if context['audit_scope']!=self.config['scope']:raise ValueError('reading_scope_mismatch')
        selected=query_task(self.application,folder.name)
        if selected.get('task_report')!=str((folder/'report.json').resolve()):raise ValueError('reading_task_binding_changed')
        return selected

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
        remaining=self.task_budget(folder).remaining()
        if self.application is not None and self.query_mode():
            from knowledge_turn_budget import TurnBudget
            from decision_read_budget import remaining_with_disclosure
            remaining=remaining_with_disclosure(remaining,TurnBudget(self.application.context['budget_path']))
        return remaining

    def task_budget(self,folder):
        context=json.loads((folder/'context.json').read_text(encoding='utf-8'))
        if context.get('task_context',{}).get('decision_contract'):
            from decision_read_budget import DecisionReadBudget
            return DecisionReadBudget(folder/'budget.db')
        return ReadBudget(folder/'budget.db', now=time.time)

    def read_timeout(self,path):
        ledger=self.task_budget(path.parent)
        record=json.loads(path.read_text(encoding='utf-8'))
        stage=record.get('query_read_stage')
        seconds=(ledger.timeout(stage=stage) if stage else ledger.timeout()) if hasattr(ledger,'timeout') else ledger.remaining()['read_seconds']
        if record['tool']=='watch_video':
            poll=ledger.remaining().get('video_polls',{}).get(ReadBudget.video_key(record['arguments']))
            if poll is not None:seconds=min(seconds,poll['seconds'])
        return seconds

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
        selected=self.query_context(folder)
        if selected is not None:
            from knowledge_decision import query_read_access, query_execution
            route=resolve(tool,args,purpose,selected['task_arguments']['query_plan'],query_records=selected['queries'])
            row=selected['queries'][route['query_index']]
            access=query_read_access(self.application,self.task_budget(folder),selected,row,tool)
            if not access['can_read']:
                if row['decision_state']=='selected' and access['reason']!='reading_task_closed':
                    query_execution(self.application,folder.name,row['query_id'],'budget_blocked',reason=access['reason'])
                raise ValueError(access['reason'])
        elif tool in ROUTED:
            context=json.loads((folder/'context.json').read_text(encoding='utf8'))
            route=resolve(tool,args,purpose,context['task_context'].get('query_plan'),context.get('needs',[]))
        before = self.remaining(folder)
        ledger=self.task_budget(folder)
        try:
            index = ledger.reserve(tool, purpose.get('purpose'), purpose.get('reason'), args,
                                   **({'stage':access['stage'],'video_policy':{'max_calls':10,'timeout_seconds':180}} if selected is not None else {}))
        except ValueError as exc:
            if selected is not None and row['decision_state']=='selected':
                query_execution(self.application,folder.name,row['query_id'],'budget_blocked',reason=str(exc))
            raise
        record = dict(read_id=index, tool=tool, arguments=args,
                      action={'kind': tool, 'purpose': purpose['purpose']},
                      purpose_record={'question': purpose['reason'], 'relation_reason': relation,
                                      'prior_observation': purpose.get('prior_observation'),
                                      'source': 'model_declared_before_call'},
                      budget_before=before, started_at=time.time(),
                      result={'status': 'pending', 'images': []})
        if route is not None:record['query_route']=route
        if selected is not None:
            from knowledge_turn_budget import TurnBudget
            record['query_read_stage']=access['stage']
            record['delivery_turn_id']=TurnBudget(self.application.context['budget_path']).current()
            query_execution(self.application,folder.name,route['query_id'],'running',read_id=str(index))
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
        if self.query_context(path.parent) is not None:
            from knowledge_decision import query_execution
            query_execution(self.application,path.parent.name,record['query_route']['query_id'],
                            'failed' if record['result']['status']=='error' else 'completed',read_id=str(record['read_id']))
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
        budget=None
        if self.query_context(path.parent) is not None:
            from knowledge_turn_budget import TurnBudget
            budget=TurnBudget(self.application.context['budget_path'])
        return self.delivery(path, response,turn_budget=budget,elapsed=elapsed)

    def evidence_reference(self, path):
        """Locate an executed read using the executor's own task and read IDs."""
        record = json.loads(path.read_text(encoding='utf-8'))
        return {'kind':'research_task','task_id':path.parent.name,
                'path':str(path.parent/'report.json'),'read_id':record['read_id'],'read_path':str(path)}

    def delivery(self, path, response, *, turn_budget=None, elapsed=0, upstream=None):
        """Persist the same bounded result and budget receipt sent to the caller."""
        from reading_result import model_response
        response = model_response(response)
        turn_receipt=None
        for block in response.get('result',{}).get('content',[]):
            if block.get('type')=='text':
                try: turn_receipt=json.loads(block['text']).get('knowledge_turn_budget',turn_receipt)
                except (ValueError,AttributeError):pass
        record = json.loads(path.read_text(encoding='utf-8'))
        ledger=self.task_budget(path.parent)
        if hasattr(ledger,'disclose'):
            from reading_result import body_of
            raw=body_of(response)
            failed=bool(response.get('error') or response.get('result',{}).get('isError') or raw.get('error'))
            charged_response=None
            def deliver_material(material):
                nonlocal charged_response,turn_receipt
                from copy import deepcopy
                projected=deepcopy(response)
                if material is None and not failed:
                    missing={'error':'probe_material_does_not_fit: commit with existing evidence','material':None}
                    projected['result']={'isError':True,'structuredContent':missing,
                        'content':[{'type':'text','text':json.dumps(missing,ensure_ascii=False)}]}
                elif not failed:
                    images=[b for b in projected.get('result',{}).get('content',[]) if b.get('type')=='image']
                    projected['result']={'structuredContent':material,
                        'content':[{'type':'text','text':json.dumps(material,ensure_ascii=False)},*images]}
                charged_response=turn_budget.deliver(record.get('delivery_turn_id',turn_budget.current()),
                    record['tool'],record['arguments'],projected,elapsed,upstream=response if upstream is None else upstream)
                charged_body=body_of(charged_response)
                turn_receipt=charged_body.get('knowledge_turn_budget')
                for block in charged_response.get('result',{}).get('content',[]):
                    if block.get('type')=='text':
                        try:turn_receipt=json.loads(block['text']).get('knowledge_turn_budget',turn_receipt)
                        except (ValueError,AttributeError):pass
                if charged_response.get('error') or charged_response.get('result',{}).get('isError') or charged_body.get('error'):
                    return None
                return charged_body
            material,coverage=ledger.disclose(record['read_id'],None if failed else raw,
                deliver=deliver_material if turn_budget is not None else None)
            if charged_response is not None:
                response=charged_response
                raw=body_of(response)
                failed=bool(response.get('error') or response.get('result',{}).get('isError') or raw.get('error'))
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
                   'budget_remaining':self.remaining(path.parent),'error':error}
            if turn_receipt is not None:value['knowledge_turn_budget']=turn_receipt
            images=[block for block in response.get('result',{}).get('content',[]) if block.get('type')=='image']
            response={'jsonrpc':response.get('jsonrpc','2.0'),'id':response.get('id'),'result':{
                'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)},*images],
                'structuredContent':value,'isError':failed}}
            if self.query_context(path.parent) is not None:
                from knowledge_decision import query_execution
                value['query_id']=record['query_route']['query_id']
                value['query_index']=record['query_route']['query_index']
                if failed or material is None:
                    response['result']['content']=response['result']['content'][:1]
                    response['result']['isError']=True
                    value['status']='error'
                state=('budget_blocked' if error and ('budget' in error or 'turn_changed' in error or 'does_not_fit' in error) else
                       'failed' if error else 'completed')
                query_execution(self.application,path.parent.name,value['query_id'],state,reason=error)
                response['result']['content'][0]['text']=json.dumps(value,ensure_ascii=False)
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
        from decision_read_budget import exhausted_dimensions
        dimensions=exhausted_dimensions(remaining) if 'total_calls' in remaining else []
        exhausted=bool(dimensions) if 'total_calls' in remaining else reading_budget_exhausted(remaining)
        if stop_reason == 'budget_exhausted' and not exhausted:
            raise ValueError('budget_not_exhausted: '+json.dumps(remaining))
        completion = dict(stop_reason=stop_reason, reason=reason, conclusion=conclusion,
                          basis=basis, budget_remaining=remaining,
                          timestamp=time.time())
        if self.query_mode():completion['exhausted_dimensions']=dimensions
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
        if self.application is not None and (folder/'decision.json').exists() and self.query_context(folder) is not None:
            from knowledge_decision import query_result
            selected=self.query_context(folder)
            public=query_result(selected,self.remaining(folder),app=self.application,ledger=self.task_budget(folder))
            report['queries']=public['queries']
            for row,query in zip(report.get('query_routes',[]),selected['queries']):row['query_id']=query['query_id']
        if (folder/'decision.json').exists():report['knowledge_decision']=json.loads((folder/'decision.json').read_text(encoding='utf-8'))
        # Separate proxies may finish reads concurrently; each evidence file remains authoritative.
        write_record(folder / 'report.json', report)
        return report

    def query_mode(self):
        policy=self.application.context['policy'] if self.application else self.config.get('knowledge_application',{})
        return policy.get('decision_granularity')=='query'

    @staticmethod
    def query_reference_schema(schema):
        schema['properties'].update(query_id={'type':'string','minLength':1,
            'description':'Stable query_id returned for this task. Reuse it for candidate, body, web and video reads.'},
            query_index={'type':'integer','minimum':0,'description':'Compatibility index into the frozen plan; if query_id is also supplied they must identify the same query.'})
        schema['anyOf']=[{'required':['query_id']},{'required':['query_index']}]
        return schema

    def schemas(self, tools, *, require_context=True, task_id=None):
        # Unbound chat proxies retain their shared schema. A bound research
        # gateway advertises selectors only for its own frozen plan.
        has_plan = True
        if task_id is not None:
            context=json.loads((self.folder(task_id)/'context.json').read_text(encoding='utf-8'))
            has_plan=bool(context.get('task_context',{}).get('query_plan'))
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
            if tool['name'] in ROUTED and has_plan:
                schema['properties']['_reading']['properties']['query_index']={'type':'integer','minimum':0,
                    'description':'0-based index in this task’s query_plan. Use for tag-only searches, reworded queries and page reads when the plan has multiple queries.'}
            if self.query_mode():
                self.query_reference_schema(schema['properties']['_reading'])
                tool['description']=tool.get('description','')+' Every read uses the task’s query_id and current permission; pending queries have only bounded local overview access. All queries share one task budget.'
            if require_context:
                schema['required'] = list(dict.fromkeys(schema.get('required', []) + ['_reading']))
            else:
                tool['description'] = tool.get('description', '') + ' 普通聊天按需读取可省略 _reading；检索任务须填写生成协议中的 _reading，使用任务独立预算并记录轨迹。'
            if tool['name']=='watch_video':
                counting=('每次准备或查询计入所有查询共享的总调用额度。' if self.query_mode() else '不占定向/探索补读次数。')
                tool['description'] = tool.get('description','') + ' 检索任务中，首次准备与后续查询每视频共最多10次、从首次准备起最多180秒，且受任务总时间限制；'+counting+'超限时保留未就绪状态，用已有材料收尾。'
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
        if self.query_mode():self.query_reference_schema(result[-1]['inputSchema'])
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
