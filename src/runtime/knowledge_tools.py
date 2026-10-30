"""Shared knowledge-tool identity and guidance for chat and research."""
LEGACY_TOOLS = ['get_knowledge_index', 'search_knowledge', 'read_knowledge']
TAG_TOOLS = ['get_knowledge_tag_index', 'search_knowledge_tags',
             'find_knowledge_entries', 'read_knowledge_entry']
ALL_TOOLS = set(LEGACY_TOOLS + TAG_TOOLS)


def provider_mode(server):
    tools = set(server.get('tools', []))
    legacy = set(LEGACY_TOOLS).issubset(tools)
    tags = set(TAG_TOOLS).issubset(tools)
    if legacy and tags:
        raise ValueError('mixed_knowledge_protocol')
    return 'tags' if tags else 'legacy' if legacy else None


def servers_mode(servers):
    modes = [provider_mode(s) for s in servers.values() if provider_mode(s)]
    if len(modes) > 1:
        raise ValueError('ambiguous_knowledge_provider')
    return modes[0] if modes else 'none'


def guidance(mode, application_policy=None):
    from knowledge_application import policy
    selected=policy(application_policy)
    gain=selected['enabled'] and selected['strategy']=='gain'
    entry=('新读取先由 begin_reading_task 创建任务，按返回的执行方向行动；已有任务沿用 task_id。'
           '任务内资料读取填写 _reading，' if gain else '')
    if mode == 'tags':
        trigger=entry+'先用 ' if gain else '表达需求或信息缺口出现时，先用 '
        ending=('本地补读后仍有具体收益的方向可继续联网；已读且适用的内容直接复用。' if gain else
                '本地材料缺失或时效不足时再联网；已读且适用的内容直接复用。')
        return (trigger+'search_knowledge_tags 查相关领域、主题、对象或需求标签；'
                '再将实际返回的 Tag ID 传给 find_knowledge_entries，all_tags 取交集，any_tags 表示备选。'
                '先看少量候选，再用 read_knowledge_entry 按 id、revision 展开正文，续读使用 next_offset。'
                'Tag 未命中时放宽组合，或用空标签列表和 query 补查标题／正文。'
                '不要猜 Tag ID，也不需要展开整份标签表。适用条件和时间依据从正文读取，修订变化时重新查询。'
                +ending)
    if mode == 'legacy':
        return (entry+'表达语境使用 search_knowledge 的 expression 分类，事实缺口使用 reference，群成员资料使用 profile；'
                '先取候选，再用 read_knowledge 展开片段，续读使用 next 句柄，版本变化重新检索。'
                +('本地补读后仍有具体收益的方向可继续联网。' if gain else '本地内容缺失或时效不足时再联网。'))
    return entry+'按已开放的只读工具获取资料；当前未配置本地知识入口。'
