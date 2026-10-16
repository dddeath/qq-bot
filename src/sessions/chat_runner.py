"""Continue a native tool-driven chat; QQ writes remain owned by Tulpa."""
import time
import uuid


def run(api, session_id, *, execute, prompt, active, deadline, clock=time.time, pause=time.sleep):
    turns=[]
    while clock()<deadline:
        if not active():return {'reason':'chat_stopped','turns':turns}
        turn=api.send(session_id,prompt,request_id='tulpa-chat-'+uuid.uuid4().hex,execute=execute)
        turns.append(turn['request_id'])
        recoverable=turn.get('continuation',{}).get('action')=='abandon_auxiliary_read'
        if turn['status']!='success' and not recoverable:return {'reason':'native_result_unknown','turns':turns}
        # The final CLI response is a control-plane result, never a QQ bubble.
        prompt='继续同一 Tulpa 群聊和原生线程。保留正在执行的子代理及原请求关联，先读取完整新消息，再检查后台结果。已取得发送回执的内容不重复发送。'
        if recoverable:
            prompt='上一轮辅助只读操作被权限拒绝。放弃该动作及其目标资源，不重试或换工具绕过；不因此停止聊天。保留原线程与群会话，读取新消息继续聊天。已有发送回执不重发，发送结果未知时仍停发。无需向群里报告内部权限错误。'
        pause(min(2,max(0,deadline-clock())))
    return {'reason':'window_closed','turns':turns}
