"""Per-query routing. A material purpose is independent of targeted/explore."""
import re
from copy import deepcopy
from pathlib import Path

PURPOSES = ('information', 'expression')
QUERY_TEXT_MAX = 40


def generation_contract(prompt=None):
    """Query authors and replay use the same limits as MCP; no repair call is hidden."""
    fields = {key: {'type': 'string'} for key in ('information', 'expression', 'keywords', 'need')}
    for key in ('information', 'expression'):
        fields[key]['maxLength'] = QUERY_TEXT_MAX
    schema = dict(type='object', properties=fields, required=list(fields), additionalProperties=False)
    rules = (f'\n输出参数契约：information 与 expression 是实际检索文本，每项最多{QUERY_TEXT_MAX}个字符（含空格、标点）；'
             '压缩 information 与 expression 时保留各自的实体和关系线索；keywords 仍填写表达关系关键词，need 填写完整承接需求。'
             '没有该类需求则留空。expression、keywords、need 三项同时为空，或三项均有内容。'
             '直接生成满足上限的查询，不依赖后续压缩调用。')
    if prompt is None:
        prompt = (Path(__file__).resolve().parents[2]/'prompts/knowledge-query.md').read_text(encoding='utf-8-sig')
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


def query_guidance():
    # The shared authoring asset also generates replay prompts. Only its output
    # envelope changes for the tool plan; decision/sampling policy stays separate.
    prompt = generation_contract()['prompt'].split('【输出：只填查询】')[0]
    return (prompt+'首次进入任务时提交 query_plan。information_need 和 expression_need 说明回复的改善方向；'
            'queries 为0至4条独立查询。information 的 text 为主题词；expression 的 text 为原话场景线索'
            '（对应生成时 expression 填原话中的场景线索），同时填写 keywords 表达关系关键词、need 完整承接需求。'
            'text 最多40字。没有新增查阅方向时允许空数组；重试沿用返回的初案，改写保存在实际工具入参中。'
            '工具列表含 retrieve_knowledge_candidates 时，text 对应其 query，表达计划的 keywords、need 分别传入同名参数；'
            '返回目录后用 read_knowledge_entry 展开。Tag 或精确字面查询仍用 search_knowledge_tags / find_knowledge_entries。')


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
