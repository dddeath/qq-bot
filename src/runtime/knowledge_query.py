"""Per-query routing. A material purpose is independent of targeted/explore."""
import re
import json
from copy import deepcopy
from pathlib import Path

PURPOSES = ('information', 'expression')
QUERY_TEXT_MAX = 40
LEGACY_DECISION_VERSION = 'knowledge-decision-v1'
QUERY_DECISION_VERSION = 'knowledge-decision-v2'
_QUERY_SECTION = '<!-- query-decision-v2 -->'


def _version(version):
    if version not in (None, LEGACY_DECISION_VERSION, QUERY_DECISION_VERSION):
        raise ValueError('unknown_knowledge_decision_protocol')
    return version == QUERY_DECISION_VERSION


class QueryContractError(ValueError):
    """A v2 parameter error shared by pure validators and MCP adapters."""
    def __init__(self, issues):
        self.details={'error':'invalid_decision_parameters','argument_errors':issues,
                      'executed':False,'recovery':'correct_arguments; retain task/query references'}
        super().__init__('invalid_decision_parameters: '+json.dumps(self.details,ensure_ascii=False))

    def tool_result(self):
        body=deepcopy(self.details)
        return {'isError':True,'content':[{'type':'text','text':json.dumps(body,ensure_ascii=False)}],
                'structuredContent':body}


def query_error(code,path,recovery,**details):
    return QueryContractError([{'code':code,'path':list(path),'recovery':recovery,**details}])


def validate_contract_schema(schema, value, path=()):
    from jsonschema import Draft202012Validator
    issues=[]
    for error in Draft202012Validator(schema).iter_errors(value):
        location=[*path,*error.absolute_path]
        item={'code':'schema_validation','path':location,'rule':error.validator,
              'recovery':'Correct the indicated field to match the tool schema.'}
        if error.validator=='required':
            item['missing']=[k for k in error.validator_value if not isinstance(error.instance,dict) or k not in error.instance]
            item['recovery']='Supply the missing fields at this path.'
        elif error.validator=='additionalProperties':
            item['unexpected']=sorted(set(error.instance)-set(error.schema.get('properties',{})))
            item['recovery']='Remove the unexpected fields at this path.'
        elif error.validator=='not':
            item['omit']=error.validator_value.get('required',[])
            if 'anyOf' in error.validator_value:
                item['omit_one_of']=[k for branch in error.validator_value['anyOf'] for k in branch.get('required',[])]
            item['recovery']='Omit the fields disallowed in this stage or query purpose.'
        elif error.validator=='oneOf' and location[:1]==['query_decisions'] and isinstance(error.instance,dict) and {'query_index','query_id'}<=set(error.instance):
            item.update(code='conflicting_query_reference',
                        recovery='First commit uses query_index; an existing task uses query_id. Keep only the applicable reference.')
        else:
            item['expected']=error.validator_value
        issues.append(item)
        if len(issues)>=8:break
    if issues:raise QueryContractError(issues)


def query_decision_schema(reference='either'):
    if reference not in ('index', 'id', 'either'):
        raise ValueError('invalid_query_reference_mode')
    fields = {
        'query_index': {'type':'integer','minimum':0,'maximum':3,
                        'description':'Index in the query_plan supplied by this same first commit, starting at 0.'},
        'query_id': {'type':'string','minLength':1,'pattern':r'\S',
                     'description':'Host-returned query ID in this task; reuse on retries and wording changes.'},
        'subjective_inclination': {'type':'number','minimum':0,'maximum':1,
            'description':'This query only: 0 needs evidence excluding benefit; 1 confirming benefit; otherwise an intermediate inclination.'},
        'expected_gain': {'type':'string','minLength':1,'pattern':r'\S',
            'description':'Brief basis for this query inclination, grounded in the current context or already-read material.'}}
    if reference != 'either':
        fields.pop('query_id' if reference == 'index' else 'query_index')
    row={'type':'object','properties':fields,
         'required':['subjective_inclination','expected_gain'],'additionalProperties':False}
    if reference == 'either':
        row['oneOf']=[{'required':['query_index']},{'required':['query_id']}]
    else:
        row['required'].append('query_index' if reference == 'index' else 'query_id')
    return {'type':'array','maxItems':4,'items':row}


def query_plan_schema(protocol_version=None):
    result=deepcopy(QUERY_PLAN_SCHEMA)
    if _version(protocol_version):
        item=result['properties']['queries']['items']
        for key in ('text','keywords','need'):
            item['properties'][key]['pattern']=r'\S'
        item['allOf']=[
            {'if':{'properties':{'purpose':{'const':'expression'}}},
             'then':{'required':['keywords','need']}},
            {'if':{'properties':{'purpose':{'const':'information'}}},
             'then':{'not':{'anyOf':[{'required':['keywords']},{'required':['need']}]}}}]
    return result


