"""Durable, single-browser QQ to Gemini test bridge."""
import json
import sqlite3
import uuid


class Bridge:
    def __init__(self, path, *, account, group):
        self.account, self.group = str(account), str(group)
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, message_key TEXT UNIQUE, state TEXT, body TEXT)')
        self.db.commit()

    def close(self):
        self.db.close()

    def accept(self, event, now):
        if (event.get('post_type') != 'message' or event.get('message_type') != 'group'
                or str(event.get('self_id')) != self.account
                or str(event.get('group_id')) != self.group
                or str(event.get('user_id')) == self.account):
            return None
        segments = event.get('message')
        if not isinstance(segments, list) or not any(
                s.get('type') == 'at' and str(s.get('data', {}).get('qq')) == self.account
                for s in segments):
            return None
        text = ''.join(str(s.get('data', {}).get('text', '')) for s in segments if s.get('type') == 'text').strip()
        if not text or event.get('message_id') is None:
            return None
        key = f'{self.account}:{self.group}:{event["message_id"]}'
        job = dict(id=uuid.uuid4().hex, key=key, message_id=str(event['message_id']),
                   account=self.account, group=self.group, sender=str(event.get('user_id')),
                   text=text, state='QUEUED', timeline={'qq_at':event.get('time'),'received':now})
        with self.db:
            cur = self.db.execute('INSERT OR IGNORE INTO jobs VALUES(?,?,?,?)',
                                 (job['id'], key, job['state'], json.dumps(job, ensure_ascii=False)))
        return job if cur.rowcount else None

    def get(self, jid):
        r = self.db.execute('SELECT body FROM jobs WHERE id=?', (jid,)).fetchone()
        if r is None:
            raise ValueError('unknown job')
        return json.loads(r[0])

    def save(self, job):
        self.db.execute('UPDATE jobs SET state=?,body=? WHERE id=?',
                        (job['state'], json.dumps(job, ensure_ascii=False), job['id']))

    def claim_browser(self, now):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.db.execute("SELECT 1 FROM jobs WHERE state IN ('SUBMITTING','GENERATING','READY','SENDING','UNKNOWN')").fetchone():
                return None
            r = self.db.execute("SELECT body FROM jobs WHERE state='QUEUED' ORDER BY rowid LIMIT 1").fetchone()
            if not r:
                return None
            job = json.loads(r[0]);job['state'] = 'SUBMITTING';job['timeline']['browser_claimed'] = now
            self.save(job)
            return job

    def unknown(self, jid, reason, now):
        with self.db:
            job = self.get(jid)
            if job['state'] == 'SENT':
                return
            job['state'] = 'UNKNOWN';job['error'] = reason;job['timeline']['stopped'] = now
            self.save(job)

    def expire(self, now, timeout=300):
        rows = self.db.execute("SELECT body FROM jobs WHERE state IN ('SUBMITTING','GENERATING','SENDING')").fetchall()
        for row in rows:
            job = json.loads(row[0]);t = job['timeline']
            start = t.get('send_started', t['browser_claimed'])
            if now - start >= timeout:
                self.unknown(job['id'], 'timeout; manual reconciliation required', now)
    def submitted(self, jid, now):
        with self.db:
            job = self.get(jid)
            if job['state'] != 'SUBMITTING':
                raise ValueError('not submitting')
            job['state'] = 'GENERATING';job['timeline']['submitted'] = now;self.save(job)

    def observe(self, jid, *, request_seen, text, complete, now):
        with self.db:
            job = self.get(jid)
            if job['state'] != 'GENERATING':
                return
            if not request_seen or not complete or not text.strip():
                job.pop('stable', None)
            elif job.get('stable', {}).get('text') != text:
                job['stable'] = dict(text=text, at=now)
            elif now - job['stable']['at'] >= 1:
                job['answer'] = text;job['state'] = 'READY';job['timeline']['answer_ready'] = now
            self.save(job)

    def claim_reply(self, now):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            r = self.db.execute("SELECT body FROM jobs WHERE state='READY' ORDER BY rowid LIMIT 1").fetchone()
            if not r:
                return None
            job = json.loads(r[0]);job['state'] = 'SENDING';job['timeline']['send_started'] = now;self.save(job)
            return job

    def sent(self, jid, *, receipt, now):
        with self.db:
            job = self.get(jid)
            if job['state'] != 'SENDING' or not receipt:
                raise ValueError('missing send claim or receipt')
            job['state'] = 'SENT';job['receipt'] = str(receipt);job['timeline']['sent'] = now
            t = job['timeline'];job['durations'] = dict(
                queue=t['browser_claimed']-t['received'], submit=t['submitted']-t['browser_claimed'],
                generation=t['answer_ready']-t['submitted'], reply_queue=t['send_started']-t['answer_ready'],
                send=t['sent']-t['send_started'], total=t['sent']-t['received'])
            self.save(job)
