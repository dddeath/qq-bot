"""Bot-scoped QQ capabilities resolved against the existing ToolProfile allowlist."""
import copy
import hashlib
import re
import json


def guide_hash(cap):
    return hashlib.sha256(json.dumps({'guide':cap['guide'],'sections':cap.get('sections',{})},
                                    ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def configured(profile, overrides):
    config = copy.deepcopy(profile.get('qq_tools', {}))
    capabilities = config.get('capabilities', {})
    if set(overrides) - set(capabilities):
        raise ValueError('unknown QQ capability override')
    for name, capability in capabilities.items():
        if not re.fullmatch(r'[a-z][a-z0-9_]*', name):
            raise ValueError('invalid QQ capability name')
        override = overrides.get(name, {})
        if set(override) - {'enabled', 'parameters'}:
            raise ValueError('QQ overrides accept enabled and parameters only')
        enabled = override.get('enabled', capability.get('enabled', True))
        if type(enabled) is not bool:
            raise ValueError('QQ capability enabled must be boolean')
        capability['enabled'] = enabled
        defaults = capability.setdefault('parameters', {})
        if set(override.get('parameters', {})) - set(defaults):
            raise ValueError('unknown QQ capability parameter')
        defaults.update(override.get('parameters', {}))
        for key, value in defaults.items():
            if not re.fullmatch(r'[a-z][a-z0-9_]*', key) or not isinstance(value, (str, int, float, bool)):
                raise ValueError('QQ parameters must be named scalar values')
        if not capability.get('summary') or not capability.get('guide') or not capability.get('tools'):
            raise ValueError('QQ capability requires summary, guide and tools')
        for server, names in capability['tools'].items():
            if not isinstance(names, list) or not names or set(names) - set(profile['servers'].get(server, {}).get('tools', [])):
                raise ValueError('QQ capability tools must exist in the profile')
    return config


def parameter_bindings(config):
    return {'qq_'+name+'_'+key: value
            for name, cap in config.get('capabilities', {}).items()
            for key, value in cap.get('parameters', {}).items()}


def resolve(config, servers, *, account_id, group_id):
    """Intersect capabilities with harness, binding and per-tool availability."""
    owned, enabled = {}, {}
    for cap in config.get('capabilities', {}).values():
        for server, names in cap['tools'].items():
            owned.setdefault(server, set()).update(names)
            if cap['enabled']:
                enabled.setdefault(server, set()).update(names)
    for server, names in owned.items():
        if server in servers:
            servers[server]['tools'] = [name for name in servers[server]['tools']
                if name not in names or name in enabled.get(server, set())]
    available = {}
    for name, cap in config.get('capabilities', {}).items():
        actual = {server: [tool for tool in names if tool in servers.get(server, {}).get('tools', [])]
                  for server, names in cap['tools'].items()}
        actual = {server: names for server, names in actual.items() if names}
        if cap['enabled'] and actual:
            available[name] = {**cap, 'tools': actual,
                'guide_sha256': guide_hash(cap)}
    binding = dict(account_id=account_id, group_id=group_id)
    startup = config.get('core', '').strip()
    startup += '\n当前 QQ 账号：'+account_id+'；当前群：'+group_id+'。\n'
    for name, cap in available.items():
        tools = ', '.join(tool for names in cap['tools'].values() for tool in names)
        startup += f"\n- {name}：{cap['summary']} 可用工具：{tools}。操作细则：read_qq_tool_guide(capability=\"{name}\")。"
    startup += '\n操作细则按需读取；当前上下文中已读且适用的细则直接复用。'
    return dict(binding=binding, capabilities=available, startup=startup)
