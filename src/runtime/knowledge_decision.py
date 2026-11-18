"""One knowledge decision, with optional pre-decision reads of the same task."""
from copy import deepcopy
from contextlib import closing
import hashlib
import json
from pathlib import Path
from knowledge_query import GUIDE as ROUTE_GUIDE
from knowledge_query import QUERY_TEXT_MAX
from knowledge_query import routing_guidance, validate_contract_schema, query_error
import sqlite3
import time
import uuid

VERSION = 'knowledge-decision-v1'
LOCAL_READS = {'get_knowledge_tag_index', 'search_knowledge_tags',
               'find_knowledge_entries', 'read_knowledge_entry', 'retrieve_knowledge_candidates'}
DEFAULTS = {'max_calls': 0, 'max_seconds': 0, 'max_characters': 0,
            'total_calls': 6, 'total_seconds': 300, 'reserve_seconds': 60}
from knowledge_query import QUERY_PLAN_SCHEMA, query_guidance, QUERY_DECISION_VERSION, query_plan_schema, query_decision_schema
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


def effective_limits(value, host, started_at):
    """Freeze one task budget from policy and host bounds at its original start."""
    limits = settings(value)
    configured_seconds = limits['total_seconds']
    seconds = min(configured_seconds, host.get('timeout_seconds', 300))
    if host.get('deadline') is not None:
        seconds = min(seconds, host['deadline'] - started_at)
    if seconds <= 0:
        raise ValueError('time_budget_exhausted')
    limits['total_calls'] = min(limits['total_calls'], host.get('max_read_units', 10))
    limits['total_seconds'] = seconds
    if seconds != configured_seconds:
        limits['reserve_seconds'] *= seconds / configured_seconds
    limits['max_calls'] = min(limits['max_calls'], limits['total_calls'])
    limits['max_seconds'] = min(limits['max_seconds'], seconds - limits['reserve_seconds'])
    return limits


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


def initial_arguments(protocol_version=VERSION):
    if protocol_version not in (VERSION, QUERY_DECISION_VERSION):
        raise ValueError('unknown_knowledge_decision_protocol')
    return {'decision_stage':'assess','goal':'查明尚未知晓的物件加成数值',
        'query_plan':{'information_need':'回答所需数值未知','expression_need':'',
                      'queries':[{'purpose':'information','text':'物件名 加成数值'}]},
        '_knowledge':{'action':'research','trigger':'information_gap',
                      'target_event_ids':['原消息ID'],'objective':'补齐回答必需的加成数值','expected_gain':'当前材料缺少数值，查阅可补足答案'}}


def initial_example_guidance(protocol_version=VERSION):
    improvement = initial_arguments(protocol_version)
    improvement.update(goal='已有加成数值，查找可补充的使用案例',
        query_plan={'information_need':'已有足够信息回答数值，补充使用案例','expression_need':'',
                    'queries':[{'purpose':'information','text':'物件名 使用案例'}]})
    improvement['_knowledge'].update(trigger='answer_improvement',objective='改善已有够用答案',
                                     expected_gain='已有可靠加成数值，可补充案例以便理解')
    text = ('首次 assess 示例（回答所需数值未知）：'+json.dumps(initial_arguments(),ensure_ascii=False,separators=(',',':'))+'\n'
        '首次 assess 对照示例（已有足够信息）：'+json.dumps(improvement,ensure_ascii=False,separators=(',',':'))+'\n'
        'trigger 按开始本次查阅前的信息状态分类：缺少回答必需事实用 information_gap；'
        '已有足够信息作答，补充案例或表达可改善答案时用 answer_improvement；'
        '表达需求和话题深入分别用 expression、discussion_deepening。示例类别不是默认值；'
        'commit 时填入开始本次查阅时的起因，即使资料已补齐原缺口。')
    if protocol_version == QUERY_DECISION_VERSION:
        first = initial_arguments(protocol_version)
        first.update(decision_stage='commit',query_decisions=[{
            'query_index':0,'subjective_inclination':1,
            'expected_gain':'回答必需的加成数值未知，查阅可补足答案'}])
        existing = deepcopy(first)
        existing.pop('goal');existing.pop('query_plan')
        existing['task_id']='宿主返回的task_id'
        existing['query_decisions'][0].pop('query_index')
        existing['query_decisions'][0]['query_id']='宿主返回的query_id'
        text += ('\n首次 commit 示例：'+json.dumps(first,ensure_ascii=False,separators=(',',':'))+
                 '\n已有任务 commit 示例：'+json.dumps(existing,ensure_ascii=False,separators=(',',':'))+
                 '\n已有任务的标识替换为宿主实际返回值；读取用 _reading.query_id，首次提交计划用 query_index。')
    return text


