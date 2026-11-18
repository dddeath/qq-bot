"""Uniform material-call budget for a pending/committed knowledge task."""
from contextlib import contextmanager
from copy import deepcopy
import json
import sqlite3
import time


def characters(material):
    return len(json.dumps(material,ensure_ascii=False,separators=(',',':')))


def remaining_with_disclosure(remaining, turn_budget):
    return {**remaining, 'turn_disclosure': {
        **turn_budget.remaining(), 'unit': 'estimated_tokens'}}


def exhausted_dimensions(remaining):
    return [key for key in ('total_seconds', 'read_seconds', 'total_calls')
            if remaining.get(key, 1) <= 0] + (
        ['turn_disclosure'] if remaining.get('turn_disclosure', {}).get('remaining', 1) <= 0 else [])


class DecisionReadBudget:
    def __init__(self,path,contract=None):
        self.path=str(path)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS decision_budget (slot INTEGER PRIMARY KEY, limits TEXT, deadline REAL, state TEXT, allowed INTEGER, probe_at REAL, probe_end REAL)')
            if 'probe_end' not in {r[1] for r in db.execute('PRAGMA table_info(decision_budget)')}:
                db.execute('ALTER TABLE decision_budget ADD COLUMN probe_end REAL')
            db.execute('CREATE TABLE IF NOT EXISTS decision_reads (id INTEGER PRIMARY KEY, tool TEXT, purpose TEXT, reason TEXT, stage TEXT, at REAL, characters INTEGER DEFAULT 0, delivered INTEGER DEFAULT 0)')
            if contract is not None:
                db.execute('INSERT OR IGNORE INTO decision_budget VALUES (1,?,?,?,NULL,NULL,NULL)',
                    (json.dumps(contract['limits']),contract['started_at']+contract['limits']['total_seconds'],'pending_decision'))

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=10)
        try:
            with db:yield db
        finally:db.close()

    def _remaining(self,db):
        limits,deadline,state,allowed,probe_at,probe_end=db.execute('SELECT limits,deadline,state,allowed,probe_at,probe_end FROM decision_budget').fetchone()
        limits=json.loads(limits)
        count,probes,chars=db.execute("SELECT count(*),coalesce(sum(stage='pending_decision'),0),coalesce(sum(characters),0) FROM decision_reads").fetchone()
        now=time.time();seconds=max(0,deadline-now)
        read_seconds=max(0,seconds-limits['reserve_seconds'])
        probe_seconds=max(0,limits['max_seconds'] if probe_at is None else probe_at+limits['max_seconds']-(probe_end or now))
        result = dict(total_calls=max(0,limits['total_calls']-count),total_seconds=seconds,
                    read_seconds=read_seconds,probe_calls=max(0,limits['max_calls']-probes),
                    probe_seconds=min(read_seconds,probe_seconds) if state=='pending_decision' else probe_seconds,
                    probe_characters=max(0,limits['max_characters']-chars),probe_started=probe_at is not None)
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='decision_video_polls'").fetchone():
            result['video_polls']={video:{'calls':max(0,cap-n),'seconds':max(0,min(deadline,first+seconds)-now)}
                for video,n,first,cap,seconds in db.execute('SELECT video,count(*),min(at),min(cap),min(seconds) FROM decision_video_polls GROUP BY video')}
        return result

    def remaining(self):
        with self.db() as db:return self._remaining(db)

    def decide(self,state,allowed, *, finish_probe=True):
        with self.db() as db:
            db.execute('UPDATE decision_budget SET state=?,allowed=?,probe_end=CASE WHEN ? THEN coalesce(probe_end,?) ELSE NULL END',
                       (state,int(allowed),int(finish_probe),time.time()))

    def state(self):
        with self.db() as db:return db.execute('SELECT state,allowed FROM decision_budget').fetchone()

    def _access(self,db,tool=None, *, stage=None):
        state,allowed=db.execute('SELECT state,allowed FROM decision_budget').fetchone()
        if stage is not None and state!='closed':
            if stage not in ('pending_decision','decided'):raise ValueError('invalid_read_stage')
            state=stage;allowed=True
        remaining=self._remaining(db)
        reason=None
        if state=='closed':reason='reading_task_closed'
        elif state=='decided' and not allowed:reason='decision_disallows_new_reads'
        elif remaining['total_seconds']<=0:reason='time_budget_exhausted'
        elif remaining['read_seconds']<=0:reason='finalization_required: commit and finish with existing material'
        elif remaining['total_calls']<=0:reason='read_budget_exhausted'
        elif state=='pending_decision':
            from knowledge_decision import LOCAL_READS
            if tool is not None and tool not in LOCAL_READS:reason='decision_probe_local_only'
            elif remaining['probe_calls']<=0:reason='probe_call_budget_exhausted: commit with existing evidence'
            elif remaining['probe_seconds']<=0:reason='probe_time_budget_exhausted: commit with existing evidence'
            elif remaining['probe_characters']<=0:reason='probe_character_budget_exhausted: commit with existing evidence'
        return dict(state=state,can_read=reason is None,reason=reason,remaining=remaining)

    def read_access(self,tool=None, *, stage=None):
        """One rule for tool discovery, task receipts and atomic call admission."""
        with self.db() as db:return self._access(db,tool,stage=stage)

    def reserve(self,tool,purpose,reason,arguments=None, *, stage=None, video_policy=None):
        if purpose not in ('targeted','explore') or not isinstance(reason,str) or not reason.strip():
            raise ValueError('reading_purpose_required')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            access=self._access(db,tool,stage=stage);state=access['state']
            if not access['can_read']:raise ValueError(access['reason'])
            key=None
            if tool=='watch_video' and video_policy is not None:
                from reading_budget import ReadBudget
                key=ReadBudget.video_key(arguments)
                db.execute('CREATE TABLE IF NOT EXISTS decision_video_polls (call_id INTEGER PRIMARY KEY,video TEXT,at REAL,cap INTEGER,seconds REAL)')
                n,first=db.execute('SELECT count(*),min(at) FROM decision_video_polls WHERE video=?',(key,)).fetchone()
                if n>=video_policy['max_calls']:raise ValueError('video_poll_count_exhausted')
                if first is not None and time.time()>=first+video_policy['timeout_seconds']:raise ValueError('video_poll_time_exhausted')
            if state=='pending_decision':
                db.execute('UPDATE decision_budget SET probe_at=coalesce(probe_at,?)',(time.time(),))
            row=db.execute('INSERT INTO decision_reads(tool,purpose,reason,stage,at) VALUES (?,?,?,?,?)',
                           (tool,purpose,reason,state,time.time()))
            if key is not None:
                db.execute('INSERT INTO decision_video_polls VALUES (?,?,?,?,?)',
                    (row.lastrowid,key,time.time(),video_policy['max_calls'],video_policy['timeout_seconds']))
            return row.lastrowid

    def timeout(self, *, stage=None):
        remaining=self.remaining();state,_=self.state()
        if stage is not None and state!='closed':state=stage
        return min(remaining['read_seconds'],remaining['probe_seconds']) if state=='pending_decision' else remaining['read_seconds']

    def disclose(self,index,material, *, deliver=None):
        """Charge only delivered material. Keep JSON, handles and coverage valid."""
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            stage,delivered=db.execute('SELECT stage,delivered FROM decision_reads WHERE id=?',(index,)).fetchone()
            if delivered:raise ValueError('read_already_delivered')
            result=deepcopy(material);partial=False
            original_next=result.get('next_offset') if isinstance(result,dict) else None
            if stage=='pending_decision':
                available=self._remaining(db)['probe_characters']
                if isinstance(result,dict) and characters(result)>available:
                    if isinstance(result.get('items'),list):
                        while result['items'] and characters(result)>available:
                            result['items'].pop();partial=True
                    elif isinstance(result.get('candidates'),list):
                        from reading_result import fit_candidates
                        result = fit_candidates(result, available, characters)
                        partial = True
                    elif isinstance(result.get('content'),str):
                        content=result['content'];offset=result.get('offset',0)
                        lo,hi=0,len(content)
                        while lo<hi:
                            mid=(lo+hi+1)//2
                            result['content']=content[:mid];result['next_offset']=offset+mid
                            if characters(result)<=available:lo=mid
                            else:hi=mid-1
                        result['content']=content[:lo];result['next_offset']=offset+lo
                        partial=lo<len(content)
                    if result is None or characters(result)>available or ('content' in result and not result['content']):
                        result=None;partial=True
                elif result is not None and characters(result)>available:
                    result=None;partial=True
            if deliver is not None:
                projected=deepcopy(result)
                result=deliver(result)
                partial=partial or result!=projected
            size=characters(result) if result is not None else 0
            db.execute('UPDATE decision_reads SET delivered=1,characters=? WHERE id=?',
                       (size if stage=='pending_decision' else 0,index))
        complete=not partial
        next_offset=original_next
        if isinstance(result,dict):
            next_offset=result.get('next_offset')
            if 'next_offset' in result:complete=complete and next_offset is None
            if isinstance(result.get('items'),list):complete=complete and len(result['items'])>=result.get('total',len(result['items']))
            if isinstance(result.get('candidate_coverage'),dict):complete=complete and result['candidate_coverage'].get('complete',True)
        return result,dict(complete=complete,next_offset=next_offset,
                           material_characters=size,disclosure_limited=partial)
