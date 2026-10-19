"""Render frozen tool snapshots into native harness configuration and short input."""
import json
from pathlib import Path
import sys


def server_configs(snapshot, path, *, python, proxy, host_wait=False):
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
    if conversation is not None and qq:
        binding = qq['binding']
        if conversation != binding['account_id']+':group:'+binding['group_id']:
            raise ValueError('tool snapshot conversation mismatch')
    return snapshot


def startup_prompt(prompt, snapshot):
    qq = snapshot.get('qq_tools')
    return prompt if not qq else prompt+'\n\n'+qq['startup']


def codex_overrides(path, *, existing_servers=(), conversation=None, host_wait=False):
    path = Path(path).resolve()
    snapshot = load_snapshot(path, conversation=conversation)
    servers = server_configs(snapshot, path, python=sys.executable,
                             proxy=str(Path(__file__).with_name('tool_proxy.py')), host_wait=host_wait)
    overrides = {f'mcp_servers.{name}.enabled': False for name in existing_servers}
    for name, config in servers.items():
        # Fresh namespaces avoid inheriting an old URL, credential or disabled list.
        managed = 'qq-managed-'+name
        tools = ['read_qq_tool_guide'] if name == 'qq-guides' else snapshot['servers'][name]['tools']
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
