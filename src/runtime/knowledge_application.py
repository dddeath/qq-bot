"""Host-scoped knowledge application policy and action provenance."""
from copy import deepcopy
from contextlib import closing
import hashlib
import json
from knowledge_sampling import VERSION as GAIN_PROTOCOL_VERSION, sample, unit_value
from pathlib import Path
import sqlite3
import time
import uuid

PROTOCOL_VERSION = 'knowledge-application-v2'
BASELINE_PROTOCOL_VERSION = 'knowledge-application-v1'
POLICY_SCHEMA = {'type': 'object', 'properties': {
    'enabled': {'type': 'boolean'},
    'strategy': {'type': 'string', 'enum': ['baseline', 'gain']},
    'gain_inclination': {'type': 'number', 'minimum': 0, 'maximum': 1, 'default': 0.5},
    'gain_adjustment_limit': {'type': 'number', 'minimum': 0, 'maximum': 1, 'default': 0.15}},
    'additionalProperties': False}


def policy(value=None):
    value = {} if value is None else value
    if (not isinstance(value, dict) or set(value)-{'enabled', 'strategy', 'gain_inclination', 'gain_adjustment_limit'}
            or type(value.get('enabled', False)) is not bool
            or value.get('strategy', 'baseline') not in ('baseline', 'gain')):
        raise ValueError('invalid_knowledge_application_policy')
    inclination = unit_value(value.get('gain_inclination', 0.5), 'gain_inclination')
    limit = unit_value(value.get('gain_adjustment_limit', 0.15), 'gain_adjustment_limit')
    return {'enabled': value.get('enabled', False), 'strategy': value.get('strategy', 'baseline'),
            'gain_inclination': inclination, 'gain_adjustment_limit': limit}


def inclination_guidance(value=None):
    selected = policy(value)
    if not selected['enabled'] or selected['strategy'] != 'gain':
        return ''
    return ('分两步决定本次知识补齐。第一步：依据当前上下文与具体目标，检查是否有充分、具体的证据'
            '确定直接作答或确定检索。直接作答需有证据表明已有材料覆盖当前需求，并有具体依据确认补读没有增益；'
            '确定检索需有证据指出影响回答的信息缺口或具体补齐收益。'
            '仅因已有答案可写、感觉熟悉或笼统觉得多查有益，均留在中间态。'
            '在 objective、expected_gain 中简述目标和决定依据。'
            '第二步：生成 subjective_inclination（0～1）。第一步确定直接作答填0；'
            '确定检索填1，宿主确定执行检索；其余中间态填大于0、小于1的主观检索倾向，由宿主抽样。'
            '该值表示是否值得补齐，资料正确性、搜索成功率和判断置信度另行判断。'
            '将该值随首次 _knowledge 声明提交；宿主返回执行方向，后续沿用决定 ID。')


