"""Build a revised tool snapshot without writing or activating it."""
from copy import deepcopy


CATALOG_TOOLS = ['get_knowledge_index', 'search_knowledge', 'read_knowledge']


def migrate_snapshot(snapshot, *, learning_root):
    """Host supplies the learning root; preserve session bindings and non-read tools."""
    result = deepcopy(snapshot)
    providers = [server for server in result['servers'].values()
                 if {'search_local_knowledge', 'read_local_knowledge'}.issubset(server.get('tools', []))
                 or {'search_knowledge', 'read_knowledge'}.issubset(server.get('tools', []))]
    if len(providers) != 1:
        raise ValueError('knowledge_provider_must_be_unique')
    provider = providers[0]
    if set(provider['tools']) - set(CATALOG_TOOLS) - {'search_local_knowledge', 'read_local_knowledge'}:
        raise ValueError('mixed_knowledge_provider_requires_split')
    env = provider.get('env', {})
    if not all(env.get(key) for key in ('QQ_KNOWLEDGE_ROOT', 'QQ_KNOWLEDGE_ACCOUNT', 'QQ_KNOWLEDGE_GROUP')):
        raise ValueError('knowledge_binding_required')
    if not learning_root:
        raise ValueError('learning_root_required')
    args = provider.get('args', [])
    entrypoints = [i for i, arg in enumerate(args)
                   if arg.replace('\\', '/').split('/')[-1] in ('local_knowledge.py', 'knowledge_catalog_mcp.py')]
    if len(entrypoints) != 1:
        raise ValueError('knowledge_entrypoint_not_recognized')
    index = entrypoints[0]
    args[index] = args[index].replace('local_knowledge.py', 'knowledge_catalog_mcp.py')
    provider['tools'] = list(CATALOG_TOOLS)
    env['QQ_KNOWLEDGE_LEARNING_ROOT'] = str(learning_root)
    for server in result['servers'].values():
        server['tools'] = [tool for tool in server.get('tools', []) if tool != 'read_group_learning']
    return result


def migrate_profile(control_plane, profile_ref, *, learning_root):
    """Publish a version through the existing registry without rebinding any Bot."""
    if profile_ref.get('kind') != 'tool_profile':
        raise ValueError('tool_profile_reference_required')
    source = control_plane.dereference(profile_ref)
    body = migrate_snapshot(source['body'], learning_root=learning_root)
    return control_plane.put('tool_profile', source['id'], body,
                             expected_version=source['version'])