def guidance(protocol_version=VERSION):
    if protocol_version == QUERY_DECISION_VERSION:
        return ('## 知识应用 '+QUERY_DECISION_VERSION+'\n'+query_guidance(protocol_version)+'\n'
            +initial_example_guidance(protocol_version)+'\n'+routing_guidance(protocol_version)+'\n'
            '唯一入口为 begin_reading_task。decision_stage=assess 时只提交初始计划、goal 与任务声明，'
            '不填 query_decisions；commit 才提交逐查询判断，可在首次调用同次提交完整计划与判断。'
            '首次 commit 每项用 query_index 对应同次计划；已有任务沿用 task_id，改用宿主返回的 query_id。'
            '同一查询重试或改写沿用首次结果，不重新抽样。_knowledge 只说明原任务、起因与目标消息，'
            '逐查询依据写在 query_decisions[].expected_gain。无新增查询时两个数组同时为空。'
            '信息和表达查询各自判断收益，不把一个查询的结果代替另一个。'
            '读取仅使用宿主已开放的动作和获准 query_id，_reading.purpose 仍为 targeted 或 explore。'
            'continue_reading 为任务摘要，执行以对应查询的 can_read 和剩余预算为准。'
            '已有材料可复用，获准读取也可提前收尾；后台与直接读取共用任务预算。'
            '完成用 finish_reading_task 保存停止原因、结论与实际材料应用。')
    if protocol_version != VERSION:
        raise ValueError('unknown_knowledge_decision_protocol')
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


def tool_contract(protocol_version=VERSION):
    """Shared discovery/validation contract; v2 is opt-in until runtime migration."""
    schema=begin_schema(protocol_version)
    description=TOOL_DESCRIPTION
    if protocol_version == QUERY_DECISION_VERSION:
        description=(
            'Create or reuse one reading task for the original messages. assess submits goal, query_plan and '
            '_knowledge without query_decisions. commit submits independent query_decisions with '
            'subjective_inclination and expected_gain per query: a first commit uses query_index in its '
            'query_plan; an existing task uses returned query_id and task_id. Preserve IDs and first '
            'decisions on retry. Reading permission is returned by the host per query; reuse existing '
            'materials and finish_reading_task when done. To append a genuinely new need, assess with '
            'task_id, the full query_plan retaining its original prefix, and context identifying the new '
            'evidence; commit the new returned IDs separately. Up to four queries share the original budget. '
            'Inspect runtime_state and can_read before reading.\n'+guidance(protocol_version))
    return {'name':'begin_reading_task','description':description,'inputSchema':schema}



