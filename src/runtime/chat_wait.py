"""Hold empty Tulpa waits in the host; only meaningful events reach the model."""
import time


def wait_for_event(upstream, arguments, wake, *, max_wait_seconds=3600,
                   poll_seconds=10, monotonic=time.monotonic):
    deadline = monotonic() + max_wait_seconds
    args = dict(arguments)
    while True:
        notification = wake()
        if notification is not None:
            return notification
        remaining = deadline - monotonic()
        if remaining < 1:
            return {'event': 'wait_deadline', 'messages': []}
        args['timeout_seconds'] = min(poll_seconds, remaining)
        result = upstream(args)
        if result.get('event') != 'idle' or result.get('messages') != []:
            return result
        if any(result.get(key) for key in ('control_events', 'background_results', 'error', 'prompt_updated', 'prompt_changed', 'has_more')):
            return result
        if result.get('receiver', {}).get('state', 'connected') != 'connected':
            return result
        if result.get('input_batch', {}).get('phase', 'WAITING') != 'WAITING':
            return result
        if 'next_call' not in result:
            # Some Tulpa idle responses omit next_call; retain the original session.
            if 'read_through_id' in result:
                args['acknowledge_through_id'] = result['read_through_id']
            continue
        next_call = result.get('next_call', {})
        if next_call.get('tool') != 'wait_chat_messages':
            return result
        next_args = next_call.get('arguments', {})
        if next_args.get('session_id') != args.get('session_id'):
            return result
        args.update(next_args)


class NativeCompletions:
    """Tail only children of this native thread; do not replay historical results."""
    def __init__(self, root, thread, record_run=None):
        self.root, self.thread = root, thread
        self.record_run = record_run
        self.files = {}
        self._scan(baseline=True)

    def _record(self, state, path, status, timestamp, payload):
        if self.record_run is None:
            return
        from datetime import datetime
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'sessions'))
        from run_records import receipt
        def seconds(value):
            if not value:return None
            try:return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
            except (ValueError, TypeError):return None
        item=receipt(dict(purpose='research',harness='codex'),
                     state[0]+':'+str(state[2] or timestamp), status=status,
                     started_at=seconds(state[2]), finished_at=None if status=='running' else seconds(timestamp),
                     native_session_id=state[0], result=payload if status!='running' else None,
                     evidence=str(path))
        item['parent_native_session_id']=self.thread
        self.record_run(item)

    def _scan(self, baseline=False):
        import json
        results = []
        for path in self.root.rglob('rollout-*.jsonl'):
            if path not in self.files:
                with path.open('rb') as f:
                    line = f.readline()
                    try:
                        meta = json.loads(line)['payload']
                    except (ValueError, KeyError):
                        continue
                    source = meta.get('source', {})
                    subagent = source.get('subagent', {}) if isinstance(source, dict) else {}
                    spawn = subagent.get('thread_spawn', {}) if isinstance(subagent, dict) else {}
                    if spawn.get('parent_thread_id') != self.thread:
                        self.files[path] = None
                        continue
                    self.files[path] = [meta.get('id'), path.stat().st_size if baseline else f.tell(), None]
            state = self.files[path]
            if state is None:
                continue
            with path.open('rb') as f:
                f.seek(state[1])
                while True:
                    line = f.readline()
                    if not line.endswith(b'\n'):
                        break
                    state[1] = f.tell()
                    row = json.loads(line)
                    payload = row.get('payload', {})
                    if row.get('type') == 'event_msg' and payload.get('type') == 'task_started':
                        state[2] = row.get('timestamp')
                        self._record(state,path,'running',row.get('timestamp'),payload)
                    if row.get('type') == 'event_msg' and payload.get('type') in ('task_complete', 'turn_aborted'):
                        from datetime import datetime
                        elapsed = None
                        if state[2] and row.get('timestamp'):
                            try:
                                value = (datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00')) - datetime.fromisoformat(state[2].replace('Z', '+00:00'))).total_seconds()
                                elapsed = value if value >= 0 else None
                            except (ValueError, TypeError):
                                pass
                        self._record(state,path,'succeeded' if payload['type']=='task_complete' else 'cancelled',row.get('timestamp'),payload)
                        results.append({'agent_id': state[0], 'result': payload, 'timestamp': row.get('timestamp'),
                                        'started_at': state[2], 'elapsed_seconds': elapsed})
                        state[2] = None
        return {'event': 'background_results', 'results': results, 'messages': []} if results else None

    def __call__(self):
        return self._scan()
