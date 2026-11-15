"""Render the two knowledge pages supplied on chat startup."""
from local_knowledge import Knowledge
from knowledge_tools import RetrievalBinding, guidance


def render_catalog(root, account, group, learning_root=None, budget=800, entry_store=None, application_policy=None, semantic=False):
    """Bounded entry points and brief mapping; body retrieval stays on demand."""
    from knowledge_catalog import KnowledgeCatalog
    if entry_store:
        from knowledge_entries import EntryStore
        index = EntryStore.for_reader(entry_store, account, group).index()
        prefix = ('## 知识入口\n'+guidance('tags',application_policy,semantic)+'\n可读条目：'+str(index['entries'])
                  +'；Tag 数：'+str(index['tags'])+'；未标注条目：'+str(index['untagged_entries'])+'\n')
    else:
        catalog = KnowledgeCatalog(root, account, group, learning_root)
        index = catalog.index()
        domains = sorted({key.split(':')[0] for key in index['categories']})
        prefix = ('## 知识入口\n'+guidance('legacy',application_policy)+'\n领域：'+', '.join(domains)
                  +'\n已发布学习：'+index['sources']['published_learning']+'\n')
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


def render_servers(servers, binding=None, application_policy=None):
    """Render only the enabled catalog's host-bound index."""
    bound = RetrievalBinding.select(servers, ambiguity='ambiguous_startup_knowledge_provider')
    return render_binding(bound, binding, application_policy)


def render_binding(bound, binding=None, application_policy=None):
    if bound is None:
        return ''
    env = bound.server.get('env', {})
    account, group = env.get('QQ_KNOWLEDGE_ACCOUNT', ''), env.get('QQ_KNOWLEDGE_GROUP', '')
    if binding and (account != binding['account_id'] or group != binding['group_id']):
        raise ValueError('startup_knowledge_scope_mismatch')
    return render_catalog(env['QQ_KNOWLEDGE_ROOT'], account, group,
        env.get('QQ_KNOWLEDGE_LEARNING_ROOT'), int(env.get('QQ_KNOWLEDGE_STARTUP_BUDGET', '800')),
        env.get('QQ_KNOWLEDGE_ENTRY_STORE'), application_policy, bound.semantic)
