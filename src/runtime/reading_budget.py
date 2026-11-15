"""Task read reservations, deadlines and overview accounting."""
from contextlib import contextmanager
import json
import math
import re
import sqlite3
import time

OVERVIEW = {'get_video_metadata', 'get_video_chapters', 'get_video_context', 'search_bilibili_videos', 'web_search', 'get_knowledge_index', 'search_knowledge'}
OVERVIEW |= {'read_rss_subscription', 'get_knowledge_tag_index', 'search_knowledge_tags', 'find_knowledge_entries', 'retrieve_knowledge_candidates'}


class ReadBudget:
    """Shared budget ledger for native web events and the read-only MCP gateway."""
    def __init__(self,path,units=2,ratio=.5,seconds=60,policy=None, *, now=None):
        self.path=str(path)
        self._now = time.time if now is None else now
        with self.db() as db:
            db.execute('create table if not exists settings (id integer primary key, units integer, explore integer, deadline real)')
            db.execute('create table if not exists calls (id integer primary key, tool text, purpose text, reason text, overview integer, at real)')
            db.execute('create table if not exists policy (id integer primary key, data text)')
            db.execute('create table if not exists video_polls (call_id integer primary key, video text, at real)')
            db.execute('insert or ignore into settings values (1,?,?,?)',(units,math.ceil(units*ratio),self._now()+seconds))
            if policy is not None:
                db.execute('insert or ignore into policy values (1,?)',(json.dumps(policy),))
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=10)
        try:
            with db:yield db
        finally:db.close()
    @staticmethod
    def video_key(arguments):
        from urllib.parse import parse_qs, urlsplit
        video=(arguments or {}).get('video')
        if not isinstance(video,str) or not video.strip():raise ValueError('video_required')
        match=re.search(r'BV[0-9A-Za-z]{10}',video)
        if not match:return video.strip()
        page=parse_qs(urlsplit(video).query).get('p',['1'])[0]
        return match.group()+':p'+str(int(page))

    def remaining(self):
        with self.db() as db:
            units,explore,deadline=db.execute('select units,explore,deadline from settings').fetchone()
            rows=db.execute('select purpose,overview from calls where id not in (select call_id from video_polls)').fetchall()
            saved=db.execute('select data from policy where id=1').fetchone()
            policy=json.loads(saved[0]) if saved else {}
            polls=db.execute('select video,count(*),min(at) from video_polls group by video').fetchall()
        now=self._now();reads=max(0,units-sum(not r[1] for r in rows))
        return dict(overview_units=max(0,3-sum(r[1] for r in rows)),read_units=reads,
            targeted_units=max(0,min(reads,policy.get('max_targeted_units',units)-sum(r[0]=='targeted' and not r[1] for r in rows))),
            exploration_units=max(0,explore-sum(r[0]=='explore' for r in rows)),seconds=max(0,deadline-now),
            read_seconds=max(0,deadline-now-policy.get('finalization_reserve_seconds',0)),
            finalization_reserve_seconds=policy.get('finalization_reserve_seconds',0),
            video_polls={video:{'calls':max(0,policy['video_poll_max_calls']-count),
                'seconds':max(0,min(deadline,first+policy['video_poll_timeout_seconds'])-now)}
                for video,count,first in polls})

    def reserve(self,tool,purpose,reason,arguments=None):
        if purpose not in ('targeted','explore') or not isinstance(reason,str) or not reason.strip():raise ValueError('reading_purpose_required')
        with self.db() as db:
            db.execute('begin immediate')
            units,explore,deadline=db.execute('select units,explore,deadline from settings').fetchone()
            rows=db.execute('select purpose,overview from calls where id not in (select call_id from video_polls)').fetchall()
            saved=db.execute('select data from policy where id=1').fetchone()
            policy=json.loads(saved[0]) if saved else {}
            if self._now()>=deadline:raise ValueError('time_budget_exhausted')
            if self._now()>=deadline-policy.get('finalization_reserve_seconds',0):
                raise ValueError('finalization_required: stop reading and call finish_reading_task, then output the final report')
            overview=tool in OVERVIEW and sum(x[1] for x in rows)<3
            if not rows and not overview:raise ValueError('overview_required')
            if tool=='watch_video' and 'video_poll_max_calls' in policy:
                key=self.video_key(arguments)
                count,first=db.execute('select count(*),min(at) from video_polls where video=?',(key,)).fetchone()
                if count>=policy['video_poll_max_calls']:raise ValueError('video_poll_count_exhausted')
                if first is not None and self._now()>=first+policy['video_poll_timeout_seconds']:
                    raise ValueError('video_poll_time_exhausted')
                stamp=self._now()
                cur=db.execute('insert into calls(tool,purpose,reason,overview,at) values(?,?,?,?,?)',(tool,purpose,reason,0,stamp))
                db.execute('insert into video_polls values(?,?,?)',(cur.lastrowid,key,stamp))
                return cur.lastrowid
            used=sum(not x[1] for x in rows)
            if not overview and used>=units:raise ValueError('read_budget_exhausted')
            if (not overview and purpose=='targeted'
                    and sum(x[0]=='targeted' and not x[1] for x in rows)>=policy.get('max_targeted_units',units)):
                raise ValueError('targeted_budget_exhausted')
            if purpose=='explore' and sum(x[0]=='explore' for x in rows)>=explore:raise ValueError('exploration_budget_exhausted')
            cur=db.execute('insert into calls(tool,purpose,reason,overview,at) values(?,?,?,?,?)',(tool,purpose,reason,int(overview),self._now()))
            return cur.lastrowid


def reading_budget_exhausted(remaining):
    return (remaining['seconds']<=0 or
            (remaining.get('overview_units',0)==0 and
             (remaining['read_units']==0 or (remaining.get('targeted_units',remaining['read_units'])==0 and remaining['exploration_units']==0))))
