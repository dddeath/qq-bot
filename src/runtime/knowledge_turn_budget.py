"""Host-owned, cross-process disclosure accounting for one main conversation turn."""
import sqlite3
import json
import time
from copy import deepcopy
from contextlib import closing


class TurnBudget:
    def __init__(self, path):
        self.path = str(path)

    def begin(self, turn, limit=2500):
        if not turn or type(limit) is not int or limit < 1:
            raise ValueError('invalid_turn_budget')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS turns (id TEXT PRIMARY KEY, maximum INTEGER, used INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS current (slot INTEGER PRIMARY KEY, id TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS deliveries (id INTEGER PRIMARY KEY, turn TEXT, body TEXT)')
            db.execute('INSERT INTO turns VALUES (?, ?, 0)', (turn, limit))
            db.execute('INSERT OR REPLACE INTO current VALUES (1, ?)', (turn,))

    def current(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT id FROM current WHERE slot=1').fetchone()[0]

    def charge(self, turn, cost):
        if type(cost) is not int or cost < 0:
            raise ValueError('invalid_disclosure_cost')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT id FROM current WHERE slot=1').fetchone()[0]
            maximum, used = db.execute('SELECT maximum, used FROM turns WHERE id=?', (turn,)).fetchone()
            accepted = current == turn and used + cost <= maximum
            if accepted:
                used += cost
                db.execute('UPDATE turns SET used=? WHERE id=?', (used, turn))
            return dict(accepted=accepted, turn_id=turn, used=used, limit=maximum,
                        remaining=maximum-used, unit='estimated_tokens',
                        reason=None if accepted else 'turn_changed' if current != turn else 'turn_disclosure_budget_exhausted')

    def deliver(self, turn, tool, arguments, response, elapsed, projector=None):
        """Keep raw evidence and the exact projected result separately."""
        delivered = deepcopy(response)
        result = delivered.get('result', {})
        success = 'result' in delivered and not result.get('isError')
        material = result.get('structuredContent')
        if material is None:
            material = result.get('content', [])
        cost = (len(json.dumps(material, ensure_ascii=False).encode('utf-8'))+1)//2 if success else 0
        receipt = self.charge(turn, cost)
        if success:
            if not receipt['accepted']:
                delivered['result'] = {'isError': True, 'content': []}
            delivered['result'].setdefault('content', []).append({'type': 'text',
                'text': json.dumps({'knowledge_turn_budget': receipt}, ensure_ascii=False)})
        if projector:
            delivered = projector(delivered)
        record = dict(turn_id=turn, tool=tool, arguments=arguments, upstream=response,
                      delivered=delivered, elapsed_seconds=elapsed, recorded_at=time.time(),
                      budget=receipt, estimated_cost=cost)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO deliveries(turn,body) VALUES (?,?)',
                       (turn, json.dumps(record, ensure_ascii=False)))
        return delivered

    def records(self, turn):
        with closing(sqlite3.connect(self.path)) as db:
            return [json.loads(row[0]) for row in db.execute(
                'SELECT body FROM deliveries WHERE turn=? ORDER BY id', (turn,))]
