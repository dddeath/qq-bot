"""Per-conversation activation gate; original inbox remains the source of messages."""
import math
import re
import json

DEFAULTS = dict(enabled=False, threshold=8, active_idle_timeout_seconds=900,
                buffer_ttl_seconds=3600, weights=dict(human=1, video_share=5, bot=.5))

class ActivationGate:
    def __init__(self, config, *, account):
        self.config = {**DEFAULTS, **config}
        self.weights = {**DEFAULTS['weights'], **config.get('weights', {})}
        for name in ('threshold', 'active_idle_timeout_seconds', 'buffer_ttl_seconds'):
            value = self.config[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError('invalid activation '+name)
        for value in self.weights.values():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('invalid activation weight')
        self.account = str(account)
        self.bots = {str(x) for x in config.get('bot_ids', [])}
        self.immediate = {'mention_self': True, 'reply_to_self': True, **config.get('immediate', {})}
        self.active = False
        self.last_arrival = None
        self.seen_through = -1

    def category(self, message):
        segments = message.get('segments', [])
        video = any(s.get('type') == 'video' for s in segments)
        text = json.dumps(segments, ensure_ascii=False) + str(message.get('content', ''))
        video = video or bool(re.search(r'(?:bilibili\.com/video/|b23\.tv/|youtu\.be/|youtube\.com/watch\?|BV[0-9A-Za-z]{10})', text))
        return 'video_share' if video else 'bot' if str(message.get('sender_id')) in self.bots else 'human'

    def directed(self, message):
        for s in message.get('segments', []):
            if self.immediate['mention_self'] and s.get('type') == 'at' and str(s.get('qq')) == self.account:
                return 'mention'
            if self.immediate['reply_to_self'] and s.get('type') == 'reply' and str(s.get('sender_id')) == self.account:
                return 'reply'
        if self.immediate['reply_to_self'] and str(message.get('reply_sender_id')) == self.account:
            return 'reply'
        return None

    def evaluate(self, messages, now):
        fresh = [m for m in messages if m['id'] > self.seen_through and str(m.get('sender_id')) != self.account and not m.get('is_self')]
        for m in fresh:
            at = m['received_at']
            if self.last_arrival is not None and at - self.last_arrival >= self.config['active_idle_timeout_seconds']:
                self.active = False
            self.last_arrival = max(at, self.last_arrival or at)
        if messages:
            self.seen_through = max(self.seen_through, max(m['id'] for m in messages))
        if self.last_arrival is not None and now-self.last_arrival >= self.config['active_idle_timeout_seconds']:
            self.active = False
        valid = [m for m in messages if now-m['received_at'] < self.config['buffer_ttl_seconds'] and str(m.get('sender_id')) != self.account and not m.get('is_self')]
        score = sum(self.weights[self.category(m)] for m in valid if not m.get('_screened',False))
        directed = next((self.directed(m) for m in valid if not m.get('_screened',False) and self.directed(m)), None)
        reason = 'disabled' if not self.config['enabled'] else directed or ('active' if self.active else 'threshold' if score >= self.config['threshold'] else 'buffering')
        activated = not self.active and reason in ('mention', 'reply', 'threshold')
        if activated: self.active = True
        return dict(deliver=bool(valid) and reason!='buffering', reason=reason, score=score,
                    activated=activated, expired_ids=[m['id'] for m in messages if now-m['received_at'] >= self.config['buffer_ttl_seconds']], message_ids=[m['id'] for m in valid], active=self.active)

class ActivationRouter:
    """Bot settings, independent group state. Caller retains original inbox rows."""
    def __init__(self, bots):
        self.bots = bots
        self.gates = {}
        self.decisions = {}

    def select(self, conversation, messages, now):
        account = conversation.split(':')[0]
        config = self.bots.get(account, {})
        if not config.get('enabled', False):
            return messages
        gate = self.gates.setdefault(conversation, ActivationGate(config, account=account))
        decision = gate.evaluate(messages, now)
        self.decisions[conversation] = decision
        ids = set(decision['message_ids']) if decision['deliver'] else set()
        return [m for m in messages if m['id'] in ids]


def select_pending(service, session, pending):
    """Tulpa hook before offered/delivered and batch creation; no cursor mutation."""
    import os
    import time
    from pathlib import Path
    path = os.environ.get('QQ_BOT_ACTIVATION_CONFIG')
    if not path:
        return pending
    if not hasattr(service, '_activation_router'):
        service._activation_router = ActivationRouter(json.loads(Path(path).read_text(encoding='utf-8-sig'))['bots'])
    router = service._activation_router
    cid = session['conversation_id']
    if not router.bots.get(cid.split(':')[0], {}).get('enabled', False):
        return pending
    with service.access.connect() as db:
        # Activation sees all retained pending rows, not just the first display page.
        rows = db.execute('SELECT * FROM chat_inbox WHERE session_id=? AND id>? ORDER BY id',
                          (session['id'],session['cursor'])).fetchall()
        messages = []
        for row in rows:
            m = dict(json.loads(row['payload']),id=row['id'],received_at=row['at'])
            for segment in m.get('segments', []):
                if segment.get('type') == 'reply' and not segment.get('sender_id'):
                    target = str(segment.get('onebot_message_id',segment.get('id',segment.get('message_id',''))))
                    found = db.execute('SELECT payload FROM chat_inbox WHERE session_id=? AND message_id=?',
                                       (session['id'],target)).fetchone()
                    if found:
                        m['reply_sender_id'] = json.loads(found[0]).get('sender_id')
            messages.append(m)
    now=time.time()
    screened=0
    if hasattr(service,'_screening_service') and cid in service._screening_service.queues:
        screened=service._screening_service.queues[cid].state['screened']
    gate_messages=[dict(m,_screened=m['id']<=screened) for m in messages]
    gate_ids={m['id'] for m in router.select(cid,gate_messages,now)}
    allowed=[m for m in messages if m['id'] in gate_ids]
    if allowed and router.bots[cid.split(':')[0]].get('screening',{}).get('enabled',False):
        if not hasattr(service,'_screening_service'):
            from screening_service import ScreeningService
            service._screening_service=ScreeningService(json.loads(Path(path).read_text(encoding='utf-8-sig')))
        with service.access.connect() as db:
            recent=db.execute('SELECT id,at,payload FROM chat_inbox WHERE session_id=? ORDER BY id DESC LIMIT 40',(session['id'],)).fetchall()
        history=[dict(json.loads(r['payload']),id=r['id'],received_at=r['at']) for r in reversed(recent)]
        allowed=service._screening_service.select(cid,allowed,history,now)
    selected = {m['id'] for m in allowed}
    return [row for row in rows if row['id'] in selected]


def export_config(database, bot_id, version):
    """Export the explicitly selected Bot revision, without changing live bindings."""
    import sqlite3
    from pathlib import Path
    from contextlib import closing
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        row=db.execute("SELECT body FROM configurations WHERE kind='bot' AND id=? AND version=?",(bot_id,version)).fetchone()
    if row is None: raise ValueError('unknown bot revision')
    bot=json.loads(row[0]);config=dict(bot.get('activation',{'enabled':False}))
    config.update(batching=bot.get('batching',{}),screening=bot.get('screening',{'enabled':False}))
    ActivationGate(config,account=bot['account_id'])
    return dict(bot_ref=dict(kind='bot',id=bot_id,version=version),bots={str(bot['account_id']):config})

if __name__ == '__main__':
    import argparse
    from pathlib import Path
    p=argparse.ArgumentParser()
    p.add_argument('--database',type=Path,required=True);p.add_argument('--bot-id',required=True)
    p.add_argument('--version',type=int,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    data=export_config(a.database,a.bot_id,a.version)
    with a.output.open('x',encoding='utf8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
