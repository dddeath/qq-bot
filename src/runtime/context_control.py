"""Session-local proactive compaction decisions at host-controlled boundaries."""


class CompactionPolicy:
    def __init__(self, *, long_tool_seconds=30, usage_ratio=.75):
        if long_tool_seconds <= 0 or not 0 < usage_ratio < 1:
            raise ValueError('invalid compaction thresholds')
        self.long_tool_seconds = long_tool_seconds
        self.usage_ratio = usage_ratio
        self.seen_tools = set()
        self.active = False
        self.pending = None
        self.in_flight = False

    def tool_completed(self, event_id, tool_name, duration_seconds):
        if event_id in self.seen_tools:
            return
        self.seen_tools.add(event_id)
        if tool_name.rsplit('.', 1)[-1] == 'wait_chat_messages':
            return
        if duration_seconds >= self.long_tool_seconds and self.pending != 'sleep':
            self.pending = 'long_tool'

    def observe(self, *, active, busy, tokens, window):
        if self.active and not active:
            self.pending = 'sleep'
        self.active = active
        if busy or self.in_flight or self.pending is None:
            return None
        reason, self.pending = self.pending, None
        if reason == 'long_tool' and (tokens is None or window is None or window <= 0 or tokens <= window*self.usage_ratio):
            return None
        self.in_flight = True
        return reason

    def completed(self):
        self.in_flight = False
