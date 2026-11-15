"""One knowledge decision, with optional pre-decision reads of the same task."""
from copy import deepcopy
from contextlib import closing
import hashlib
import json
from pathlib import Path
from knowledge_query import GUIDE as ROUTE_GUIDE
from knowledge_query import QUERY_TEXT_MAX
import sqlite3
import time
import uuid

VERSION = 'knowledge-decision-v1'
LOCAL_READS = {'get_knowledge_tag_index', 'search_knowledge_tags',
               'find_knowledge_entries', 'read_knowledge_entry', 'retrieve_knowledge_candidates'}
DEFAULTS = {'max_calls': 0, 'max_seconds': 0, 'max_characters': 0,
            'total_calls': 6, 'total_seconds': 300, 'reserve_seconds': 60}
from knowledge_query import QUERY_PLAN_SCHEMA, query_guidance
QUERY_GUIDANCE = query_guidance()
CONFIG_SCHEMA = {'type': 'object', 'properties': {
    key: {'type': 'integer' if key.endswith(('calls', 'characters')) else 'number',
          'minimum': 1 if key in ('total_calls', 'total_seconds') else 0, 'default': value}
    for key, value in DEFAULTS.items()}, 'additionalProperties': False}

FINAL_REPORT_SCHEMA={'type':'object','properties':{
    'reply_text':{'type':'string', 'description': 'Final proposed reply text used to verify material applications.'},
    'applications':{'type':'array','items':{'type':'object','properties':{
        'read_id':{'type':'string', 'description': 'Actual read identifier returned in the tool result; preserve its type and namespace.'},'tag_ids':{'type':'array','items':{'type':'string'}, 'description': 'IDs of relevant Tags from the material or Tag search.'},
        'context_event_ids':{'type':'array','items':{'type':'string'},'minItems':1, 'description': 'Delivered event ID strings to which this application relates.'},
        'reply_excerpt':{'type':'string','minLength':1, 'description': 'Exact substring of reply_text showing the application.'}},
        'required':['read_id','tag_ids','context_event_ids','reply_excerpt'],'additionalProperties':False}, 'description': 'Actual material uses in the final reply; [] when no retrieved material was used.'},
    'completion':{'type':'object','properties':{'stop_reason':{'type':'string', 'description': 'Stopping reason recorded for this reply; use the reason returned by the reading task when available.'},'reason':{'type':'string', 'description': 'Short factual basis for this action or stopping reason.'}},
                  'required':['stop_reason','reason'],'additionalProperties':False, 'description': 'Stopping reason and brief factual basis recorded for this result.'}},
    'required':['reply_text','applications','completion'],'additionalProperties':False}


def settings(value=None):
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value)-set(DEFAULTS):
        raise ValueError('invalid_decision_probe_config')
    result = {**DEFAULTS, **value}
    import math
    for key, v in result.items():
        if type(v) not in (int, float) or not math.isfinite(v) or v < 0:
            raise ValueError('invalid_decision_probe_config:'+key)
        if key.endswith(('calls', 'characters')) and type(v) is not int:
            raise ValueError('invalid_decision_probe_config:'+key)
    if (result['total_calls'] < 1 or result['total_seconds'] <= 0
            or result['reserve_seconds'] >= result['total_seconds']
            or result['max_calls'] > result['total_calls']):
        raise ValueError('invalid_decision_probe_limits')
    return result


