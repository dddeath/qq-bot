"""Shared knowledge-tool identity and guidance for chat and research."""
from dataclasses import dataclass

LEGACY_TOOLS = ['get_knowledge_index', 'search_knowledge', 'read_knowledge']
TAG_TOOLS = ['get_knowledge_tag_index', 'search_knowledge_tags',
             'find_knowledge_entries', 'read_knowledge_entry']
SEMANTIC_TOOL = 'retrieve_knowledge_candidates'
ALL_TOOLS = set(LEGACY_TOOLS + TAG_TOOLS + [SEMANTIC_TOOL])


def provider_mode(server):
    tools = set(server.get('tools', []))
    legacy = set(LEGACY_TOOLS).issubset(tools)
    tags = set(TAG_TOOLS).issubset(tools)
    if legacy and tags:
        raise ValueError('mixed_knowledge_protocol')
    return 'tags' if tags else 'legacy' if legacy else None


@dataclass(frozen=True)
class RetrievalBinding:
    """Selected host snapshot provider; the child still resolves its backend from env."""
    name: str
    mode: str
    server: dict

    @property
    def semantic(self):
        return self.mode == 'tags' and SEMANTIC_TOOL in self.server.get('tools', ())

    @classmethod
    def select(cls, servers, *, ambiguity):
        matches = [cls(name, mode, server) for name, server in servers.items()
                   if (mode := provider_mode(server))]
        if len(matches) > 1:
            raise ValueError(ambiguity)
        return matches[0] if matches else None


def servers_mode(servers):
    bound = RetrievalBinding.select(servers, ambiguity='ambiguous_knowledge_provider')
    return bound.mode if bound else 'none'


def guidance(mode, application_policy=None, semantic=False):
    from knowledge_application import policy
    selected=policy(application_policy)
    gain=selected['enabled'] and selected['strategy']=='gain'
    entry=('新读取先由 begin_reading_task 创建任务，按返回的执行方向行动；已有任务沿用 task_id。'
           '任务内资料读取填写 _reading，' if gain else '')
    if mode == 'tags':
        from knowledge_query import GUIDE
        trigger=entry+'先用 ' if gain else '表达需求或信息缺口出现时，先用 '
        ending=('本地补读后仍有具体收益的方向可继续联网；已读且适用的内容直接复用。' if gain else
                '本地材料缺失或时效不足时再联网；已读且适用的内容直接复用。')
        if gain and 'decision_probe' in selected:
            ending='待裁决查阅限于本地 Tag、候选与正文；提交裁决后按宿主方向和剩余预算行动。已读且适用的内容直接复用。'
        if semantic:
            return (entry+'资料缺口或表达需要使用 retrieve_knowledge_candidates：purpose 指定 information 或 expression，query 为1至40字；'
                    '表达查询同时填写关系关键词 keywords 与完整表达需要 need，资料查询这两项留空。'
                    '返回至多六个父条目及段落位置，选择需要的 entry_id、revision、offset、limit 用 read_knowledge_entry 展开。'
                    '精确 Tag 或字面过滤仍使用 search_knowledge_tags / find_knowledge_entries。'
                    +GUIDE+ending)
        return (trigger+'search_knowledge_tags 查相关领域、主题、对象或需求标签；'
                '再将实际返回的 Tag ID 传给 find_knowledge_entries，all_tags 取交集，any_tags 表示备选。'
                '先看少量候选，再用 read_knowledge_entry 按 id、revision 展开正文，续读使用 next_offset。'
                'Tag 未命中时放宽组合，或用空标签列表和 query 补查标题／正文。'
                '不要猜 Tag ID，也不需要展开整份标签表。适用条件和时间依据从正文读取，修订变化时重新查询。'
                +GUIDE+ending)
    if mode == 'legacy':
        return (entry+'表达语境使用 search_knowledge 的 expression 分类，事实缺口使用 reference，群成员资料使用 profile；'
                '先取候选，再用 read_knowledge 展开片段，续读使用 next 句柄，版本变化重新检索。'
                +('本地补读后仍有具体收益的方向可继续联网。' if gain else '本地内容缺失或时效不足时再联网。'))
    return entry+'按已开放的只读工具获取资料；当前未配置本地知识入口。'
