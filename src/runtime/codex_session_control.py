"""Serialized Codex App Server session control; no live runner ownership transfer."""
import time


class ServerOverloaded(RuntimeError):
    def __init__(self, turn_id, tools_started):
        super().__init__('Codex serverOverloaded')
        self.turn_id, self.tools_started = turn_id, tools_started


class CodexSession:
    def __init__(self, transport, thread_id=None, *, record=lambda event: None):
        self.transport = transport
        self.thread_id = thread_id
        self.last_usage = None
        self.record = record

    def configure(self, instructions, **options):
        params = dict(options, developerInstructions=instructions)
        if self.thread_id:
            params['threadId'] = self.thread_id
            params['excludeTurns'] = True
        result = self.transport.call('thread/resume' if self.thread_id else 'thread/start', params)
        self.thread_id = result['thread']['id']
        return self.thread_id

    def run_turn(self, text, *, timeout=180):
        inputs = text if isinstance(text, list) else [{'type': 'text', 'text': text}]
        for attempt in range(4):
            result = self.transport.call('turn/start', {'threadId': self.thread_id, 'input': inputs})
            try:
                return self._finish(result['turn']['id'], False, timeout)
            except ServerOverloaded as error:
                # A tool may already have changed external state, including an unknown send result.
                # Never replay that action or ask the model to repeat the batch.
                stop = error.tools_started or attempt == 3
                self.record(dict(event='overload_recovery', thread_id=self.thread_id,
                                 turn_id=error.turn_id, attempt=attempt+1,
                                 action='abandon_action' if stop else 'retry',
                                 reason='tool_started' if error.tools_started else 'retry_limit' if stop else 'serverOverloaded',
                                 delay_seconds=0 if stop else 2**(attempt+1)))
                if stop:
                    return dict(status='overload_abandoned', turn_id=error.turn_id,
                                reason='tool_started' if error.tools_started else 'retry_limit')
                time.sleep(2**(attempt+1))
                inputs = [{'type': 'text', 'text': '上一轮因模型服务过载失败，且尚未启动工具。继续处理该轮已有输入，不重复引入原始批次。'}]

    def compact(self, *, timeout=180):
        self.transport.call('thread/compact/start', {'threadId': self.thread_id})
        return self._finish(None, True, timeout)

    def _finish(self, turn_id, compact, timeout):
        started = time.monotonic()
        item_done = False
        tools_started = False
        answers = []
        before = self.last_usage
        while True:
            remaining = timeout-(time.monotonic()-started)
            if remaining <= 0:
                raise TimeoutError('Codex turn completion timeout')
            event = self.transport.next_event(remaining)
            params = event.get('params', {})
            if params.get('threadId') != self.thread_id:
                continue
            method = event.get('method')
            if compact and turn_id is None and method == 'turn/started':
                turn_id = params['turn']['id']
            if method == 'thread/tokenUsage/updated':
                self.last_usage = params['tokenUsage']
            if method in ('item/started', 'item/completed') and params.get('turnId') == turn_id:
                kind = params.get('item', {}).get('type')
                if kind in ('mcpToolCall', 'dynamicToolCall', 'commandExecution', 'codeExecution', 'imageGeneration', 'webSearch'):
                    tools_started = True
            if method == 'item/completed':
                item = params.get('item', {})
                if compact and item.get('type') == 'contextCompaction' and turn_id in (None, params['turnId']):
                    turn_id, item_done = params['turnId'], True
                elif params.get('turnId') == turn_id and item.get('type') == 'agentMessage':
                    answers.append(item['text'])
            if method == 'turn/completed' and params['turn']['id'] == turn_id:
                turn = params['turn']
                if turn['status'] != 'completed' or (compact and not item_done):
                    if (turn.get('error') or {}).get('codexErrorInfo') == 'serverOverloaded':
                        raise ServerOverloaded(turn_id, tools_started)
                    raise RuntimeError('Codex operation did not complete: '+turn['status'])
                return dict(status=turn['status'], turn_id=turn_id, answers=answers,
                            elapsed_seconds=time.monotonic()-started,
                            usage_before=before, usage_after=self.last_usage)