DECISION_GUIDANCE = (
    '第一步，检查收益依据。内容收益包括结论、条件或推导的改善；表达收益包括适用于当前交流的表达方式。'
    '条目带有与当前上下文相关的有效 Tag，且其中表达可用于本次回复，即具备明确的预期表达收益；最终以实际应用核验。'
    '需求类 Tag 也可构成相关性依据。已有答案可写时仍检查这两类收益。'
    '证据不足可在允许的裁决查阅额度内查 Tag、候选或正文；证据足够时提前结束。查到的材料与任务总额度继续复用。'
    '第二步，只提交一次最终 subjective_inclination。0 要求具体依据足以排除本次补读的内容和表达收益；'
    '1 要求具体依据确认收益；其余给出大于0、小于1的主观倾向。中间值越高，越倾向继续读取；'
    '该值表示补读倾向，资料正确性、搜索成功率和判断置信度另行判断。'
    '已有一版回答、尚未查阅、一次未命中或额度用尽，都不足以独立支持0。'
    '仅找到宽泛 Tag 而未确认表达用途时保留不确定性。'
    '在 objective、expected_gain 中简述目标、依据与材料引用。轻量查阅已取得可用材料时可提交1并直接复用材料收尾。')


def initial_arguments():
    return {'decision_stage':'assess','goal':'查明尚未知晓的物件加成数值',
        'query_plan':{'information_need':'回答所需数值未知','expression_need':'',
                      'queries':[{'purpose':'information','text':'物件名 加成数值'}]},
        '_knowledge':{'action':'research','trigger':'information_gap',
                      'target_event_ids':['原消息ID'],'objective':'补齐回答必需的加成数值','expected_gain':'当前材料缺少数值，查阅可补足答案'}}


def initial_example_guidance():
    improvement = initial_arguments()
    improvement.update(goal='已有加成数值，查找可补充的使用案例',
        query_plan={'information_need':'已有足够信息回答数值，补充使用案例','expression_need':'',
                    'queries':[{'purpose':'information','text':'物件名 使用案例'}]})
    improvement['_knowledge'].update(trigger='answer_improvement',objective='改善已有够用答案',
                                     expected_gain='已有可靠加成数值，可补充案例以便理解')
    return ('首次 assess 示例（回答所需数值未知）：'+json.dumps(initial_arguments(),ensure_ascii=False,separators=(',',':'))+'\n'
        '首次 assess 对照示例（已有足够信息）：'+json.dumps(improvement,ensure_ascii=False,separators=(',',':'))+'\n'
        'trigger 按开始本次查阅前的信息状态分类：缺少回答必需事实用 information_gap；'
        '已有足够信息作答，补充案例或表达可改善答案时用 answer_improvement；'
        '表达需求和话题深入分别用 expression、discussion_deepening。示例类别不是默认值；'
        'commit 时填入开始本次查阅时的起因，即使资料已补齐原缺口。')


def guidance():
    return ('## 知识应用 '+VERSION+'\n'+QUERY_GUIDANCE+'\n'
        +initial_example_guidance()+'\n'
        +ROUTE_GUIDE+'\n'
        '按实际需求填写；queries[].purpose 使用 information 或 expression，查询文本字段为 text；'
        'trigger 按工具枚举选择，目标消息 ID 写入 _knowledge.target_event_ids。\n'+DECISION_GUIDANCE+'\n'
        '唯一裁决入口为 begin_reading_task：需要轻量查阅时 decision_stage=assess，_knowledge 不填倾向；'
        '证据足够时 decision_stage=commit，提交最终倾向，可直接首次 commit。'
        'assess 返回 task_id，所有读取用 _reading 记录 task_id、purpose、reason、relation；'
        '提交裁决沿用同一 task_id 与原消息集合。相同消息集合只保存首次裁决，重试不重新采样。'
        'continue_reading 仅表示是否允许裁决后的新增读取；已有材料始终可复用，true 也不要求额外读取。'
        '按返回余额及时间收尾，查阅额度耗尽仍可提交中间倾向；总时间用尽且尚无裁决时记录 decision_missing。'
        '完成用 finish_reading_task 记录原因、结论。回复规划仅引用 decision_ids 与实际采用的 used_read_ids；'
        '采用材料用 knowledge_application.read_id 字符串定位。最终报告的 applications 记录 read_id、tag_ids、'
        'context_event_ids、reply_excerpt，分别指向实际已读材料、相关 Tag、上下文消息与回复中的原句；无应用时为空数组。'
        '后台研究沿用同一任务及预算。')


