"""Host-owned waiting and safe between-turn compaction for Codex sessions."""
from context_control import CompactionPolicy
from codex_session_control import ServerOverloaded
import hashlib
import json


class ChatLoop:
    def __init__(self, session, session_id, *, window, policy=None, record=lambda event: None):
        self.session = session
        self.arguments = {'session_id': session_id}
        self.window = window
        self.policy = policy or CompactionPolicy()
        self.record = record
        self.active = False
        self.handled = set()
        self.retry_delay = 0

    def event_keys(self, kind, items):
        return [(kind, hashlib.sha256(json.dumps(
            item.get('id', item) if kind != 'background' else item,
            sort_keys=True, ensure_ascii=False).encode()).hexdigest()) for item in items]

    def observe_activation(self, active):
        if active is not None:
            self.active = active
        # Defer execution until the current host event has been classified.
        self.policy.observe(active=self.active, busy=True, tokens=None, window=self.window)

    def maintain(self):
        usage = self.session.last_usage
        tokens = usage['last']['totalTokens'] if usage else None
        reason = self.policy.observe(active=self.active, busy=False, tokens=tokens, window=self.window)
        if reason:
            try:
                result = self.session.compact()
                self.record(dict(event='proactive_compaction', reason=reason, result=result))
            except ServerOverloaded as error:
                self.record(dict(event='compaction_overload', turn_id=error.turn_id, action='continue_chat'))
            finally:
                self.policy.completed()

    def handle(self, body, *, blocks=None):
        self.retry_delay = 0
        event = body.get('event')
        if event in ('stopped', 'revoked'):
            self.record({'event': 'wake_decision', 'action': 'stop', 'reason': event})
            raise RuntimeError('Tulpa session '+event)
        if event == 'source_unavailable' or body.get('receiver', {}).get('state', 'connected') != 'connected':
            self.retry_delay = 10
            self.record({'event': 'wake_decision', 'action': 'wait', 'reason': 'source_unavailable'})
            return
        keys = []
        if event == 'background_results':
            results = body.get('results', [])
            fresh = [(k, r) for k, r in zip(self.event_keys('background', results), results) if k not in self.handled]
            keys = [k for k, _ in fresh]
            body = {**body, 'results': [r for _, r in fresh]}
        elif body.get('messages'):
            keys = self.event_keys('message', body['messages'])
        elif body.get('control_events'):
            controls = body['control_events']
            fresh = [(k, c) for k, c in zip(self.event_keys('control', controls), controls) if k not in self.handled]
            keys = [k for k, _ in fresh]
            body = {**body, 'control_events': [c for _, c in fresh]}
        meaningful = any(k not in self.handled for k in keys)
        self.record({'event': 'wake_decision', 'action': 'model' if meaningful else 'wait',
                     'reason': event, 'new_items': sum(k not in self.handled for k in keys)})
        if body.get('event') == 'background_results':
            for result in body.get('results', []):
                if result.get('elapsed_seconds') is not None:
                    self.policy.tool_completed((result.get('agent_id'), result.get('timestamp')),
                                               'background_research', result['elapsed_seconds'])
            # Results are buffered by the host before the next response starts.
            self.maintain()
        if meaningful:
            result = self.session.run_turn(body if blocks is None else {'payload': body, 'content': blocks})
            if result['status'] not in ('completed', 'overload_abandoned'):
                raise RuntimeError('chat turn incomplete; acknowledgement retained')
            self.record(dict(event='chat_turn_result', result=result))
            self.handled.update(keys)
        if not meaningful and event not in ('idle', 'messages', 'background_results', 'control'):
            self.retry_delay = 10
            return
        next_call = body.get('next_call', {})
        next_args = next_call.get('arguments', {})
        if next_call.get('tool') == 'wait_chat_messages' and next_args.get('session_id') == self.arguments['session_id']:
            self.arguments.update(next_args)
        elif body.get('read_through_id') is not None:
            self.arguments['acknowledge_through_id'] = body['read_through_id']
        self.maintain()