def validate_query_plan(plan, protocol_version=None):
    from jsonschema import Draft202012Validator
    per_query=_version(protocol_version)
    if per_query:
        validate_contract_schema(query_plan_schema(protocol_version),plan,('query_plan',))
    elif not Draft202012Validator(query_plan_schema(protocol_version)).is_valid(plan):
        raise ValueError('invalid_query_plan')
    seen=set()
    for index,q in enumerate(plan['queries']):
        text=q['text'];key=(q['purpose'],text.casefold())
        if text.strip()!=text or not plan[q['purpose']+'_need'].strip():
            if per_query:
                path=['query_plan','queries',index,'text'] if text.strip()!=text else ['query_plan',q['purpose']+'_need']
                raise query_error('query_plan_need_mismatch',path,'Trim query text and supply the need for its purpose.')
            raise ValueError('query_plan_need_mismatch')
        if 'keywords' in q or 'need' in q:
            validate_candidate_arguments(q['purpose'],text,q.get('keywords',''),q.get('need',''))
        if key in seen:
            if per_query:raise query_error('duplicate_query_plan_text',['query_plan','queries',index,'text'],'Reuse the existing query instead of duplicating its purpose and text.')
            raise ValueError('duplicate_query_plan_text')
        seen.add(key)


def validate_query_decisions(decisions, *, plan=None, reference='either', require_all=False):
    import math
    validate_contract_schema(query_decision_schema(reference),decisions,('query_decisions',))
    seen=set()
    for index,row in enumerate(decisions):
        if not math.isfinite(row['subjective_inclination']):
            raise query_error('invalid_subjective_inclination',['query_decisions',index,'subjective_inclination'],'Use a finite number between 0 and 1.')
        key=('index',row['query_index']) if 'query_index' in row else ('id',row['query_id'])
        if key in seen:
            raise query_error('duplicate_query_decision',['query_decisions',index,'query_index' if key[0]=='index' else 'query_id'],'Keep one declaration per query; reuse its first decision.')
        seen.add(key)
        if key[0]=='index' and plan is not None and key[1]>=len(plan['queries']):
            raise query_error('query_index_out_of_plan',['query_decisions',index,'query_index'],'Reference an index present in this query_plan.')
    if require_all and plan is not None:
        expected={('index',i)for i in range(len(plan['queries']))}
        if seen!=expected:
            raise query_error('query_decisions_incomplete',['query_decisions'],'Include each planned query exactly once.',
                              missing_indices=sorted(i for kind,i in expected-seen))


def generation_contract(prompt=None, *, protocol_version=None):
    """Query authors and replay use the same limits as MCP; no repair call is hidden."""
    per_query = _version(protocol_version)
    asset = ((Path(__file__).resolve().parents[2]/'prompts/knowledge-query.md').read_text(encoding='utf-8-sig')
             if prompt is None or per_query else '')
    if prompt is None:
        prompt = asset
    prompt, section, _ = prompt.partition(_QUERY_SECTION)
    if section:
        prompt = prompt.removesuffix('\n')
    if per_query:
        instructions, marker, conversation = prompt.partition('以下是对话数据。')
        instructions = instructions.split('【输出：只填查询】')[0]
        rules = asset.partition(_QUERY_SECTION)[2].strip()
        if not rules:
            raise ValueError('query_decision_prompt_missing')
        schema={'type':'object','properties':{
            'query_plan':query_plan_schema(protocol_version),
            'query_decisions':query_decision_schema('index')},
            'required':['query_plan','query_decisions'],'additionalProperties':False}
        return {'prompt':instructions.rstrip()+'\n\n'+rules+'\n\n'+marker+conversation, 'schema':schema}
    fields = {key: {'type': 'string'} for key in ('information', 'expression', 'keywords', 'need')}
    for key in ('information', 'expression'):
        fields[key]['maxLength'] = QUERY_TEXT_MAX
    schema = dict(type='object', properties=fields, required=list(fields), additionalProperties=False)
    rules = (f'\n输出参数契约：information 与 expression 是实际检索文本，每项最多{QUERY_TEXT_MAX}个字符（含空格、标点）；'
             '压缩 information 与 expression 时保留各自的实体和关系线索；keywords 仍填写表达关系关键词，need 填写完整承接需求。'
             '没有该类需求则留空。expression、keywords、need 三项同时为空，或三项均有内容。'
             '直接生成满足上限的查询，不依赖后续压缩调用。')
    instructions, marker, conversation = prompt.partition('以下是对话数据。')
    rendered = instructions.rstrip()+rules+'\n\n'+marker+conversation if marker else prompt+rules
    return {'prompt': rendered, 'schema': schema}