def begin_schema(protocol_version=VERSION):
    if protocol_version == QUERY_DECISION_VERSION:
        result = begin_schema()
        props = result['properties']
        props['_knowledge']['properties'].pop('subjective_inclination')
        props['_knowledge']['description'] = 'Original task declaration; per-query inclinations belong in query_decisions.'
        for key in ('objective','expected_gain'):
            props['_knowledge']['properties'][key].update(minLength=1,pattern=r'\S')
        props['query_plan'] = query_plan_schema(QUERY_DECISION_VERSION)
        props['query_decisions'] = query_decision_schema()
        props['query_decisions']['description'] = 'One inclination and evidence per query. First commit uses query_index; an existing task uses query_id. Reuse the first decision on retry.'
        props['task_id'].update(minLength=1,pattern=r'\S')
        props['goal']['pattern']=r'\S'
        props['decision_stage']['description']='assess obtains query identities and bounded overview without final inclinations; commit supplies per-query decisions. A first commit can include the whole query plan.'
        result['allOf']=[
            {'if':{'not':{'required':['task_id']}},
             'then':{'required':['goal','query_plan']}},
            {'if':{'properties':{'decision_stage':{'const':'assess'}}},
             'then':{'not':{'required':['query_decisions']}}},
            {'if':{'properties':{'decision_stage':{'const':'commit'}}},
             'then':{'required':['query_decisions'],'allOf':[
                 {'if':{'required':['task_id']},
                  'then':{'properties':{'query_decisions':query_decision_schema('id')}},
                  'else':{'properties':{'query_decisions':query_decision_schema('index')}}}]}}]
        return result
    if protocol_version != VERSION:
        raise ValueError('unknown_knowledge_decision_protocol')
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


def validate_query_plan(plan, protocol_version=VERSION):
    from knowledge_query import validate_query_plan as validate
    validate(plan,protocol_version)


def validate_begin_arguments(arguments, protocol_version=VERSION):
    """Shared discovery/call contract; ownership and execution remain host checks."""
    from jsonschema import Draft202012Validator
    schema=begin_schema(protocol_version)
    if protocol_version==QUERY_DECISION_VERSION:
        validate_contract_schema(schema,arguments)
    errors = [] if protocol_version==QUERY_DECISION_VERSION else list(Draft202012Validator(schema).iter_errors(arguments))
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
                if protocol_version == QUERY_DECISION_VERSION and 'anyOf' in e.validator_value:
                    item['omit_one_of'] = [key for branch in e.validator_value['anyOf'] for key in branch.get('required',[])]
            elif e.validator == 'anyOf':
                item['required_alternatives'] = [v['required'] for v in e.validator_value if 'required' in v]
            else:
                item['expected'] = e.validator_value
            problems.append(item)
        raise ValueError('invalid_decision_parameters: '+json.dumps(
            {'argument_errors': problems, 'executed': False, 'recovery': 'correct_arguments; do not repeat unchanged'}, ensure_ascii=False))
    if 'query_plan' in arguments.get('context',{}):
        if protocol_version==QUERY_DECISION_VERSION:
            raise query_error('query_plan_requires_top_level_parameter',['context','query_plan'],'Move query_plan to the top level.')
        raise ValueError('query_plan_requires_top_level_parameter')
    if 'query_plan' in arguments:
        validate_query_plan(arguments['query_plan'],protocol_version)
    if protocol_version==QUERY_DECISION_VERSION and arguments['decision_stage']=='commit':
        from knowledge_query import validate_query_decisions
        initial='task_id' not in arguments
        validate_query_decisions(arguments['query_decisions'],plan=arguments.get('query_plan'),
                                 reference='index' if initial else 'id',require_all=initial)
    return deepcopy(arguments)


