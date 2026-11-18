"""Host-owned, cross-process disclosure accounting for one main conversation turn."""
import sqlite3
import json
import time
from contextlib import closing

CANDIDATE_MENU_PERCENT = 60


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

    def remaining(self):
        with closing(sqlite3.connect(self.path)) as db:
            row=db.execute('SELECT turns.id,maximum,used FROM turns JOIN current ON turns.id=current.id WHERE slot=1').fetchone()
        return dict(turn_id=row[0],limit=row[1],used=row[2],remaining=max(0,row[1]-row[2]))

    def charge(self, turn, cost, *, candidate_menu=False):
        if type(cost) is not int or cost < 0:
            raise ValueError('invalid_disclosure_cost')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT id FROM current WHERE slot=1').fetchone()[0]
            maximum, used = db.execute('SELECT maximum, used FROM turns WHERE id=?', (turn,)).fetchone()
            allowance = (maximum-used)*CANDIDATE_MENU_PERCENT//100 if candidate_menu else maximum-used
            accepted = current == turn and cost <= allowance
            if accepted:
                used += cost
                db.execute('UPDATE turns SET used=? WHERE id=?', (used, turn))
            receipt = dict(accepted=accepted, turn_id=turn, used=used, limit=maximum,
                           remaining=maximum-used, unit='estimated_tokens',
                           reason=None if accepted else 'turn_changed' if current != turn else
                           'candidate_menu_budget_exhausted' if candidate_menu else 'turn_disclosure_budget_exhausted')
            if candidate_menu:
                receipt['candidate_menu_limit'] = allowance
            return receipt

    def deliver(self, turn, tool, arguments, response, elapsed, projector=None, application_call_id=None, *, upstream=None):
        """Keep raw evidence and the exact projected result separately."""
        from reading_result import model_response
        delivered = model_response(response)
        result = delivered.get('result', {})
        success = 'result' in delivered and not result.get('isError')
        material = result.get('structuredContent')
        if material is None:
            material = result.get('content', [])
        def measure(value):
            return (len(json.dumps(value, ensure_ascii=False).encode('utf-8'))+1)//2
        cost = measure(material) if success else 0
        candidate_menu = success and tool == 'retrieve_knowledge_candidates' and isinstance(material,dict) and isinstance(material.get('candidates'),list)
        receipt = self.charge(turn, cost, candidate_menu=candidate_menu)
        if candidate_menu:
            from reading_result import fit_candidates
            # Recheck atomically after projection: another consumer may have
            # used part of this same turn's budget in the meantime.
            while not receipt['accepted'] and receipt['reason']=='candidate_menu_budget_exhausted':
                reduced = fit_candidates(material, receipt['candidate_menu_limit'], measure)
                if reduced is None:
                    break
                material = reduced
                cost = measure(material)
                receipt = self.charge(turn, cost, candidate_menu=True)
                result['structuredContent'] = material
                result['content'] = [{'type':'text','text':json.dumps(material,ensure_ascii=False)}]
            if not receipt['accepted']:
                receipt['candidate_coverage'] = dict(
                    total=material.get('candidate_coverage',{}).get('total',len(material['candidates'])),
                    returned=0, complete=False)
        if success:
            if not receipt['accepted']:
                denied={'error':receipt['reason'],'material':None,
                        'coverage':{'complete':False,'next_offset':None},
                        'knowledge_turn_budget':receipt}
                delivered['result']={'isError':True,'structuredContent':denied,
                    'content':[{'type':'text','text':json.dumps(denied,ensure_ascii=False)}]}
            else:
                delivered['result'].setdefault('content', []).append({'type': 'text',
                    'text': json.dumps({'knowledge_turn_budget': receipt}, ensure_ascii=False)})
        if projector:
            delivered = projector(delivered)
        record = dict(turn_id=turn, tool=tool, arguments=arguments, upstream=response if upstream is None else upstream,
                      delivered=delivered, elapsed_seconds=elapsed, recorded_at=time.time(),
                      budget=receipt, estimated_cost=cost)
        if application_call_id is not None:
            record['application_call_id'] = application_call_id
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO deliveries(turn,body) VALUES (?,?)',
                       (turn, json.dumps(record, ensure_ascii=False)))
        return delivered

    def records(self, turn):
        with closing(sqlite3.connect(self.path)) as db:
            return [json.loads(row[0]) for row in db.execute(
                'SELECT body FROM deliveries WHERE turn=? ORDER BY id', (turn,))]