def protocol(value=None):
    selected = policy(value)
    if not selected['enabled']:
        return ''
    trigger = ('表达需求或有影响答案的信息缺口时按需检索，已有材料足够时直接生成回应。'
               if selected['strategy'] == 'baseline' else
               '先判断当前交流需要；即使已有答案，若补读某个条件、数值、社区语义或比较依据能产生具体收益，'
               '可用 answer_improvement 记录本次增益读取，按实际范围与耗时选择执行方式。'
               '已有材料足以计算或综合时完成推导；没有具体补读收益时直接回应。')
    preference = inclination_guidance(selected)
    if preference:
        trigger += '\n'+preference
    if selected['strategy'] == 'gain':
        return ('## 知识应用 '+PROTOCOL_VERSION+'\n'+trigger+'\n'
                '在 begin_reading_task 或 plan_chat_reply 中提交 _knowledge，包含 action、trigger、'
                'target_event_ids、objective、expected_gain 和 subjective_inclination。'
                '准备直接作答时同样提交判断。begin_reading_task 的 action 为 research，回复规划为 reply。'
                'next_action=direct_reply 时使用已有信息作答；next_action=begin_reading_task 时用返回的 decision_ids 创建任务；'
                'next_action=read 时按执行协议读取。任务内各工具用 _reading 关联 task_id，完成后再规划最终回复；'
                '若需先告知正在检索，可在回复规划声明 _knowledge.phase=acknowledgement，最终回复使用 phase=final（默认）。'
                '自行或后台执行沿用同一任务、决定与剩余预算。相同原消息集合共用首次裁决，改写目标不重新采样。'
                '重试沿用 decision_ids；新消息单独判断。跨轮沿用研究决定时，回复仍指向原研究消息；直接回复决定仅用于原轮次。'
                '回复规划用 decision_ids 和 used_read_ids 标记采用的材料：复制成功读取回执中 '
                'knowledge_application.read_id 的字符串；任务内数字 read_id 用于该任务的读取定位。'
                + envelope_schema()['properties']['trigger']['description'] +
                'target_event_ids 使用字符串数组，例如 ["1364"]。'
                '沿用决定时 _knowledge 仅填 decision_ids，可加 used_read_ids、phase 和回复专用 completion，省略首次判断字段。'
                '阅读任务用 finish_reading_task 记录停止原因与结论；回复规划的 completion 可省略，'
                '填写时使用对象，例如 {"stop_reason":"sufficient","reason":"已核对需要的材料"}。')
    return ('## 知识应用 ' + BASELINE_PROTOCOL_VERSION + '\n' + trigger + '\n'
            '本节定义本次知识读取的触发策略；读取范围和工具预算沿用当前固定配置。'
            '在首次知识读取、begin_reading_task 或 plan_chat_reply 中用 _knowledge 记录动作、'
            'target_event_ids、objective 和简短 expected_gain；后续读取沿用返回的 decision_ids。'
            '回复规划用 decision_ids 和 used_read_ids 标记实际采用的已交付材料；'
            '可选 completion 填对象 {"stop_reason":"sufficient","reason":"已核对需要的材料"}。'
            'scope、配置版本和预算由宿主提供。focus_ref 当前为 null；跨轮状态尚未启用。')


def envelope_schema():
    return {'type': 'object', 'properties': {
        'action': {'type': 'string', 'enum': ['reply', 'local_read', 'research']},
        'trigger': {'type': 'string', 'enum': ['none', 'expression', 'information_gap', 'answer_improvement', 'discussion_deepening'],
            'description': '固定类别：none 无补读需求；expression 表达或社区语义；information_gap 回答所需信息缺口；answer_improvement 已能回答但补读可改善；discussion_deepening 延续当前话题深挖。具体判断依据写 objective、expected_gain。'},
        'target_event_ids': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1,
            'description': '当前已交付消息的事件 ID 字符串数组，例如 ["1364"]。'},
        'objective': {'type': 'string'}, 'expected_gain': {'type': 'string'},
        'focus_ref': {'type': 'null'},
        'subjective_inclination': {'type':'number','minimum':0,'maximum':1},
        'phase': {'type':'string','enum':['acknowledgement','final']},
        'completion': {'type':'object',
            'description': '仅 plan_chat_reply 可选填写的回复收尾说明。阅读任务先用 finish_reading_task 记录停止原因；这里可省略，若填写须为对象，例如 {"stop_reason":"sufficient","reason":"已核对所需材料"}。',
            'properties':{
            'stop_reason':{'type':'string','enum':['sufficient','no_expected_gain','budget_exhausted','no_readable_material']},
            'reason':{'type':'string','minLength':1}},'required':['stop_reason','reason'],'additionalProperties':False},
        'decision_ids': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1,
            'description': '沿用宿主返回的决定 ID；本次 _knowledge 仅保留 decision_ids，可加 used_read_ids、phase、completion，省略 action、trigger、target_event_ids、objective、expected_gain、focus_ref 和 subjective_inclination。'},
        'used_read_ids': {'type': 'array', 'items': {'type': 'string'},
            'description': '复制实际采用材料的 knowledge_application.read_id 字符串；任务内数字 read_id 仅用于任务定位。'}},
        'additionalProperties': False,
        'oneOf': [{'required': ['action', 'trigger', 'target_event_ids', 'objective'],
                   'not': {'required': ['decision_ids']}},
                  {'required': ['decision_ids'], 'not': {'anyOf': [
                      {'required': [field]} for field in ('action','trigger','target_event_ids','objective',
                                                        'expected_gain','focus_ref','subjective_inclination')]}}]}


