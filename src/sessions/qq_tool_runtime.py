"""Render frozen tool snapshots into native harness configuration and short input."""
import json
from pathlib import Path
import sys


def validate_snapshot(snapshot):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
    from knowledge_application import policy
    selected=policy(snapshot.get('knowledge_application'))
    if selected['enabled'] and selected['strategy']=='gain':
        from learning_research import ALLOWED
        for definition in snapshot.get('servers',{}).values():
            trace=definition.get('reading_trace') or {}
            tools=definition.get('tools',[])
            if (definition.get('command') and not definition.get('url') and tools
                    and set(tools).issubset(ALLOWED) and trace.get('root') and trace.get('scope')):
                return
        raise ValueError('gain_reading_entry_required: configure a read-only stdio provider with reading_trace')


def server_configs(snapshot, path, *, python, proxy, host_wait=False):
    validate_snapshot(snapshot)
    servers = {name: {'command': python, 'args': [proxy, '--config', str(path), '--server', name]}
               for name, definition in snapshot['servers'].items() if definition['tools']}
    if (snapshot.get('qq_tools') or {}).get('capabilities'):
        if 'qq-guides' in servers:
            raise ValueError('qq-guides is reserved for operation guides')
        servers['qq-guides'] = {'command': python,
            'args': [str(Path(__file__).with_name('qq_guides_mcp.py')), '--snapshot', str(path)]}
    if host_wait:
        for name, config in servers.items():
            if name == 'qq-guides' or snapshot['servers'][name].get('url'):
                config['args'].append('--host-wait')
    return servers


def load_snapshot(path, *, conversation=None, session_id=None):
    snapshot = json.loads(Path(path).read_text(encoding='utf-8'))
    if session_id is not None and snapshot['session_id'] != session_id:
        raise ValueError('tool snapshot session mismatch')
    qq = snapshot.get('qq_tools')
    if conversation is not None and snapshot.get('account_id') is not None:
        if conversation != snapshot['account_id']+':group:'+snapshot['group_id']:
            raise ValueError('tool snapshot conversation mismatch')
    if conversation is not None and qq:
        binding = qq['binding']
        if conversation != binding['account_id']+':group:'+binding['group_id']:
            raise ValueError('tool snapshot conversation mismatch')
    return snapshot


def startup_prompt(prompt, snapshot):
    validate_snapshot(snapshot)
    qq = snapshot.get('qq_tools')
    result = prompt if not qq else prompt+'\n\n'+qq['startup']
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
    from startup_knowledge import render_servers
    knowledge = render_servers(snapshot.get('servers', {}), qq['binding'] if qq else None, snapshot.get('knowledge_application'))
    result = result+'\n\n'+knowledge if knowledge else result
    from knowledge_application import protocol
    application = protocol(snapshot.get('knowledge_application'))
    return result+'\n\n'+application if application else result



def codex_overrides(path, *, existing_servers=(), conversation=None, host_wait=False, knowledge_budget=None, research_links=None, knowledge_application=None):
    path = Path(path).resolve()
    snapshot = load_snapshot(path, conversation=conversation)
    servers = server_configs(snapshot, path, python=sys.executable,
                             proxy=str(Path(__file__).with_name('tool_proxy.py')), host_wait=host_wait)
    if knowledge_budget:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
        from knowledge_tools import provider_mode
        for name, config in servers.items():
            if provider_mode(snapshot['servers'].get(name, {})):
                config['args'] += ['--knowledge-budget', str(knowledge_budget)]
    if research_links:
        if not conversation:raise ValueError('research_links_conversation_required')
        for name, config in servers.items():
            source = snapshot['servers'].get(name, {})
            if source.get('url') and {'plan_chat_reply','send_chat_reply'}.intersection(source.get('tools', [])):
                config['args'] += ['--research-links', str(research_links), '--conversation', conversation]
    if knowledge_application:
        from knowledge_tools import provider_mode
        from knowledge_application import policy
        if not policy(snapshot.get('knowledge_application'))['enabled']:
            raise ValueError('knowledge_application_not_enabled')
        for name, config in servers.items():
            definition=snapshot['servers'].get(name,{})
            if provider_mode(definition) or definition.get('reading_trace') or 'plan_chat_reply' in definition.get('tools',[]):
                config['args'] += ['--knowledge-application', str(knowledge_application)]
                if knowledge_budget and '--knowledge-budget' not in config['args']:
                    config['args'] += ['--knowledge-budget', str(knowledge_budget)]
    overrides = {f'mcp_servers.{name}.enabled': False for name in existing_servers}
    for name, config in servers.items():
        # Fresh namespaces avoid inheriting an old URL, credential or disabled list.
        managed = 'qq-managed-'+name
        tools = ['read_qq_tool_guide'] if name == 'qq-guides' else snapshot['servers'][name]['tools']
        if '--research-links' in config.get('args', []):
            tools = [*tools, 'read_research_report']
        if snapshot['servers'].get(name, {}).get('reading_trace'):
            tools = [*tools, 'begin_reading_task', 'finish_reading_task', 'declare_native_read']
        for key, value in {**config, 'enabled': True, 'enabled_tools': tools,
                           'tool_timeout_sec': 3660 if 'wait_chat_messages' in tools else 245}.items():
            overrides[f'mcp_servers.{managed}.{key}'] = value
        original=snapshot['servers'].get(name,{})
        env_vars=list(original.get('env_vars',[]))
        if original.get('bearer_token_env_var'):
            env_vars.append(original['bearer_token_env_var'])
        if env_vars:
            overrides[f'mcp_servers.{managed}.env_vars']=sorted(set(env_vars))
        for tool in tools:
            overrides[f'mcp_servers.{managed}.tools.{tool}.approval_mode'] = 'approve'
    return overrides