def prepare_begin(app, arguments, *, protocol_version=VERSION):
    version=protocol_version
    validate_begin_arguments(arguments,version)
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
            if selected.get('decision_protocol')!=version:
                raise ValueError('decision_protocol_mismatch: retain original decision_ids')
            app._validate_decision_scope(db,[ref],turn,'begin_reading_task',args)
        else:
            from knowledge_application import message_ids
            event,started=db.execute('SELECT event,at FROM turns WHERE id=?',(turn,)).fetchone()
            if set(targets)-message_ids(json.loads(event)):raise ValueError('knowledge_target_not_delivered')
            if not args.get('goal'):raise ValueError('reading_goal_required')
            selected={**meta,'action':'research','turn_id':turn,'task_id':ref,
                      'decision_protocol':version,'state':'pending_decision',
                      'started_at':started,'basis':'awaiting_model_commit',
                      'task_arguments':{k:deepcopy(args[k]) for k in ('goal','context','task_mode','needs','query_plan') if k in args}}
            selected.pop('subjective_inclination',None)
            db.execute('INSERT INTO decisions VALUES (?,?,?)',(ref,turn,json.dumps(selected,ensure_ascii=False)))
        if version==QUERY_DECISION_VERSION:
            if not prior:
                selected['queries']=[new_query(app,ref,i,q,meta,args.get('context',{}))
                                     for i,q in enumerate(args['query_plan']['queries'])]
            elif 'query_plan' in args:
                existing=selected['task_arguments']['query_plan']['queries'];incoming=args['query_plan']['queries']
                if len(incoming)<len(existing) or any(a['purpose']!=b['purpose'] for a,b in zip(existing,incoming)):
                    raise query_error('query_plan_identity_conflict',['query_plan'],'Keep original query slots and purposes; rewording retains their identities.')
                if len(incoming)>len(existing):
                    if (args['decision_stage']!='assess' or not args.get('task_id') or not args.get('context')):
                        raise query_error('query_addition_basis_required',['context'],'Use assess with task_id, the extended plan, and context identifying the new need or evidence.')
                    if selected['state']=='closed' or incoming[:len(existing)]!=existing:
                        raise query_error('query_plan_identity_conflict',['query_plan'],'Append to the unchanged plan of an open task.')
                    selected['queries'].extend(new_query(app,ref,i,q,meta,args['context'])
                        for i,q in enumerate(incoming) if i>=len(existing))
                    selected['task_arguments']['query_plan']=deepcopy(args['query_plan'])
                    selected['state']='pending_decision'
            resolve_query_declarations(selected,args)
            db.execute('UPDATE decisions SET body=? WHERE id=?',(json.dumps(selected,ensure_ascii=False),ref))
        args['task_id']=ref
        token=uuid.uuid4().hex
        db.execute('INSERT INTO calls VALUES (?,?,?,?,?,?,NULL)',(token,turn,'begin_reading_task',json.dumps([ref]),
            json.dumps({'upstream':args,'declaration':meta,'reused':bool(prior)},ensure_ascii=False),time.time()))
    return token,args


def new_query(app, task_id, index, query, declaration, context):
    return dict(query_id=uuid.uuid4().hex, task_id=task_id, query_index=index,
                purpose=query['purpose'], original_query=deepcopy(query),
                decision_state='pending', execution_state='not_started',
                origin={'target_event_ids':deepcopy(declaration['target_event_ids']),
                        'objective':declaration['objective'],'expected_gain':declaration['expected_gain'],
                        'context':deepcopy(context)}, configuration_binding=app.configuration())


def resolve_query_declarations(selected, args):
    rows=selected['queries'];by_id={r['query_id']:r for r in rows}
    resolved=[]
    for index,declaration in enumerate(args.get('query_decisions',[])):
        key=declaration.get('query_id')
        if key is not None:
            if key not in by_id:
                raise query_error('query_not_in_task',['query_decisions',index,'query_id'],'Use a query_id returned for this task.')
            row=by_id[key]
        else:
            i=declaration['query_index']
            if i>=len(rows):
                raise query_error('query_index_out_of_plan',['query_decisions',index,'query_index'],'Retain the original plan and query identities.')
            row=rows[i]
        resolved.append((row,declaration))
    return sorted(resolved,key=lambda pair:pair[0]['query_index'])


def query_task(app, task_id):
    with closing(sqlite3.connect(app.path)) as db:
        found=db.execute('SELECT body FROM decisions WHERE id=?',(task_id,)).fetchone()
    if not found:raise ValueError('knowledge_task_not_linked')
    selected=json.loads(found[0])
    if selected.get('decision_protocol')!=QUERY_DECISION_VERSION:raise ValueError('decision_protocol_mismatch')
    return selected