def generation_plan(value):
    import jsonschema
    jsonschema.validate(value, generation_contract('')['schema'])
    expression = [bool(value[k].strip()) for k in ('expression', 'keywords', 'need')]
    if any(expression) and not all(expression):
        raise ValueError('incomplete_expression_query')
    queries = [dict(purpose=p, text=value[p]) for p in PURPOSES if value[p].strip()]
    for query in queries:
        if query['purpose'] == 'expression':
            query.update(keywords=value['keywords'], need=value['need'])
    return dict(information_need=value['information'], expression_need=value['need'], queries=queries)


def generation_decision(value):
    """Validate one model output containing a full plan and its query decisions."""
    validate_contract_schema(generation_contract('',protocol_version=QUERY_DECISION_VERSION)['schema'],value)
    validate_query_plan(value['query_plan'],QUERY_DECISION_VERSION)
    validate_query_decisions(value['query_decisions'],plan=value['query_plan'],reference='index',require_all=True)
    return deepcopy(value)


QUERY_PLAN_SCHEMA = {'type':'object','properties':{
    'information_need':{'type':'string','description':'针对本次回复的信息缺口或改善方向；没有则为空。'},
    'expression_need':{'type':'string','description':'针对本次回复的措辞、接梗或承接需求；没有则为空。'},
    'queries':{'type':'array','maxItems':4,'items':{'type':'object','properties':{
        'purpose':{'type':'string','enum':list(PURPOSES)},
        'text':{'type':'string','minLength':1,'maxLength':QUERY_TEXT_MAX,
                'description':'information 为主题词；expression 为原话场景线索。最多40字。'},
        'keywords':{'type':'string','description':'表达关系关键词；表达计划填写，资料计划省略。'},
        'need':{'type':'string','description':'一句话说明表达要承接什么；表达计划填写，资料计划省略。'}},
        'required':['purpose','text'],'additionalProperties':False}}},
    'required':['information_need','expression_need','queries'],'additionalProperties':False}


def query_guidance(protocol_version=None):
    # The shared authoring asset also generates replay prompts. Only its output
    # envelope changes for the tool plan; decision/sampling policy stays separate.
    if _version(protocol_version):
        return generation_contract(protocol_version=protocol_version)['prompt'].partition('以下是对话数据。')[0].rstrip()
    prompt = generation_contract()['prompt'].split('【输出：只填查询】')[0]
    return (prompt+'首次进入任务时提交 query_plan。information_need 和 expression_need 说明回复的改善方向；'
            'queries 为0至4条独立查询。information 的 text 为主题词；expression 的 text 为原话场景线索'
            '（对应生成时 expression 填原话中的场景线索），同时填写 keywords 表达关系关键词、need 完整承接需求。'
            'text 最多40字。没有新增查阅方向时允许空数组；重试沿用返回的初案，改写保存在实际工具入参中。'
            '工具列表含 retrieve_knowledge_candidates 时，text 对应其 query，表达计划的 keywords、need 分别传入同名参数；'
            '返回目录后用 read_knowledge_entry 展开。Tag 或精确字面查询仍用 search_knowledge_tags / find_knowledge_entries。')


def routing_guidance(protocol_version=None):
    if not _version(protocol_version):
        return GUIDE
    return ('同一消息可同时提出资料和表达查询，每次候选检索按一条查询执行。'
            '读取使用 _reading.query_id 关联宿主返回的查询身份；改写、Tag检索和正文展开沿用该身份。'
            '查询的 information/expression 决定资料用途，_reading.purpose 的 targeted/explore 记录读取目的。')


def candidate_schema(schema):
    """Discovery and host validation use the same conditional parameter contract."""
    result = deepcopy(schema)
    result['additionalProperties'] = False
    properties = result.setdefault('properties', {})
    properties.update({
        'purpose': {'type':'string', 'enum':list(PURPOSES)},
        'query': {'type':'string','minLength':1,'maxLength':QUERY_TEXT_MAX,'pattern':r'\S',
                  'description':'主题词或原话场景线索，1至40字。'},
        'keywords': {'type':'string','default':'','description':'表达关系关键词；expression 必填非空，information 留空。'},
        'need': {'type':'string','default':'','description':'完整表达承接需求；expression 必填非空，information 留空。'}})
    result['required'] = list(dict.fromkeys(result.get('required', [])+['purpose','query']))
    result['allOf'] = [
        {'if':{'properties':{'purpose':{'const':'expression'}}},'then':{
            'required':['keywords','need'],'properties':{k:{'type':'string','pattern':r'\S'} for k in ('keywords','need')}}},
        {'if':{'properties':{'purpose':{'const':'information'}}},'then':{
            'properties':{k:{'const':''} for k in ('keywords','need')}}}]
    return result


