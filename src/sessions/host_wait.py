"""Host-owned waiting projection for Tulpa control fields, never chat contents."""
from copy import deepcopy
import json

HOST_WAIT = '本批处理完后结束当前轮次，由宿主等待并交付下一批消息或后台结果。'
CHAT_TOOLS = {'start_chat_session', 'get_chat_session', 'plan_chat_reply', 'send_chat_reply',
              'select_chat_expressions', 'send_chat_message', 'send_chat_sticker'}


def host_text(text):
    """Translate known system-owned legacy instructions to event-driven semantics."""
    if not isinstance(text, str):
        return text
    # These paragraphs describe the old model-owned loop, not message data.
    paragraphs = {
        '暂时没有新消息；不发群消息，现在直接调用 wait_chat_messages。': HOST_WAIT,
        '统一循环：': HOST_WAIT,
        '循环调用 wait_chat_messages。': '消息交付与处理进度确认由宿主负责；has_more=true 时宿主继续读取下一批。',
        'idle/等待超时只表示': 'idle、等待超时和 source_unavailable 由宿主续等；消息源恢复后继续交付。stopped 或 revoked 结束聊天；用户明确停止时调用 stop_chat_session。',
        '处理完一批消息，确认游标并继续 wait_chat_messages。': HOST_WAIT,
        '开始即在当前机器人账号与群内边聊边学': '学习功能沿当前已启用能力配置执行。',
    }
    lines = []
    for line in text.split('\n'):
        for prefix, replacement in paragraphs.items():
            if line.startswith(prefix):
                line = replacement
                break
        lines.append(line)
    text = '\n'.join(lines)
    replacements = {
        '沉默就是不调用发送，下一步直接调用 wait_chat_messages。': '沉默就是不调用发送，处理完本批后结束当前轮次，由宿主续等。',
        '不用再做一次空 Planner，直接继续等待。': '不用再做一次空 Planner，处理完本批后结束当前轮次。',
        '成功发送后的 next_call 已带本轮确认游标；只在这批已处理完时沿用。': '本批处理进度由宿主确认。',
        'needs_wait 时继续 wait。': 'needs_wait 时结束本轮交回宿主。',
        '继续 wait_chat_messages': HOST_WAIT.rstrip('。'),
        'idle/没有新输入无需额外规划，直接用 next_call 或 continue_with 继续等待。': 'idle/没有新输入无需额外规划，结束本轮交回宿主。',
        'needs_wait 按提示等待': 'needs_wait 结束本轮交回宿主',
        '下次等待带 known_prompt_version，版本变化会重新给出完整提示。': '提示版本由宿主管理，版本变化时更新提示。',
        '处理完本批后直接调用；不要为了等待再提交空规划。': HOST_WAIT,
        '平时使用 wait_chat_messages(timeout_seconds=180, quiet_seconds=0.5)；有后台任务时按 qq-background-work 技能缩短等待。': HOST_WAIT,
        '处理后只确认实际返回的 read_through_id。': '处理进度由宿主按实际返回的 read_through_id 确认。',
        'idle 继续等待，不发送在线声明。': 'idle 由宿主续等，不发送在线声明。',
        'get_chat_session 或 wait_chat_messages': 'get_chat_session',
        '原始 wait/get 返回': '宿主交付或 get_chat_session 返回',
        '原始 wait/get/plan/send': '宿主交付/get/plan/send',
        'get/wait 返回': '宿主交付或 get_chat_session 返回',
        'wait/get 返回': '宿主交付或 get_chat_session 返回',
        'event_id 是 wait_chat_messages 的 id': 'event_id 是宿主交付消息的 id',
        '返回后直接持续执行 next_call/wait；silence 不结束循环，learning_ready 推进一个阶段后回 wait，无需用户另给学习指令。': HOST_WAIT,
        '开启并自动边聊边学': '开启',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def project_body(body):
    out = deepcopy(body)
    if not isinstance(out, dict):
        return out
    for key in ('next_call', 'continue_with'):
        call = out.get(key)
        if isinstance(call, dict) and call.get('tool') == 'wait_chat_messages':
            out.pop(key)
    for key in ('next', 'instructions', 'resume', 'when', 'behavior'):
        if isinstance(out.get(key), str):
            out[key] = host_text(out[key])
    if isinstance(out.get('reminders'), list):
        out['reminders'] = [host_text(text) for text in out['reminders']]
    for key in ('chat_guidance', 'chat_prompt', 'recovery'):
        if isinstance(out.get(key), dict):
            out[key] = project_body(out[key])
    if isinstance(out.get('recent_turns'), list):
        out['recent_turns'] = [project_body(turn) for turn in out['recent_turns']]
    # Keep capability status while omitting disabled operation instructions.
    for key in ('language_learning', 'reactions'):
        cap = out.get(key)
        if isinstance(cap, dict) and (cap.get('enabled') is False or cap.get('authorized') is False):
            out[key] = {k: cap[k] for k in ('enabled', 'authorized') if k in cap}
    return out


def project_host_response(response, request):
    out = deepcopy(response)
    result = out.get('result')
    if not isinstance(result, dict):
        return out
    if request.get('method') == 'tools/list':
        result['tools'] = [t for t in result.get('tools', []) if t.get('name') != 'wait_chat_messages']
        for tool in result['tools']:
            if 'description' in tool:
                tool['description'] = host_text(tool['description'])
    elif request.get('method') == 'tools/call' and request.get('params', {}).get('name') in CHAT_TOOLS:
        for key in ('structuredContent', 'structured_content'):
            if isinstance(result.get(key), dict):
                result[key] = project_body(result[key])
        for block in result.get('content', []):
            if block.get('type') != 'text':
                continue
            try:
                body = json.loads(block['text'])
            except (ValueError, KeyError):
                continue
            if isinstance(body, dict):
                block['text'] = json.dumps(project_body(body), ensure_ascii=False)
    return out
