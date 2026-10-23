"""Render the two knowledge pages supplied on chat startup."""
from local_knowledge import Knowledge


def render_catalog(root, account, group, learning_root=None, budget=800):
    """Bounded entry points and brief mapping; body retrieval stays on demand."""
    from knowledge_catalog import KnowledgeCatalog
    catalog = KnowledgeCatalog(root, account, group, learning_root)
    index = catalog.index()
    domains = sorted({key.split(':')[0] for key in index['categories']})
    prefix = ('## 知识入口\n表达需求查 expression，信息缺口查 reference，成员资料查 profile。'
              '先 search_knowledge，再按候选句柄 read_knowledge。\n领域：' + ', '.join(domains)
              + '\n已发布学习：' + index['sources']['published_learning'] + '\n')
    page = Knowledge(root, account, group).read(f'group-memory/{account}/{group}/INDEX.md')
    mapping = page.get('text', '') if page.get('found') else ''
    suffix = '\n成员映射未展开部分可通过知识工具读取。'
    def size(text): return (len(text.encode('utf-8'))+1)//2
    if type(budget) is not int or budget < 1 or size(prefix+suffix) > budget:
        raise ValueError('startup_knowledge_budget_too_small')
    lo, hi = 0, len(mapping)
    while lo < hi:
        mid = (lo+hi+1)//2
        if size(prefix+mapping[:mid]+suffix) <= budget: lo = mid
        else: hi = mid-1
    return prefix + mapping[:lo] + (suffix if lo < len(mapping) else '')

def render(root,account,group):
    kb=Knowledge(root,account,group)
    paths=['INDEX.md',f'group-memory/{account}/{group}/INDEX.md']
    sections=[]
    for path in paths:
        page=kb.read(path)
        if not page['found']:raise ValueError('missing_startup_knowledge:'+path)
        sections.append(f'## 知识入口：{path}\n\n'+page['text'])
    return '\n\n'.join(sections)


def render_servers(servers, binding=None):
    """Render only the enabled catalog's host-bound index."""
    catalogs = [server for server in servers.values()
                if {'search_knowledge', 'read_knowledge'}.issubset(server.get('tools', []))]
    if not catalogs:
        return ''
    if len(catalogs) != 1:
        raise ValueError('ambiguous_startup_knowledge_provider')
    env = catalogs[0].get('env', {})
    account, group = env.get('QQ_KNOWLEDGE_ACCOUNT', ''), env.get('QQ_KNOWLEDGE_GROUP', '')
    if binding and (account != binding['account_id'] or group != binding['group_id']):
        raise ValueError('startup_knowledge_scope_mismatch')
    return render_catalog(env['QQ_KNOWLEDGE_ROOT'], account, group,
        env.get('QQ_KNOWLEDGE_LEARNING_ROOT'), int(env.get('QQ_KNOWLEDGE_STARTUP_BUDGET', '800')))
