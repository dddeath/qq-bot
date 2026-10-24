"""Wire existing read providers to the shared protocol in a versioned profile."""
from copy import deepcopy
from learning_research import ALLOWED
from knowledge_tools import ALL_TOOLS as KNOWLEDGE_TOOLS


def wire_research_profile(profile, *, trace_root, native_sessions_directory):
    result = deepcopy(profile)
    for server in result['servers'].values():
        tools = set(server.get('tools', []))
        if not tools.intersection(ALLOWED):
            continue
        if not server.get('command') or tools - ALLOWED:
            raise ValueError('research_provider_requires_read_only_stdio')
        if {'get_video_context', 'get_video_comments'}.issubset(tools):
            server['tools'] = list(dict.fromkeys([*server['tools'], 'get_video_comment_threads']))
        server['reading_trace'] = {
            'max_read_units': 10, 'exploration_budget_ratio': .2, 'timeout_seconds': 300,
            **server.get('reading_trace', {}),
            'root': str(trace_root).rstrip('/\\')+'/${account_id}/${group_id}',
            'scope': 'qq:${account_id}:group:${group_id}',
            'native_sessions_directory': str(native_sessions_directory),
            'require_context': not tools.issubset(KNOWLEDGE_TOOLS),
        }
    return result