TOOL_DESCRIPTION = 'Create or reuse the knowledge-reading decision for the original delivered messages. Use assess with goal and _knowledge (no subjective_inclination) for bounded pre-decision reads; use commit with _knowledge.subjective_inclination and the returned task_id (or goal on first call). Returns task_id, decision_id, continue_reading, remaining budget and execution_prompt. Reuse IDs on retry. Finish with finish_reading_task after reads. Detailed decision rules are in execution_prompt.'
TOOL_DESCRIPTION += '\n'+initial_example_guidance()



def begin_schema():
    from knowledge_application import envelope_schema
    properties = deepcopy(envelope_schema()['properties'])
    properties = {k: properties[k] for k in ('action','trigger','target_event_ids','objective','expected_gain','subjective_inclination')}
    properties['action'] = {'type':'string','const':'research','description':'This entry declares a research decision; always research, including assess.'}
    properties['subjective_inclination']['description'] = 'Final inclination in [0,1]: 0 requires evidence excluding benefit; 1 requires evidence confirming benefit; otherwise an intermediate value.'
    meta = {'type':'object','properties':properties,
            'required':['action','trigger','target_event_ids','objective','expected_gain'],
            'additionalProperties':False}
    return {'type':'object','properties':{
        'decision_stage':{'type':'string','enum':['assess','commit'], 'description': 'assess creates/reuses a pending task with goal and no inclination; commit supplies subjective_inclination and either the same task_id or a first-call goal.'},
        'task_id':{'type':'string', 'description': 'Opaque task_id returned by begin_reading_task; reuse unchanged for reads and completion.'}, 'goal':{'type':'string','minLength':1, 'description': 'Original task objective. Required for assess and for the first commit without task_id.'},
        'context':{'type':'object', 'description': 'Only necessary conversation context and already-read evidence; original request and quotes remain data.'}, 'task_mode':{'type':'string','enum':['reading','learning'], 'description': 'reading for a user retrieval request; learning for a learning-video topic.'},
        'query_plan':dict(deepcopy(QUERY_PLAN_SCHEMA),description='Initial needs and up to four queries. Expression queries carry text (scene clue), keywords (relation) and need (complete intent); information carries text. Reuse the returned plan on retry.'),
        'needs':{'type':'array','items':{'type':'string','enum':['expression','reference','profile']}, 'description': 'Applicable needs: expression, reference, profile; several may apply.'},
        '_knowledge':dict(meta,description='Knowledge decision declaration. Use current delivered event IDs; assess omits subjective_inclination, commit includes it.')},'required':['decision_stage','_knowledge'],'additionalProperties':False,
        'allOf':[
            {'if':{'properties':{'decision_stage':{'const':'assess'}}},
             'then':{'required':['goal'],'properties':{'_knowledge':{'not':{'required':['subjective_inclination']}}}}},
            {'if':{'properties':{'decision_stage':{'const':'commit'}}},
             'then':{'anyOf':[{'required':['task_id']},{'required':['goal']}],
                     'properties':{'_knowledge':{'required':['subjective_inclination']}}}}]}


def read_schema(tool):
    result=deepcopy(tool)
    schema=result['inputSchema'];properties=schema['properties']
    if 'limit' in properties:
        properties['limit'].update(minimum=1,maximum=2400 if tool['name']=='read_knowledge_entry' else 20)
    if 'revision' in properties:properties['revision']['minimum']=1
    if 'offset' in properties:properties['offset']['minimum']=0
    schema['additionalProperties']=False
    return result


