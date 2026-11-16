"""Single-owner stdio RPC transport retaining notifications across responses."""
from collections import deque
import json
import os
import queue
import signal
import subprocess
import threading
import time


class AppServerTransport:
    def __init__(self, command, *, cwd=None, stderr=None, record=lambda event: None):
        self.process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=stderr, text=True, encoding='utf-8',
            bufsize=1, start_new_session=os.name != 'nt')
        self.queue = queue.Queue()
        self.pending = deque()
        self.sequence = 0
        self.record = record
        self.runtime = None
        self.catalog_verified = False
        self.stage_catalog_required = False
        for index, value in enumerate(command[:-1]):
            if value == '-c' and command[index+1].startswith('features.mcp_tool_list_changed='):
                self.stage_catalog_required = json.loads(command[index+1].split('=', 1)[1]) is True
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        try:
            for line in self.process.stdout:
                self.queue.put(json.loads(line))
        except Exception as exc:
            self.queue.put(exc)
        finally:
            self.queue.put(EOFError('App Server closed stdout'))

    def send(self, message):
        self.process.stdin.write(json.dumps(message, ensure_ascii=False)+'\n')
        self.process.stdin.flush()

    def _read(self, timeout):
        try:
            event = self.queue.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError('App Server response timeout') from None
        if isinstance(event, Exception):
            raise event
        self.record(event)
        if 'method' in event and 'id' in event:
            self.send({'id': event['id'], 'error': {'code': -32601,
                'message': 'Interactive requests are not enabled in this runner'}})
        return event

    def call(self, method, params, *, timeout=60):
        if method in ('thread/start', 'thread/resume') and self.stage_catalog_required and not self.catalog_verified:
            self._verify_stage_catalog(timeout)
        self.sequence += 1
        request_id = self.sequence
        self.send({'id': request_id, 'method': method, 'params': params})
        deadline = time.monotonic()+timeout
        while True:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('App Server RPC timeout: '+method)
            event = self._read(remaining)
            if 'method' not in event and event.get('id') == request_id:
                if 'error' in event:
                    raise RuntimeError(event['error'])
                if method == 'initialize':
                    self.runtime = event['result'].get('userAgent')
                return event['result']
            if 'method' in event and 'id' not in event:
                self.pending.append(event)

    def _verify_stage_catalog(self, timeout):
        """Check the actual connected host before starting or resuming a thread."""
        cursor = None
        seen = set()
        deadline = time.monotonic() + min(timeout, 30)
        feature = None
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Codex stage catalog capability check timeout')
            page = self.call('experimentalFeature/list', {'limit':100, **({'cursor':cursor} if cursor else {})}, timeout=remaining)
            feature = next((item for item in page.get('data', []) if item.get('name') == 'mcp_tool_list_changed'), None)
            if feature:
                break
            cursor = page.get('nextCursor')
            if not cursor:
                break
            if cursor in seen:
                raise RuntimeError('Codex stage catalog capability pagination repeated')
            seen.add(cursor)
        verified = bool(feature and feature.get('enabled') is True and feature.get('stage') != 'removed')
        self.record({'method':'host/runtimeCapabilities', 'params':{
            'runtime':self.runtime, 'required_feature':'mcp_tool_list_changed',
            'feature':feature, 'verified':verified}})
        if not verified:
            raise RuntimeError('Codex runtime lacks enabled mcp_tool_list_changed; install the pinned config/codex-runtime.json runtime before starting this session')
        self.catalog_verified = True

    def next_event(self, timeout):
        if self.pending:
            return self.pending.popleft()
        deadline = time.monotonic()+timeout
        while True:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError('App Server notification timeout')
            event = self._read(remaining)
            if 'method' in event and 'id' not in event:
                return event

    def close(self):
        if self.process.poll() is None:
            if os.name == 'nt':
                self.process.terminate()
            else:
                os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                if os.name == 'nt':
                    self.process.kill()
                else:
                    os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait()
        self.process.stdin.close()
        self.process.stdout.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
