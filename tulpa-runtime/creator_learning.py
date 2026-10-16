"""Bounded daily creator collection, separate from group conversation materials."""
import datetime as dt
import json
import sqlite3
import uuid
from pathlib import Path
from contextlib import closing
from daily_learning import TZ, write
from daily_learning import RETENTION

class CreatorCollector:
    def __init__(self, root, config):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.config=config;self.dbpath=self.root/'creator-collection.sqlite3'
        with closing(sqlite3.connect(self.dbpath)) as d, d:
            d.executescript('''CREATE TABLE IF NOT EXISTS days(day TEXT PRIMARY KEY,state TEXT,run TEXT);
CREATE TABLE IF NOT EXISTS account_days(day TEXT,uid TEXT,PRIMARY KEY(day,uid));
CREATE TABLE IF NOT EXISTS seen(uid TEXT,id TEXT,body TEXT,PRIMARY KEY(uid,id));''')
            # Import completed collection receipts created before account-level claims.
            for day,run in d.execute("SELECT day,run FROM days WHERE state='completed'").fetchall():
                receipt=Path(run)/'result.json'
                if receipt.exists():
                    for account in json.loads(receipt.read_text(encoding='utf-8')).get('accounts',[]):
                        d.execute('INSERT OR IGNORE INTO account_days VALUES(?,?)',(day,str(account['uid'])))

    def deliver(self, learning, now):
        with closing(sqlite3.connect(self.dbpath)) as d:
            rows=[json.loads(x[0]) for x in d.execute('SELECT body FROM seen')]
        learning.collect_creators([x for x in rows if now-RETENTION<=x['at']<=now and x['content']['status']=='ok'],now)

    def run(self, accounts, provider, now):
        day=dt.datetime.fromtimestamp(now,TZ).strftime('%Y-%m-%d')
        run=self.root/'runs'/(dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+uuid.uuid4().hex[:8])
        with closing(sqlite3.connect(self.dbpath)) as d, d:
            d.execute('BEGIN IMMEDIATE')
            previous=d.execute('SELECT state,run FROM days WHERE day=?',(day,)).fetchone()
            claimed={x[0] for x in d.execute('SELECT uid FROM account_days WHERE day=?',(day,))}
            accounts=[a for a in accounts if a.get('enabled') and a.get('uid') and str(a['uid']) not in claimed]
            if previous and (previous[0]=='started' or not accounts):
                return dict(state='already_'+previous[0],run=previous[1],materials=[])
            run.mkdir(parents=True);d.execute('INSERT OR REPLACE INTO days VALUES(?,?,?)',(day,'started',str(run)))
            for account in accounts:d.execute('INSERT OR IGNORE INTO account_days VALUES(?,?)',(day,str(account['uid'])))
        materials=[];records=[];reports=[]
        limit=int(self.config.get('per_account_limit',2))
        cutoff=now-float(self.config.get('lookback_days',7))*86400
        for account in accounts:
            if not account.get('enabled') or not account.get('uid'):continue
            candidates={};uid=str(account['uid']);report={'uid':uid,'sections':[]};reports.append(report)
            for section in ('videos','dynamics'):
                cursor=None
                for _ in range(int(self.config.get('max_pages',1))):
                    try:page=provider.catalog(account,section,cursor)
                    except Exception as exc:
                        report['sections'].append(dict(section=section,status='error',error=str(exc)))
                        cursor=None;break
                    for item in page['items']:
                        if cutoff<=item['published_at']<=now or (hasattr(provider,'parts') and item['id'].startswith('v:')):candidates[item['id']]=item
                    cursor=page.get('next_cursor')
                    if not cursor:break
                if not any(x['section']==section for x in report['sections']):
                    report['sections'].append(dict(section=section,status='truncated' if cursor else 'complete'))
            if hasattr(provider,'parts'):
                from creator_parts import expand_parts
                candidates,report['part_scan']=expand_parts(self.dbpath,uid,candidates,provider,self.config,now,cutoff)
            with closing(sqlite3.connect(self.dbpath)) as d:
                seen={x[0] for x in d.execute('SELECT id FROM seen WHERE uid=?',(uid,))}
                for body, in d.execute('SELECT body FROM seen WHERE uid=?',(uid,)):
                    previous=json.loads(body);content=previous.get('content',{});meta=content.get('metadata',{})
                    if content.get('scope') not in ('part_1_subtitles','selected_part_subtitles'):continue
                    page=content.get('page',1)
                    part=next((p for p in meta.get('pages',[]) if p.get('page')==page),None)
                    if part and meta.get('bvid') and part.get('cid'):
                        seen.add(f"v:{meta['bvid']}:cid:{part['cid']}")
            selected=sorted((v for k,v in candidates.items() if k not in seen),key=lambda x:(-x['published_at'],x['id']))[:limit]
            for item in selected:
                try:result=provider.read(item)
                except Exception as exc:result=dict(status='read_failed',error=str(exc))
                material=dict(id='bilibili:'+uid+':'+item['id'],content_id=item['id'],at=now,
                              creator=account,published_at=item['published_at'],**{'content':result})
                with closing(sqlite3.connect(self.dbpath)) as d, d:
                    d.execute('INSERT OR IGNORE INTO seen VALUES(?,?,?)',(uid,item['id'],json.dumps(material,ensure_ascii=False)))
                records.append(material)
                if result['status']=='ok':materials.append(material)
        write(run/'records.json',records)
        result=dict(state='completed',run=str(run),materials=materials,records=records,accounts=reports)
        write(run/'result.json',result)
        with closing(sqlite3.connect(self.dbpath)) as d, d:d.execute('UPDATE days SET state=? WHERE day=?',('completed',day))
        return result