def query_read_access(app, ledger, selected, row, tool=None):
    from knowledge_turn_budget import TurnBudget
    state=row['decision_state']
    stage='pending_decision' if state=='pending' else 'decided'
    access=ledger.read_access(tool,stage=stage)
    reason=('reading_task_closed' if selected['state']=='closed' else
            'query_disallows_new_reads' if state not in ('selected','pending') else access['reason'])
    from decision_read_budget import remaining_with_disclosure, exhausted_dimensions
    access['remaining']=remaining_with_disclosure(access['remaining'],TurnBudget(app.context['budget_path']))
    if reason is None and 'turn_disclosure' in exhausted_dimensions(access['remaining']):
        reason='turn_disclosure_budget_exhausted'
    return dict(access,stage=stage,can_read=reason is None,reason=reason)


def query_execution(app, task_id, query_id, state, *, read_id=None, reason=None, read_stage=None):
    # A pre-read keeps its trace link and its own outcome. It is not
    # post-decision execution, even if the decision changed while it ran.
    pre_read = read_stage == 'pending_decision'
    if pre_read and read_id is None:
        return
    with closing(sqlite3.connect(app.path,timeout=10)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        selected=json.loads(db.execute('SELECT body FROM decisions WHERE id=?',(task_id,)).fetchone()[0])
        row=next(q for q in selected['queries'] if q['query_id']==query_id)
        if not pre_read:
            row['execution_state']=state
            if reason is not None:row['execution_reason']=reason
        if read_id is not None and read_id not in row.setdefault('trace_read_ids',[]):row['trace_read_ids'].append(read_id)
        db.execute('UPDATE decisions SET body=? WHERE id=?',(json.dumps(selected,ensure_ascii=False),task_id))


def query_result(selected, remaining, *, app, ledger):
    from knowledge_turn_budget import TurnBudget
    from decision_read_budget import remaining_with_disclosure
    if 'turn_disclosure' not in remaining:
        remaining=remaining_with_disclosure(remaining,TurnBudget(app.context['budget_path']))
    rows=[{key:deepcopy(row[key]) for key in ('query_id','query_index','purpose','decision_state','execution_state')}
          | {'can_read':False,'read_ids':[],'next_actions':[]} for row in selected['queries']]
    for public,row in zip(rows,selected['queries']):
        access=query_read_access(app,ledger,selected,row)
        public.update(can_read=access['can_read'],read_ids=deepcopy(row.get('read_ids',[])),
                      next_actions=['read'] if access['can_read'] else [])
    active=selected['state']!='closed'
    actions=(['begin_reading_task'] if any(r['decision_state']=='pending' for r in rows) else [])+['finish_reading_task'] if active else []
    if active and any(r['can_read'] for r in rows):actions.insert(0,'read')
    parameters={**selected['task_arguments'],'query_results':rows}
    result={'protocol_version':QUERY_DECISION_VERSION,'task_id':selected['task_id'],
            'decision_id':selected.get('decision_id'),'state':selected['state'],
            'target_event_ids':deepcopy(selected['target_event_ids']),
            'query_plan':deepcopy(parameters['query_plan']),'queries':rows,
            'query_plan_status':'recorded' if rows else 'no_query',
            'selection_allows_reading':active and any(r['decision_state']=='selected' for r in rows),
            'continue_reading':any(r['can_read'] for r in rows),'runtime_state':'ready',
            'budget_remaining':remaining,'next_actions':actions}
    result['execution_prompt']=execution_prompt(selected['state'],remaining,parameters,{'next_actions':actions},protocol_version=QUERY_DECISION_VERSION)
    return result


def intercept_queries(app, db, call, selected, trace):
    """Persist query decisions atomically, then reconcile filesystem projections."""
    if trace is None:raise ValueError('reading_entry_not_configured')
    saved=json.loads(call[2]);args=saved['upstream'];ref=selected['task_id']
    limits=effective_limits(app.context['policy'].get('decision_probe'),trace.config,selected['started_at'])
    parameters=deepcopy(selected['task_arguments'])
    parameters['context']={**parameters.get('context',{}),'decision_contract':{
        'version':QUERY_DECISION_VERSION,'started_at':selected['started_at'],'limits':limits},
        'knowledge_application':{'session_id':app.context['session_id'],'run_id':app.context['run_id'],
                                 'target_event_ids':selected['target_event_ids']}}
    path=str((trace.root/ref/'report.json').resolve())
    if selected.get('task_report') and selected['task_report']!=path:raise ValueError('reading_task_binding_changed')
    selected['task_report']=path
    trace.begin_once(ref,parameters)
    folder=trace.folder(ref);ledger=trace.task_budget(folder)
    if call[0]=='begin_reading_task' and args['decision_stage']=='commit' and selected['state']!='closed':
        from knowledge_sampling import sample as query_sample
        from knowledge_turn_budget import TurnBudget
        for row,declaration in resolve_query_declarations(selected,args):
            if row['decision_state']!='pending':continue
            row.update(subjective_inclination=declaration['subjective_inclination'],expected_gain=declaration['expected_gain'])
            row['learned_adjustment']=0
            row['decision_order']=sum('decision_order' in q for q in selected['queries'])
            row['decided_at']=time.time()
            remaining=ledger.remaining()
            remaining['turn_disclosure_remaining']=TurnBudget(app.context['budget_path']).remaining()['remaining']
            row['budget_at_decision']=remaining
            reason=('time_budget_exhausted' if remaining['read_seconds']<=0 else
                    'read_budget_exhausted' if remaining['total_calls']<=0 else
                    'turn_disclosure_budget_exhausted' if remaining['turn_disclosure_remaining']<=0 else None)
            if reason:
                row.update(decision_state='not_sampled_budget_blocked',execution_state='budget_blocked',reason=reason)
            else:
                row['gate']=query_sample(row['subjective_inclination'],app.context['policy'],random_source=app.random_source)
                row['decision_state']='selected' if row['gate']['retrieve'] else 'skipped_no_gain' if row['gate']['branch']=='no_gain' else 'skipped_sampled'
        selected['decision_id']=ref
        selected['state']='pending_decision' if any(r['decision_state']=='pending' for r in selected['queries']) else 'decided'
        selected['selection_allows_reading']=any(r['decision_state']=='selected' for r in selected['queries'])
        selected['basis']='query_decisions_persisted'
    db.execute('UPDATE decisions SET body=? WHERE id=?',(json.dumps(selected,ensure_ascii=False),ref))
    db.commit()
    db.execute('BEGIN IMMEDIATE')
    selected=json.loads(db.execute('SELECT body FROM decisions WHERE id=?',(ref,)).fetchone()[0])
    # Preserve one ledger; admission selects the phase of the referenced query.
    ledger.decide(selected['state'],any(q['decision_state']=='selected' for q in selected['queries']),
                  finish_probe=selected['state']!='pending_decision')
    if call[0]=='finish_reading_task':
        db.commit()
        if not (folder/'completion.json').exists():
            trace.control('finish_reading_task',args)
        db.execute('BEGIN IMMEDIATE')
        selected=json.loads(db.execute('SELECT body FROM decisions WHERE id=?',(ref,)).fetchone()[0])
        selected['state']='closed'
        completion=json.loads((folder/'completion.json').read_text(encoding='utf-8'))
        exhausted=completion.get('exhausted_dimensions',[]) if completion['stop_reason']=='budget_exhausted' else []
        for row in selected['queries']:
            if row['execution_state']=='not_started' and row['decision_state'] in ('selected','pending'):
                if exhausted and row['decision_state']=='selected':
                    row.update(execution_state='budget_blocked',execution_reason='budget_exhausted: '+', '.join(exhausted))
                else:row['execution_state']='cancelled'
        ledger.decide('closed',False)
        db.execute('UPDATE decisions SET body=? WHERE id=?',(json.dumps(selected,ensure_ascii=False),ref))
        db.commit();db.execute('BEGIN IMMEDIATE')
    remaining=completion['budget_remaining'] if call[0]=='finish_reading_task' else ledger.remaining()
    result=query_result(selected,remaining,app=app,ledger=ledger);result['reused']=saved.get('reused',False)
    if call[0]=='finish_reading_task':
        result.update({key:completion[key] for key in ('stop_reason','reason','conclusion')})
        result['exhausted_dimensions']=completion.get('exhausted_dimensions',[])
    from research_trace import write_record
    # Only public state goes into reports returned by finish; probability remains in Application audit.
    write_record(folder/'decision.json',{key:deepcopy(result[key]) for key in
        ('protocol_version','task_id','decision_id','state','queries','selection_allows_reading','runtime_state')})
    write_record(folder/'protocol.json',{'protocol_version':QUERY_DECISION_VERSION,'execution_prompt':result['execution_prompt']})
    context=json.loads((folder/'context.json').read_text(encoding='utf-8'))
    context['task_context']['query_plan']=deepcopy(selected['task_arguments']['query_plan'])
    write_record(folder/'context.json',context)
    trace.report(folder)
    return result


def intercept_begin(app, db, call, selected, trace):
    if trace is None:raise ValueError('reading_entry_not_configured')
    saved=json.loads(call[2]);args=saved['upstream'];meta=saved['declaration'];ref=selected['task_id']
    config=effective_limits(app.context['policy'].get('decision_probe'),trace.config,selected['started_at'])
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


def query_execution_view(state, remaining, parameters, access=None):
    """Project supplied v2 host state; never create identities or grant access."""
    budget_keys=('total_calls','total_seconds','read_seconds','probe_calls','probe_seconds','probe_characters')
    budget={k:v for k,v in remaining.items() if k in budget_keys and type(v) in (int,float)}
    if isinstance(remaining.get('turn_disclosure'),dict):
        budget['turn_disclosure']=deepcopy(remaining['turn_disclosure'])
    if type(remaining.get('probe_started')) is bool:
        budget['probe_started']=remaining['probe_started']
    fields=('query_id','query_index','purpose','decision_state','execution_state',
            'can_read','read_ids','next_actions')
    rows=[{k:deepcopy(row[k]) for k in fields if k in row}
          for row in parameters.get('query_results',[])]
    return {'state':state,'goal':parameters['goal'],'query_plan':deepcopy(parameters.get('query_plan')),
            'queries':rows,'budget_remaining':budget,
            'next_actions':deepcopy((access or {}).get('next_actions',[]))}


def execution_prompt(state, remaining, parameters, access=None, *, protocol_version=VERSION):
    if protocol_version == QUERY_DECISION_VERSION:
        view=query_execution_view(state,remaining,parameters,access)
        return (guidance(protocol_version)+'\n当前任务状态：'+str(state)+
            '\n原始目标：'+view['goal']+
            '\n本次需求与初始查询：'+json.dumps(view['query_plan'],ensure_ascii=False,separators=(',',':'))+
            '\n逐查询状态：'+json.dumps(view['queries'],ensure_ascii=False,separators=(',',':'))+
            '\n当前可执行动作：'+json.dumps(view['next_actions'],ensure_ascii=False,separators=(',',':'))+
            '\n剩余预算：'+json.dumps(view['budget_remaining'],ensure_ascii=False,separators=(',',':'))+
            '\n追加读取前检查该查询许可、total_calls、read_seconds 和 turn_disclosure.remaining（本轮文本估算额度）。'
            '任一读取预算用尽时停止补读，完成裁决后用 budget_exhausted 记录收尾。')
    if protocol_version != VERSION:
        raise ValueError('unknown_knowledge_decision_protocol')
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
            if task and decision.get('decision_protocol')==QUERY_DECISION_VERSION:
                if decision.get('state')!='closed' and (self.trace.root/task/'context.json').exists():
                    folder=self.trace.folder(task)
                    if (folder/'completion.json').exists():continue
                    names.add('finish_reading_task')
                    ledger=self.trace.task_budget(folder)
                    for tool in reads:
                        if any(query_read_access(self.app,ledger,decision,row,tool)['can_read'] for row in decision['queries']):names.add(tool)
                continue
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
