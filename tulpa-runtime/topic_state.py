"""Bounded group/topic state. No network, QQ sender, or live chat integration."""
from dataclasses import dataclass
from copy import deepcopy


@dataclass(frozen=True)
class Limits:
    max_messages: int = 200
    max_age_seconds: float = 1800
    max_total_chars: int = 24000

    def __post_init__(self):
        if min(self.max_messages, self.max_age_seconds, self.max_total_chars) <= 0:
            raise ValueError('limits must be positive')


def bounded(messages, limits, now):
    kept = [m for m in messages if now - m['at'] <= limits.max_age_seconds]
    while len(kept) > limits.max_messages or sum(len(m['text']) for m in kept) > limits.max_total_chars:
        kept.pop(0)
    return kept


class TopicState:
    def __init__(self, *, group_limits=Limits(), message_chars=2000,
                 topic_limits=Limits(50, 1200, 8000), max_topics=5, idle_seconds=600,
                 participation_probability=0.15, stale_grace_seconds=45,
                 mention_reply_probability=1.0, context_reply_probability=1.0, bot_id='1000000011'):
        if message_chars <= 0:
            raise ValueError('message_chars must be positive')
        self.group_limits = group_limits
        self.message_chars = message_chars
        self.messages = []
        if not 1 <= max_topics <= 5 or idle_seconds <= 0:
            raise ValueError('max_topics must be 1..5; idle_seconds positive')
        self.topic_limits, self.max_topics, self.idle_seconds = topic_limits, max_topics, idle_seconds
        self.topics, self.maintenance = {}, []
        self.next_topic = 0
        if not all(0 <= p <= 1 for p in (participation_probability,mention_reply_probability,context_reply_probability)):
            raise ValueError('probability must be 0..1')
        self.participation_probability = participation_probability
        self.mention_reply_probability = mention_reply_probability
        self.context_reply_probability = context_reply_probability
        self.bot_id = str(bot_id)
        self.queue, self.decisions = [], {}
        self.pending = {}
        if stale_grace_seconds < 0:
            raise ValueError('grace must be nonnegative')
        self.stale_grace_seconds = stale_grace_seconds

    def _trim(self, messages, limits, now, scope):
        kept=bounded(messages,limits,now)
        ids={m['id'] for m in kept}
        removed=[m['id'] for m in messages if m['id'] not in ids]
        if removed:
            self.maintenance.append(dict(at=now,event='records_evicted',scope=scope,message_ids=removed))
        return kept

    def check_reply(self, reply_id, now):
        q = next(q for q in self.queue if q['id'] == reply_id)
        if q['status'] not in ('queued','responding','waiting_external'):
            return dict(state=q['status'])
        t = self.topics.get(q['topic_id'])
        if t is None:
            return dict(state='cancelled')
        stale = t['version'] != q['version'] and now-q['snapshot_at'] > self.stale_grace_seconds
        return dict(state='needs_refresh' if stale else 'ready', topic_id=t['id'], version=t['version'])

    def complete_reply(self, reply_id, now, *, outcome):
        if outcome not in ('historical_confirmed','simulated_complete','unknown'):
            raise ValueError('unsupported completion outcome')
        q=next(q for q in self.queue if q['id']==reply_id)
        if q['status'] not in ('queued','responding','waiting_external','needs_revision'):
            raise ValueError('reply already closed')
        q.update(status=outcome,completed_at=now)

    def refresh_reply(self, reply_id, now, *, unchanged):
        q = next(q for q in self.queue if q['id'] == reply_id)
        if q['status'] not in ('queued','responding','waiting_external','needs_revision'):
            raise ValueError('closed reply')
        if not unchanged:
            q['status'] = 'needs_revision'
        else:
            q.update(snapshot_at=now, version=self.topics[q['topic_id']]['version'])
            if q['status']=='needs_revision':q['status']='queued'

    def cancel_target(self, message_id, now, *, reason):
        self.pending.pop(message_id,None)
        for q in self.queue:
            if q['message_id'] == message_id and q['status'] in ('queued','responding','waiting_external','needs_revision'):
                q.update(status='cancelled', closed_reason=reason)
        self.maintenance.append(dict(at=now,event='target_cancelled',message_id=message_id,reason=reason))

    def create_topic(self, title, now, *, actor='main'):
        if actor != 'main':
            raise PermissionError('main owns topic lifecycle')
        if len(self.topics) >= self.max_topics:
            raise ValueError('topic capacity reached')
        self.next_topic += 1
        tid = f'T{self.next_topic:03}'
        topic = dict(id=tid, title=title, maintainer_id='M'+tid[1:], last_update=now,
                     version=0, messages=[])
        self.topics[tid] = topic
        self.maintenance.append(dict(at=now, event='maintainer_allocated', topic_id=tid,
                                     maintainer_id=topic['maintainer_id'],title=title))
        return deepcopy(topic)

    def retire_topic(self, topic_id, now, *, reason, actor='main', pending_disposition=None):
        if actor != 'main':
            raise PermissionError('main owns topic lifecycle')
        pending = [q for q in self.queue if q['topic_id'] == topic_id and q['status'] in ('queued','responding','waiting_external','needs_revision')]
        if pending and pending_disposition != 'cancel':
            raise ValueError('pending replies require an explicit disposition')
        for q in pending:
            q['status'] = 'cancelled'
            q['closed_reason'] = reason
        topic = self.topics.pop(topic_id)
        self.maintenance.append(dict(at=now, event='maintainer_released', topic_id=topic_id,
                                     maintainer_id=topic['maintainer_id'], reason=reason,
                                     cancelled_targets=[q['message_id'] for q in pending]))

    def defer_assignment(self, message_id, decision, now):
        if message_id in self.decisions:return
        message=next(m for m in self.messages if m['id']==message_id)
        self.pending.setdefault(message_id,dict(message=deepcopy(message),decision=deepcopy(decision),deferred_at=now))

    def assign(self, message_id, topic_id, *, should_reply, direct, now, draw=0.5, reason=''):
        if message_id in self.decisions:
            return deepcopy(self.decisions[message_id])
        if type(should_reply) is not bool or type(direct) is not bool or not 0 <= draw <= 1:
            raise ValueError('invalid decision')
        m = next(m for m in self.messages if m['id'] == message_id)
        topic = self.topics[topic_id]
        topic['messages'] = self._trim(topic['messages']+[deepcopy(m)], self.topic_limits, now,topic_id)
        topic['version'] += 1
        topic['last_update'] = m['at']
        source,probability=self.response_policy(m,should_reply=should_reply,direct=direct)
        reply = probability == 1 or draw < probability
        decision = dict(message_id=message_id, topic_id=topic_id, should_reply=should_reply,
                        direct=direct, action='reply' if reply else 'observe', at=now, reason=reason, draw=draw,
                        response_source=source,probability=probability)
        self.decisions[message_id] = decision
        self.pending.pop(message_id,None)
        if reply:
            self.queue.append(dict(id='R'+message_id, message_id=message_id, topic_id=topic_id,
                                   recipient=m['sender'], status='queued', snapshot_at=now,
                                   version=topic['version'], target=deepcopy(m)))
        return deepcopy(decision)

    def response_policy(self, message, *, should_reply, direct):
        if message.get('is_self',False):return 'self',0.0
        if any(s.get('type')=='at' and str(s.get('qq'))==self.bot_id for s in message.get('segments',[])):
            return 'mention',self.mention_reply_probability
        if direct:return 'context',self.context_reply_probability
        if should_reply:return 'participation',self.participation_probability
        return 'none',0.0

    def expired_topics(self, now):
        return [t['id'] for t in self.topics.values() if now-t['last_update'] >= self.idle_seconds]

    def receive(self, message):
        m = deepcopy(message)
        m['truncated'] = bool(m.get('truncated')) or len(m['text']) > self.message_chars
        m['text'] = m['text'][:self.message_chars]
        if m['truncated'] and 'segments' in m:
            m['segments']=[s for s in m['segments'] if s.get('type')!='text']
        if not any(x['id'] == m['id'] for x in self.messages) and m['id'] not in self.decisions:
            self.messages = self._trim(self.messages + [m], self.group_limits, m['at'],'group')
        return deepcopy(m)

    def view(self, now):
        self.messages = self._trim(self.messages, self.group_limits, now,'group')
        visible={m['id'] for m in self.messages}
        for mid in list(self.pending):
            if mid not in visible:
                self.pending.pop(mid)
                self.maintenance.append(dict(at=now,event='pending_expired',message_id=mid,reason='group_window_expired'))
        for topic in self.topics.values():
            topic['messages'] = self._trim(topic['messages'], self.topic_limits, now,topic['id'])
        return deepcopy({'messages': self.messages, 'topics': list(self.topics.values()),
                         'maintenance': self.maintenance, 'queue': self.queue,
                         'decisions': list(self.decisions.values()),'pending_assignments':list(self.pending.values())})