def validate_query_plan(plan):
    from jsonschema import Draft202012Validator
    if not Draft202012Validator(QUERY_PLAN_SCHEMA).is_valid(plan):
        raise ValueError('invalid_query_plan')
    seen=set()
    for q in plan['queries']:
        text=q['text']; key=(q['purpose'],text.casefold())
        if text.strip()!=text or not plan[q['purpose']+'_need'].strip():
            raise ValueError('query_plan_need_mismatch')
        # Older recorded purpose/text plans remain readable; new semantic fields
        # must form one complete route rather than silently dropping a field.
        if 'keywords' in q or 'need' in q:
            from knowledge_query import validate_candidate_arguments
            validate_candidate_arguments(q['purpose'], text, q.get('keywords',''), q.get('need',''))
        if key in seen:raise ValueError('duplicate_query_plan_text')
        seen.add(key)


def prepare_begin(app, arguments):
    from jsonschema import Draft202012Validator
    errors = list(Draft202012Validator(begin_schema()).iter_errors(arguments))
    if errors:
        if not isinstance(arguments, dict) or arguments.get('decision_stage') not in ('assess', 'commit'):
            errors = [e for e in errors if not list(e.absolute_schema_path) or list(e.absolute_schema_path)[0] != 'allOf']
        problems = []
        for e in errors[:8]:
            item = {'path': list(e.absolute_path), 'rule': e.validator}
            if e.validator == 'required':
                item['missing'] = [k for k in e.validator_value if not isinstance(e.instance, dict) or k not in e.instance]
            elif e.validator == 'additionalProperties':
                item['unexpected'] = sorted(set(e.instance) - set(e.schema.get('properties', {})))
            elif e.validator == 'not':
                item['omit'] = e.validator_value.get('required', [])
            elif e.validator == 'anyOf':
                item['required_alternatives'] = [v['required'] for v in e.validator_value if 'required' in v]
            else:
                item['expected'] = e.validator_value
            problems.append(item)
        raise ValueError('invalid_decision_parameters: '+json.dumps(
            {'argument_errors': problems, 'executed': False, 'recovery': 'correct_arguments; do not repeat unchanged'}, ensure_ascii=False))
    if 'query_plan' in arguments.get('context',{}):
        raise ValueError('query_plan_requires_top_level_parameter')
    if 'query_plan' in arguments:
        validate_query_plan(arguments['query_plan'])
    args=deepcopy(arguments);meta=args.pop('_knowledge');targets=meta['target_event_ids']
    if not meta['objective'].strip():raise ValueError('knowledge_objective_required')
    identity=json.dumps([app.context['session_id'],app.context['run_id'],app.context['configuration_sha256'],sorted(set(targets))],ensure_ascii=False)
    ref=hashlib.sha256(identity.encode()).hexdigest()[:32]
    with closing(sqlite3.connect(app.path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT turn_id FROM current WHERE slot=1').fetchone()
        if not row:raise ValueError('application_turn_missing')
        turn=row[0]
        prior=db.execute('SELECT body FROM decisions WHERE id=?',(ref,)).fetchone()
        if not prior:
            for old_ref, old in db.execute('SELECT id,body FROM decisions ORDER BY rowid'):
                if set(json.loads(old).get('target_event_ids',[]))==set(targets):
                    ref,prior=old_ref,(old,);break
        if args.get('task_id') and (not prior or args['task_id']!=ref):
            raise ValueError('knowledge_task_decision_mismatch')
        if prior:
            selected=json.loads(prior[0])
            if selected.get('decision_protocol')!=VERSION:
                raise ValueError('decision_protocol_mismatch: retain original decision_ids')
            app._validate_decision_scope(db,[ref],turn,'begin_reading_task',args)
        else:
            from knowledge_application import message_ids
            event,started=db.execute('SELECT event,at FROM turns WHERE id=?',(turn,)).fetchone()
            if set(targets)-message_ids(json.loads(event)):raise ValueError('knowledge_target_not_delivered')
            if not args.get('goal'):raise ValueError('reading_goal_required')
            selected={**meta,'action':'research','turn_id':turn,'task_id':ref,
                      'decision_protocol':VERSION,'state':'pending_decision',
                      'started_at':started,'basis':'awaiting_model_commit',
                      'task_arguments':{k:deepcopy(args[k]) for k in ('goal','context','task_mode','needs','query_plan') if k in args}}
            selected.pop('subjective_inclination',None)
            db.execute('INSERT INTO decisions VALUES (?,?,?)',(ref,turn,json.dumps(selected,ensure_ascii=False)))
        args['task_id']=ref
        token=uuid.uuid4().hex
        db.execute('INSERT INTO calls VALUES (?,?,?,?,?,?,NULL)',(token,turn,'begin_reading_task',json.dumps([ref]),
            json.dumps({'upstream':args,'declaration':meta,'reused':bool(prior)},ensure_ascii=False),time.time()))
    return token,args


def intercept_begin(app, db, call, selected, trace):
    if trace is None:raise ValueError('reading_entry_not_configured')
    saved=json.loads(call[2]);args=saved['upstream'];meta=saved['declaration'];ref=selected['task_id']
    config=settings(app.context['policy'].get('decision_probe'))
    config['total_calls']=min(config['total_calls'],trace.config.get('max_read_units',10))
    config['total_seconds']=min(config['total_seconds'],trace.config.get('timeout_seconds',300))
    config['reserve_seconds']=min(config['reserve_seconds'],config['total_seconds'])
    parameters=deepcopy(selected['task_arguments'])
    parameters['context']={**parameters.get('context',{}),'decision_contract':{
        'version':VERSION,'started_at':selected['started_at'],'limits':config},
        'knowledge_application':{'session_id':app.context['session_id'],'run_id':app.context['run_id'],
                                 'target_event_ids':selected['target_event_ids']}}
    path=str((trace.root/ref/'report.json').resolve())
    if selected.get('task_report') and selected['task_report']!=path:raise ValueError('reading_task_binding_changed')
    selected['task_report']=path
    trace_arguments=deepcopy(parameters)
    trace.begin_once(ref,trace_arguments)
    folder=trace.folder(ref);ledger=trace.task_budget(folder)
    if selected['state']=='pending_decision' and ledger.remaining()['total_seconds']<=0:
        if not (folder/'completion.json').exists():
            trace.finish(ref,'cancelled','decision_missing: total task time exhausted','保留已读材料；未收到最终裁决。',basis='executor_control')
        selected.update(state='closed',stop_reason='decision_missing')
    elif args['decision_stage']=='commit' and selected['state']=='pending_decision':
        from knowledge_application import sample
        gate=sample(meta['subjective_inclination'],app.context['policy'])
        selected.update(meta)
        selected.update(action='research' if gate['retrieve'] else 'reply',
                        state='decided',gate=gate,decision_id=ref,basis='model_declared_host_sampled')
    db.execute('UPDATE decisions SET body=? WHERE id=?',(json.dumps(selected,ensure_ascii=False),ref))
    # The first draw is durable before publishing file/ledger receipts. A retry
    # reconciles these projections without evaluating a second draw.
    db.commit()
    db.execute('BEGIN IMMEDIATE')
    if selected['state']!='pending_decision':
        ledger.decide(selected['state'],selected.get('gate',{}).get('retrieve',False))
    trace.report(folder)
    available=[]
    for call_id, refs, observation in db.execute('SELECT id,refs,observation FROM calls WHERE observation IS NOT NULL'):
        observed=json.loads(observation)
        if ref in json.loads(refs) and observed.get('read_id') and observed.get('status')=='ok':available.append(call_id)
    decision_id=selected.get('decision_id')
    state=selected['state']
    access=task_read_access(app,ledger);remaining=access['remaining']
    result={'protocol_version':VERSION,'task_id':ref,'decision_id':decision_id,'state':state,
            'target_event_ids':deepcopy(selected['target_event_ids']),
            'reused':saved['reused'],
            'query_plan':deepcopy(parameters.get('query_plan')),
            'query_plan_status':'recorded' if 'query_plan' in parameters else 'not_recorded',
            'continue_reading':selected.get('gate',{}).get('retrieve') if state!='closed' else False,
            'available_read_ids':available,'budget_remaining':remaining,
            'next_actions':next_actions(access),
            'execution_prompt':execution_prompt(state,remaining,parameters,access)}
    from research_trace import write_record
    write_record(folder/'decision.json',{k:deepcopy(selected[k]) for k in ('state','decision_id','gate','stop_reason') if k in selected})
    trace.report(folder)
    return result


def task_read_access(app,ledger,tool=None):
    from knowledge_turn_budget import TurnBudget
    access=ledger.read_access(tool)
    if access['can_read'] and TurnBudget(app.context['budget_path']).remaining()['remaining']<=0:
        access.update(can_read=False,reason='turn_disclosure_budget_exhausted')
    return access


def next_actions(access):
    if access['state']=='closed':return []
    tail=['commit'] if access['state']=='pending_decision' else ['finish']
    return (['read'] if access['can_read'] else [])+tail


def execution_prompt(state, remaining, parameters, access=None):
    actions=next_actions(access) if access else []
    stage=('当前待裁决：查阅额度已用尽或未开放，使用同一 task_id 提交 commit。'
           if state=='pending_decision' and access and not access['can_read'] else
           '当前待裁决：在剩余查阅额度内按需读取，然后使用同一 task_id 提交 commit。'
           if state=='pending_decision' else '当前裁决已固定：仅在 continue_reading 允许且仍需补读时新增读取；已有材料可直接复用收尾。'
           if state=='decided' else '任务已关闭，保留已有结果。')
    if state=='decided' and access and not access['can_read']:
        stage='当前裁决已固定：新增读取已关闭，复用已有材料并调用 finish_reading_task 收尾。'
    return (guidance()+'\n'+stage+'\n原始目标：'+parameters['goal']+
        '\n当前可执行动作：'+json.dumps(actions,ensure_ascii=False)+
        '\n本次需求与初始查询：'+json.dumps(parameters.get('query_plan'),ensure_ascii=False,separators=(',',':'))+
        '\n剩余预算：'+json.dumps(remaining,ensure_ascii=False,separators=(',',':'))+
        '\n每次被接受的资料调用计1次；裁决查阅同时扣总预算，失败也计数。'
        '剩余 read_seconds 用尽后停止读取，留出时间提交裁决、停止记录与回复。'
        '裁决查阅仅使用已配置的 Tag 目录、候选与正文工具；继续读取仍受工具白名单约束。')


class DecisionToolAccess:
    """Project existing task ledgers into the tools discoverable by this session."""
    def __init__(self,app,trace,tools):
        self.app=app;self.trace=trace;self.tools=set(tools)

    def names(self):
        names=self.tools-LOCAL_READS-{'finish_reading_task','declare_native_read'}
        from reading_tools import ALLOWED
        reads=self.tools & (ALLOWED | {'declare_native_read'})
        names-=reads
        with closing(sqlite3.connect(self.app.path)) as db:
            current=db.execute('SELECT turn_id FROM current WHERE slot=1').fetchone()
            current=current[0] if current else None
            decisions=[json.loads(body) for turn,body in db.execute('SELECT turn_id,body FROM decisions')
                       if turn==current or json.loads(body).get('action')=='research']
        for decision in decisions:
            task=decision.get('task_id')
            if not task or decision.get('decision_protocol')!=VERSION or decision.get('state')=='closed':continue
            if not (self.trace.root/task/'context.json').exists():continue
            folder=self.trace.folder(task)
            if (folder/'completion.json').exists():continue
            ledger=self.trace.task_budget(folder)
            if ledger.state()[0]=='decided':names.add('finish_reading_task')
            for tool in reads:
                if task_read_access(self.app,ledger,tool)['can_read']:names.add(tool)
        return names & self.tools

    def schemas(self,tools):
        names=self.names()
        return [tool for tool in tools if tool['name'] in names]