def message_ids(event):
    body = event.get('payload', event)
    messages = [*body.get('messages', []), *(body.get('input_batch') or {}).get('messages', [])]
    return {str(m.get('event_id', m.get('id'))) for m in messages if isinstance(m, dict)
            and m.get('event_id', m.get('id')) is not None}


class Application:
    """One Run's scope and decisions; material remains in existing evidence stores."""
    def __init__(self, path):
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as db:
            self.context = json.loads(db.execute('SELECT body FROM context').fetchone()[0])

    @classmethod
    def for_run(cls, directory, snapshot):
        directory=Path(directory)
        from run_records import load
        receipt_path=directory/'run-receipt.json'
        receipt=load(receipt_path) if receipt_path.exists() else {}
        if receipt.get('session_id') is not None and receipt['session_id']!=snapshot['session_id']:
            raise ValueError('application_run_session_mismatch')
        namespace=PROTOCOL_VERSION if policy(snapshot.get('knowledge_application'))['strategy']=='gain' else ''
        fingerprint=hashlib.sha256((namespace+json.dumps(snapshot,sort_keys=True,ensure_ascii=False)).encode()).hexdigest()
        return cls.create(directory/'knowledge-application'/fingerprint[:16]/'application.sqlite3',snapshot,
            run_id=receipt.get('run_id'),budget_path=directory/'knowledge-budget.sqlite3')

    @classmethod
    def create(cls, path, snapshot, *, run_id, budget_path):
        selected = policy(snapshot.get('knowledge_application'))
        if not selected['enabled']:
            raise ValueError('knowledge_application_not_enabled')
        version=PROTOCOL_VERSION if selected['strategy']=='gain' else BASELINE_PROTOCOL_VERSION
        if selected['strategy']=='baseline':
            selected.pop('gain_adjustment_limit')
        context = dict(protocol_version=version, policy=selected, run_id=run_id,
            session_id=snapshot['session_id'], bot_ref=deepcopy(snapshot['bot_ref']),
            conversation_id=str(snapshot['account_id'])+':group:'+str(snapshot['group_id']),
            budget_path=str(Path(budget_path).resolve()),
            configuration_sha256=hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest())
        if selected['strategy'] == 'gain':
            context['gain_protocol_version'] = GAIN_PROTOCOL_VERSION
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS context(body TEXT)')
            old = db.execute('SELECT body FROM context').fetchone()
            if old and json.loads(old[0]) != context:
                raise ValueError('application_configuration_conflict')
            if not old: db.execute('INSERT INTO context VALUES (?)',(json.dumps(context),))
            db.execute('CREATE TABLE IF NOT EXISTS turns(id TEXT PRIMARY KEY, event TEXT, at REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS current(slot INTEGER PRIMARY KEY, turn_id TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, turn_id TEXT, body TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY, turn_id TEXT, tool TEXT, refs TEXT, arguments TEXT, started REAL, observation TEXT)')
        return cls(path)

    def begin_turn(self, turn_id, event):
        with closing(sqlite3.connect(self.path)) as db, db:
            old = db.execute('SELECT event FROM turns WHERE id=?',(turn_id,)).fetchone()
            if old and json.loads(old[0]) != event:
                raise ValueError('application_turn_conflict')
            db.execute('INSERT OR IGNORE INTO turns VALUES (?,?,?)',(turn_id,json.dumps(event,ensure_ascii=False),time.time()))
            db.execute('INSERT OR REPLACE INTO current VALUES (1,?)',(turn_id,))

    @property
    def gated(self):
        return self.context['policy']['strategy'] == 'gain'

    def schemas(self, tools):
        from knowledge_tools import ALL_TOOLS
        names = ALL_TOOLS | {'begin_reading_task','plan_chat_reply','read_research_report'}
        result = deepcopy(tools)
        for tool in result:
            if tool['name'] in names:
                if self.gated and tool['name'] in ALL_TOOLS:
                    continue  # Task reads use _reading; judgment belongs to the two entry tools.
                envelope = envelope_schema()
                if self.gated and tool['name']=='read_research_report':
                    envelope={'type':'object','properties':{
                        'decision_ids':envelope['properties']['decision_ids']},
                        'required':['decision_ids'],'additionalProperties':False}
                    tool['inputSchema'].setdefault('properties', {})['_knowledge']=envelope
                    tool['description']+=' 用 _knowledge.decision_ids 关联原研究决定；此工具不提交首次判断。'
                    continue
                if tool['name'] != 'plan_chat_reply':
                    envelope['properties'].pop('completion')
                if self.gated:
                    envelope['properties']['action']['enum'] = ['reply' if tool['name']=='plan_chat_reply' else 'research']
                    tool['inputSchema']['required']=list(dict.fromkeys(tool['inputSchema'].get('required',[])+['_knowledge']))
                    envelope['oneOf'][0]['required'].append('subjective_inclination')
                    envelope['properties']['subjective_inclination']['description'] = inclination_guidance(self.context['policy'])
                    envelope['properties']['expected_gain']['description'] = '简述第一步的具体证据与决定依据；中间态说明可能的补齐收益。'
                tool['inputSchema'].setdefault('properties', {})['_knowledge'] = envelope
                tool['description'] = tool.get('description', '') + (' 首次 _knowledge 提交 subjective_inclination 与固定枚举 trigger，判断依据写 objective、expected_gain。后续 _knowledge 使用 {"decision_ids":["返回的ID"]}，省略首次判断字段；读取统一由 begin_reading_task 创建任务后填写 _reading。' if self.gated else ' 用可选 _knowledge 记录知识应用决定；后续沿用 decision_ids，回复规划标记 used_read_ids。')
                if tool['name'] in ('begin_reading_task','plan_chat_reply'):
                    tool['description'] += ' trigger '+envelope['properties']['trigger']['description']
                    tool['description'] += ' target_event_ids '+envelope['properties']['target_event_ids']['description']
                if tool['name'] == 'plan_chat_reply':
                    tool['description'] += ' completion '+envelope['properties']['completion']['description']
        return result

    def verify_snapshot(self, snapshot):
        fingerprint=hashlib.sha256(json.dumps(snapshot,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if fingerprint != self.context['configuration_sha256']:
            raise ValueError('application_snapshot_mismatch')

    def _validate_decision_scope(self, db, refs, turn, tool, arguments):
        decisions=[(row[0],json.loads(row[1])) for ref in refs
                   for row in db.execute('SELECT turn_id,body FROM decisions WHERE id=?',(ref,))]
        prior=[body for origin,body in decisions if origin!=turn]
        if any(body['action']!='research' for body in prior):
            raise ValueError('knowledge_decision_turn_mismatch: new messages require their own decision')
        if tool=='plan_chat_reply':
            targets=set()
            if arguments.get('target_event_id') is not None:
                targets.add(str(arguments['target_event_id']))
            if isinstance(arguments.get('target_event_ids'),list):
                targets.update(str(value) for value in arguments['target_event_ids'])
            allowed=set().union(*(set(body['target_event_ids']) for _,body in decisions))
            if prior and not targets:
                raise ValueError('knowledge_reply_targets_required: identify the original research messages')
            if targets-allowed:
                raise ValueError('knowledge_reply_target_mismatch: reply to the decision messages')

    def prepare(self, tool, arguments):
        from knowledge_tools import ALL_TOOLS
        args = deepcopy(arguments)
        meta = args.pop('_knowledge', None)
        if self.gated and tool in ALL_TOOLS and meta is not None:
            raise ValueError('knowledge_metadata_not_supported: use _reading for task reads')
        if self.gated and tool=='read_research_report' and meta is not None and (not isinstance(meta,dict) or set(meta)!={'decision_ids'}):
            raise ValueError('knowledge_entry_required: use original decision_ids for the report')
        if self.gated and tool in ALL_TOOLS and '_reading' not in args:
            raise ValueError('knowledge_entry_required: begin_reading_task')
        applicable = tool in ALL_TOOLS | {'begin_reading_task','plan_chat_reply','send_chat_reply','read_research_report','finish_reading_task','declare_native_read'} or '_reading' in args
        if not applicable:
            if meta is not None: raise ValueError('knowledge_metadata_not_supported')
            return None, args
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT turn_id FROM current WHERE slot=1').fetchone()
            if not row: raise ValueError('application_turn_missing')
            turn = row[0]
            refs = []
            task_id=(args.get('_reading') or {}).get('task_id') or (args.get('task_id') if tool in ('finish_reading_task','declare_native_read') else None)
            task_refs=[]
            if task_id:
                for found in db.execute("SELECT refs,observation FROM calls WHERE tool='begin_reading_task' AND observation IS NOT NULL"):
                    if json.loads(found[1]).get('task_id')==task_id:
                        task_refs=json.loads(found[0]);break
                if not task_refs and self.gated:
                    for row in db.execute('SELECT id,body FROM decisions'):
                        if json.loads(row[1]).get('task_id')==task_id:
                            task_refs=[row[0]];break
            if meta is not None:
                if not isinstance(meta, dict) or set(meta)-set(envelope_schema()['properties']):
                    raise ValueError('invalid_knowledge_decision')
                if meta.get('focus_ref') is not None:
                    raise ValueError('knowledge_focus_not_enabled')
                if 'decision_ids' in meta:
                    if set(meta)-{'decision_ids','used_read_ids','completion','phase'}:
                        raise ValueError('mixed_knowledge_decision')
                    refs = meta['decision_ids']
                    if not isinstance(refs,list) or not refs or any(not isinstance(r,str) for r in refs):
                        raise ValueError('invalid_decision_references')
                    for ref in refs:
                        found = db.execute('SELECT turn_id,body FROM decisions WHERE id=?',(ref,)).fetchone()
                        if not found: raise ValueError('unknown_knowledge_decision')
                        if not self.gated and found[0] != turn and not (tool in ('plan_chat_reply','read_research_report') and json.loads(found[1])['action']=='research'):
                            raise ValueError('knowledge_decision_turn_mismatch')
                        expected = 'research' if tool in ('begin_reading_task','read_research_report') or '_reading' in args else 'local_read'
                        if tool!='plan_chat_reply' and not (self.gated and tool=='begin_reading_task') and json.loads(found[1])['action']!=expected:
                            raise ValueError('knowledge_action_tool_mismatch')
                else:
                    if meta.get('action') not in ('reply','local_read','research'):
                        raise ValueError('invalid_knowledge_decision')
                    if meta.get('trigger') not in envelope_schema()['properties']['trigger']['enum']:
                        raise ValueError('invalid_knowledge_trigger: '+envelope_schema()['properties']['trigger']['description'])
                    if not isinstance(meta.get('objective'),str) or not meta['objective'].strip():
                        raise ValueError('knowledge_objective_required')
                    if meta['trigger']=='answer_improvement' and (not isinstance(meta.get('expected_gain'),str) or not meta['expected_gain'].strip()):
                        raise ValueError('knowledge_expected_gain_required')
                    targets = meta.get('target_event_ids')
                    events=db.execute('SELECT event FROM turns WHERE id=?',(turn,)) if self.gated else db.execute('SELECT event FROM turns')
                    known = set().union(*(message_ids(json.loads(r[0])) for r in events))
                    if not isinstance(targets,list) or not targets or any(not isinstance(t,str) for t in targets):
                        raise ValueError('invalid_knowledge_target_ids: expected nonempty string array, e.g. ["1364"]')
                    if any(t not in known for t in targets):
                        raise ValueError('knowledge_target_not_delivered')
                    expected = 'reply' if tool=='plan_chat_reply' else 'research' if tool in ('begin_reading_task','read_research_report') else 'local_read'
                    if meta['action'] != expected: raise ValueError('knowledge_action_tool_mismatch')
                    if self.gated:
                        if tool not in ('begin_reading_task','plan_chat_reply'):
                            raise ValueError('knowledge_entry_required: begin_reading_task')
                        subjective=unit_value(meta.get('subjective_inclination'),'subjective_inclination')
                        identity=json.dumps([self.context['session_id'],self.context['run_id'],self.context['configuration_sha256'],sorted(set(targets))],ensure_ascii=False)
                        ref=hashlib.sha256(identity.encode()).hexdigest()[:32]
                        prior=db.execute('SELECT body FROM decisions WHERE id=?',(ref,)).fetchone()
                        if prior is None:
                            # Existing v2 records included objective in their ID. Keep the first draw and its task.
                            for old_ref, old_body in db.execute('SELECT id,body FROM decisions ORDER BY rowid'):
                                if set(json.loads(old_body).get('target_event_ids',[]))==set(targets):
                                    ref,prior=old_ref,(old_body,)
                                    break
                        if prior:
                            body=json.loads(prior[0])
                            if body['gate']['subjective_inclination']!=subjective:
                                raise ValueError('knowledge_decision_already_sampled: reuse decision_ids '+json.dumps([ref]))
                        else:
                            gate=sample(subjective,self.context['policy'])
                            body={**meta,'proposed_action':meta['action'],
                                  'action':'research' if gate['retrieve'] else 'reply',
                                  'gate':gate,'decision_id':ref,'turn_id':turn,'basis':'model_declared_host_sampled'}
                            db.execute('INSERT INTO decisions VALUES (?,?,?)',(ref,turn,json.dumps(body,ensure_ascii=False)))
                    else:
                        ref = uuid.uuid4().hex
                        body = {**meta,'decision_id':ref,'turn_id':turn,'basis':'model_declared_before_call'}
                        db.execute('INSERT INTO decisions VALUES (?,?,?)',(ref,turn,json.dumps(body,ensure_ascii=False)))
                    refs = [ref]
                used = meta.get('used_read_ids',[])
                completion=meta.get('completion')
                if completion is not None:
                    if (tool!='plan_chat_reply' or not isinstance(completion,dict)
                            or set(completion)!={'stop_reason','reason'}
                            or completion['stop_reason'] not in envelope_schema()['properties']['completion']['properties']['stop_reason']['enum']
                            or not isinstance(completion['reason'],str) or not completion['reason'].strip()):
                        raise ValueError('invalid_application_completion')
                if not isinstance(used,list) or any(not isinstance(x,str) for x in used):
                    raise ValueError('invalid_used_reads')
                if used and tool!='plan_chat_reply': raise ValueError('used_reads_require_reply_plan')
                for read in used:
                    found=db.execute('SELECT refs,observation,tool,arguments FROM calls WHERE id=?',(read,)).fetchone()
                    if not found or not found[1] or not set(json.loads(found[0])).intersection(refs):
                        raise ValueError('unknown_used_read')
                    if json.loads(found[1]).get('status')!='ok': raise ValueError('used_read_not_delivered')
                    if found[2] not in ALL_TOOLS | {'read_research_report'} and '_reading' not in json.loads(found[3])['upstream']:
                        raise ValueError('used_reference_is_not_a_read')
            if task_refs:
                if refs and refs!=task_refs:raise ValueError('knowledge_task_decision_mismatch')
                refs=task_refs
            if self.gated:
                if refs:self._validate_decision_scope(db,refs,turn,tool,args)
                if tool in ('begin_reading_task','plan_chat_reply') and not refs:
                    raise ValueError('subjective_inclination_required')
                if task_id and not task_refs:
                    raise ValueError('knowledge_task_not_linked')
                phase=(meta or {}).get('phase','final')
                if phase not in ('acknowledgement','final') or (phase!='final' and tool!='plan_chat_reply'):
                    raise ValueError('invalid_reply_phase')
            if tool=='begin_reading_task' and refs:
                args['context']={**args.get('context',{}),'knowledge_application':{
                    'protocol_version':self.context['protocol_version'],'decision_ids':refs,
                    'session_id':self.context['session_id'],'run_id':self.context['run_id']}}
            token = uuid.uuid4().hex
            db.execute('INSERT INTO calls VALUES (?,?,?,?,?,?,NULL)',
                (token,turn,tool,json.dumps(refs),json.dumps({'upstream':args,'declaration':meta},ensure_ascii=False),time.time()))
        return token, args

    def intercept(self, token, arguments, trace=None):
        """Return a host decision instead of calling upstream when a read/plan must wait."""
        if not self.gated or token is None:
            return None
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            call=db.execute('SELECT tool,refs,arguments FROM calls WHERE id=?',(token,)).fetchone()
            refs=json.loads(call[1])
            if not refs or call[0] not in ('begin_reading_task','plan_chat_reply'):
                return None
            decisions=[json.loads(db.execute('SELECT body FROM decisions WHERE id=?',(ref,)).fetchone()[0]) for ref in refs]
            reading=[d for d in decisions if d.get('gate',{}).get('retrieve')]
            if call[0]=='begin_reading_task':
                if len(decisions)!=1:
                    raise ValueError('reading_requires_one_decision')
                if not reading:
                    return {'next_action':'direct_reply','decision_ids':refs}
                if trace is None:
                    raise ValueError('reading_entry_not_configured')
                trace.validate_application_budget(arguments.get('budget'))
                try:
                    trace.validate_begin(**arguments)
                except TypeError as exc:
                    raise ValueError('invalid_reading_parameters') from exc
                selected=decisions[0]
                report_path=str((trace.root/selected['decision_id']/'report.json').resolve())
                if selected.get('task_report') and selected['task_report']!=report_path:
                    raise ValueError('reading_task_binding_changed')
                fingerprint=hashlib.sha256(json.dumps(arguments,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                if selected.get('task_request') and selected['task_request']!=fingerprint:
                    raise ValueError('reading_request_changed: retain original task arguments')
                selected['task_id']=selected['decision_id'];selected['task_request']=fingerprint
                selected['task_report']=report_path
                # Commit the task reservation before file I/O so a restart retains its parameters.
                db.execute('UPDATE decisions SET body=? WHERE id=?',(json.dumps(selected,ensure_ascii=False),selected['decision_id']))
                db.commit()
                db.execute('BEGIN IMMEDIATE')
                result=trace.begin_once(selected['task_id'],arguments)
                return {'next_action':'read','decision_ids':refs,**result}
            pending=[d['decision_id'] for d in reading if not d.get('task_id')]
            if pending:
                return {'next_action':'begin_reading_task','decision_ids':pending}
            if (json.loads(call[2]).get('declaration') or {}).get('phase')=='acknowledgement':
                return None
            unfinished=[]
            for decision in reading:
                try:
                    finished=json.loads(Path(decision['task_report']).with_name('completion.json').read_text(encoding='utf-8'))
                except (KeyError,OSError,ValueError):
                    finished=None
                if finished is None:unfinished.append(decision['task_id'])
            if unfinished:
                return {'next_action':'continue_reading','task_ids':unfinished,'decision_ids':refs}
            return None

    def complete(self, token, response, elapsed, evidence_ref=None):
        if token is None: return response
        from research_feedback import body_of
        result = deepcopy(response)
        body = body_of(result)
        if not isinstance(result.get('result',{}).get('structuredContent'),dict):
            for block in result.get('result',{}).get('content',[]):
                if block.get('type')!='text':continue
                try: candidate=json.loads(block['text'])
                except ValueError:continue
                if isinstance(candidate,dict) and not set(candidate)<= {'read_id','budget_remaining','knowledge_turn_budget','knowledge_application'}:
                    body=candidate;break
        failed = bool(result.get('error') or result.get('result',{}).get('isError') or body.get('error'))
        budget = body.get('knowledge_turn_budget')
        for block in result.get('result',{}).get('content',[]):
            if block.get('type')=='text':
                try: budget = json.loads(block['text']).get('knowledge_turn_budget',budget)
                except (ValueError,AttributeError): pass
        observation = dict(status='error' if failed else 'ok', elapsed_seconds=elapsed,
            finished_at=time.time(), budget=budget)
        if failed:
            observation['error']=deepcopy(result.get('error') or body.get('error') or
                [block.get('text','') for block in result.get('result',{}).get('content',[]) if block.get('type')=='text'])
        if evidence_ref is not None: observation['evidence_ref']=deepcopy(evidence_ref)
        for key in ('task_id','stop_reason','plan_id','bubbles','research_association','recorded','next_action'):
            if key in body: observation[key]=deepcopy(body[key])
        with closing(sqlite3.connect(self.path)) as db, db:
            row=db.execute('SELECT turn_id,refs,observation,tool,arguments FROM calls WHERE id=?',(token,)).fetchone()
            if not row: raise ValueError('unknown_application_call')
            if row[2] is not None: raise ValueError('application_call_already_completed')
            from knowledge_tools import ALL_TOOLS
            if not failed and (row[3] in ALL_TOOLS | {'read_research_report'}
                               or '_reading' in json.loads(row[4])['upstream']):
                observation['read_id']=token
            db.execute('UPDATE calls SET observation=? WHERE id=?',(json.dumps(observation,ensure_ascii=False),token))
        receipt=dict(protocol_version=self.context['protocol_version'],turn_id=row[0],call_id=token,
            decision_ids=json.loads(row[1]),status=observation['status'],
            decision_status='recorded' if json.loads(row[1]) else 'decision_not_recorded')
        if 'read_id' in observation:
            receipt['read_id']=observation['read_id']
        if isinstance(result.get('result'),dict):
            result['result'].setdefault('content',[]).append({'type':'text','text':json.dumps({'knowledge_application':receipt},ensure_ascii=False)})
            if isinstance(result['result'].get('structuredContent'),dict):
                result['result']['structuredContent']={**body,'knowledge_application':receipt}
        return result

    def export(self):
        from knowledge_turn_budget import TurnBudget
        budget = TurnBudget(self.context['budget_path'])
        with closing(sqlite3.connect(self.path)) as db:
            turns=[dict(turn_id=r[0],event=json.loads(r[1]),at=r[2]) for r in db.execute('SELECT * FROM turns ORDER BY rowid')]
            decisions=[json.loads(r[0]) for r in db.execute('SELECT body FROM decisions ORDER BY rowid')]
            calls=[dict(call_id=r[0],turn_id=r[1],tool=r[2],decision_ids=json.loads(r[3]),
                        request=json.loads(r[4]),started_at=r[5],observation=json.loads(r[6]) if r[6] else None)
                   for r in db.execute('SELECT * FROM calls ORDER BY rowid')]
        reads=[]
        for turn in turns:
            reads.extend(budget.records(turn['turn_id']))
        tasks={}
        for call in calls:
            reference=(call['observation'] or {}).get('evidence_ref') or {}
            if reference.get('kind')=='research_task' and reference['task_id'] not in tasks:
                try:
                    report=json.loads(Path(reference['path']).read_text(encoding='utf-8'))
                    tasks[reference['task_id']]={'reference':reference,'report':report,'status':'available'}
                except (OSError,ValueError) as exc:
                    tasks[reference['task_id']]={'reference':reference,'report':None,'status':'missing','error':str(exc)}
        return dict(schema_version=1,record_origin='knowledge_application',configuration=deepcopy(self.context),
            turns=turns,decisions=decisions,calls=calls,reads=reads,research_tasks=list(tasks.values()),
            usage={'billed_tokens':None,'model_requests':None,'missing_reason':'model_usage_not_attached'})
