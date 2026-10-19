"""Serialized Codex App Server session control; no live runner ownership transfer."""
import time


class CodexSession:
    def __init__(self, transport, thread_id=None):
        self.transport = transport
        self.thread_id = thread_id
        self.last_usage = None

    def configure(self, instructions, **options):
        params = dict(options, developerInstructions=instructions)
        if self.thread_id:
            params['threadId'] = self.thread_id
        result = self.transport.call('thread/resume' if self.thread_id else 'thread/start', params)
        self.thread_id = result['thread']['id']
        return self.thread_id

    def run_turn(self, text, *, timeout=180):
        result = self.transport.call('turn/start', {
            'threadId': self.thread_id, 'input': text if isinstance(text, list) else [{'type': 'text', 'text': text}]})
        return self._finish(result['turn']['id'], False, timeout)

    def compact(self, *, timeout=180):
        self.transport.call('thread/compact/start', {'threadId': self.thread_id})
        return self._finish(None, True, timeout)

    def _finish(self, turn_id, compact, timeout):
        started = time.monotonic()
        item_done = False
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
            if method == 'item/completed':
                item = params.get('item', {})
                if compact and item.get('type') == 'contextCompaction' and turn_id in (None, params['turnId']):
                    turn_id, item_done = params['turnId'], True
                elif params.get('turnId') == turn_id and item.get('type') == 'agentMessage':
                    answers.append(item['text'])
            if method == 'turn/completed' and params['turn']['id'] == turn_id:
                turn = params['turn']
                if turn['status'] != 'completed' or (compact and not item_done):
                    raise RuntimeError('Codex operation did not complete: '+turn['status'])
                return dict(status=turn['status'], turn_id=turn_id, answers=answers,
                            elapsed_seconds=time.monotonic()-started,
                            usage_before=before, usage_after=self.last_usage)
