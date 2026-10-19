"""Host control protocol v1. Data fields never participate in control decoding."""
from copy import deepcopy
from pathlib import Path
import json

HOST_WAIT = '本批处理完后结束当前轮次，由宿主等待并交付下一批消息或后台结果。'
GUIDES = Path(__file__).resolve().parents[2] / 'prompts/qq-tools/host'
CHAT_TOOLS = {'start_chat_session', 'get_chat_session', 'plan_chat_reply', 'send_chat_reply',
              'select_chat_expressions', 'send_chat_message', 'send_chat_sticker'}
DESCRIPTIONS = {
 'start_chat_session': '在当前授权账号和群开启或接续聊天。先 list_chat_personas 查询人格 id；新会话保存人格快照，同群同人格接续。消息和游标由宿主管理，学习按独立配置执行。',
 'plan_chat_reply': '根据宿主交付或 get_chat_session 返回的 input_batch.id，选择 wait、silence 或 reply、回应对象与表达通道。只提交简短沟通意图。READY 沿 next_call 完成表达选择和发送；等待或沉默交回宿主。',
 'read_chat_image': '读取当前聊天事件图片的真实像素；动图最多3帧。event_id 使用宿主交付或 get_chat_session 中消息的 id，index 使用 image_index。看图后再描述。',
}


def guide_text(name):
    return (GUIDES / (name + '.md')).read_text(encoding='utf-8')


def project_body(body, *, event=None, has_more=False):
    out = deepcopy(body)
    if not isinstance(out, dict):
        return out
    event = out.get('event', event)
    has_more = out.get('has_more', has_more)
    waiting = False
    for key in ('next_call', 'continue_with'):
        call = out.get(key)
        if isinstance(call, dict) and call.get('tool') == 'wait_chat_messages':
            out.pop(key)
            waiting = True
    state = out.get('state', out.get('status'))
    if waiting:
        out.pop('when', None)
    if 'next' in out or waiting:
        call = out.get('next_call') or (out.get('plan_call') if out.get('decision_required') is not False else None)
        action = 'call' if isinstance(call, dict) and call.get('tool') else 'yield'
        out['control'] = dict(version=1, owner='host', action=action, state=state)
        if action == 'call':
            out['control']['tool'] = call['tool']
            out['next'] = '沿返回的 ' + ('next_call' if out.get('next_call') else 'plan_call') + ' 完成当前动作；其余等待由宿主负责。'
        else:
            out['next'] = HOST_WAIT
    if 'instructions' in out:
        out['instructions'] = guide_text('instructions')
    if 'behavior' in out:
        out['behavior'] = guide_text('behavior')
    if 'resume' in out:
        out['resume'] = '需要恢复人格或上下文时读取 get_chat_session；提示版本由宿主管理。'
    # Tulpa packet v1 has three base hints, followed by one conditional
    # delivery hint. Select its meaning from event fields, not Chinese prose.
    hints = out.get('reminders')
    if isinstance(hints, list) and len(hints) >= 4:
        notices = out.get('reaction_notices') or {}
        if event == 'idle':
            hints[3] = HOST_WAIT
        elif event == 'source_unavailable':
            hints[3] = '消息源暂不可用，宿主等待恢复；本轮不发送。'
        elif has_more:
            hints[3] = '还有未读消息，宿主继续交付；依据完整材料决定回应。'
        elif notices.get('new_items'):
            hints[3] = '读取 reaction_notices.new_items 的原消息和操作者，结合语境决定回应或沉默；不重复回应旧通知和自己的回声。处理完交回宿主。'
    for key in ('chat_guidance', 'chat_prompt', 'recovery', 'input_batch'):
        if isinstance(out.get(key), dict):
            out[key] = project_body(out[key], event=event, has_more=has_more)
    if isinstance(out.get('recent_turns'), list):
        out['recent_turns'] = [project_body(turn, event=event) for turn in out['recent_turns']]
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
            if tool.get('name') in DESCRIPTIONS:
                tool['description'] = DESCRIPTIONS[tool['name']]
            if tool.get('name') == 'send_chat_message':
                prop = tool.get('inputSchema', {}).get('properties', {}).get('reply_to_event_id')
                if isinstance(prop, dict):
                    prop['description'] = '宿主交付或 get_chat_session.context 中消息的 id；仅选择回应目标，quote 决定是否显示引用。'
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