def validate_candidate_arguments(purpose=None, query=None, keywords='', need='', **unexpected):
    if unexpected:
        raise ValueError('unexpected_query_arguments: remove '+', '.join(sorted(unexpected)))
    if purpose not in PURPOSES:
        raise ValueError('invalid_query_purpose')
    if not isinstance(query,str) or not query.strip() or len(query)>QUERY_TEXT_MAX:
        raise ValueError('query_length: expected 1..40 characters')
    if not isinstance(keywords,str) or not isinstance(need,str):
        raise ValueError('query_field_type: keywords and need must be strings')
    if purpose == 'information' and (keywords or need):
        raise ValueError('information_query_has_expression_fields')
    if purpose == 'expression' and not all(isinstance(v,str) and v.strip() for v in (keywords,need)):
        raise ValueError('expression_query_requires_keywords_and_need')

LOOKUPS = {'find_knowledge_entries': 'purpose', 'search_knowledge': 'usage',
           'retrieve_knowledge_candidates': 'purpose'}
ROUTED = set(LOOKUPS) | {'search_knowledge_tags', 'read_knowledge_entry', 'read_knowledge'}
GUIDE = ('同一消息可同时提出资料和表达查询。每次候选检索按一条查询执行；直接调用 find_knowledge_entries 时用 purpose 指定 information 或 expression。'
         '改写关键词、仅用 Tag 或展开正文时，用 _reading.query_index 指明原计划的查询序号（从 0 开始）。'
         '工具按该查询的用途筛候选；_reading.purpose 仍只表示 targeted/explore。')


def supports_expression(entry, documents):
    if entry['collection'] == 'formal':
        prefix = 'catalog-snapshot:formal:'
        return any('expression' in documents.get(s[len(prefix):], {}).get('usage', ())
                   for s in entry['sources'] if s.startswith(prefix))
    if not entry['collection'].startswith('learning:'):
        return False
    text = entry['content']
    kind = re.search(r'^kind:[ \t]*(\S+)[ \t]*\r?$', text, re.M)
    if kind:
        return kind[1] in ('community', 'group')
    return bool(re.search(r'^surface_form:[ \t]*\S[^\r\n]*', text, re.M))


def resolve(tool, args, reading, plan, needs=()):
    """Bind a planned read before charging or issuing it; never guess between routes."""
    if tool not in ROUTED:
        return None
    qs = (plan or {}).get('queries', [])
    idx = reading.get('query_index')
    field = LOOKUPS.get(tool)
    supplied = args.get(field) if field else None
    if not qs:
        if idx is not None:
            raise ValueError('query_index_without_plan')
        if not field:
            return None
        declared={'reference':'information','profile':'information'}.get(supplied,supplied)
        possible={p for n,p in (('reference','information'),('profile','information'),('expression','expression')) if n in needs}
        if declared and possible and declared not in possible:
            raise ValueError('query_purpose_conflict')
        if not declared and len(possible)>1:
            raise ValueError('query_purpose_required: select one knowledge purpose for this search')
        chosen=declared or next(iter(possible),None)
        if not chosen:return None
        if chosen not in PURPOSES:raise ValueError('invalid_query_purpose')
        if not supplied:
            args[field]=('profile' if list(needs)==['profile'] else 'reference') if field=='usage' and chosen=='information' else chosen
        return dict(query_index=None,purpose=chosen,text=args.get('query',''))
    if idx is None:
        options = [i for i,q in enumerate(qs) if q['text'].casefold() == args.get('query','').casefold()]
        if len(qs) == 1:
            idx = 0
        elif len(options) == 1:
            idx = options[0]
        else:
            raise ValueError('query_index_required: select _reading.query_index from the original query_plan (0-based)')
    if type(idx) is not int or not 0 <= idx < len(qs):
        raise ValueError('invalid_query_index')
    q = qs[idx]
    if field:
        value = 'reference' if field == 'usage' and q['purpose'] == 'information' else q['purpose']
        if field == 'usage' and supplied == 'profile' and value == 'reference':
            value = 'profile'
        if supplied and supplied != value:
            raise ValueError('query_purpose_conflict: use the purpose of the selected query')
        args[field] = value
    return dict(query_index=idx, purpose=q['purpose'], text=q['text'])
