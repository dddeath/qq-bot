"""Daily group learning: retained inputs and clean role-facing publication."""
import datetime as dt
import json
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from contextlib import contextmanager
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'sessions'))
from run_records import recorded
TZ=dt.timezone(dt.timedelta(hours=8))
RETENTION=7*86400
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)
class Learning:
    def __init__(self,root,account,group,*,session_id=None,knowledge_publication=None):
        self.root=Path(root)/'groups'/str(account)/str(group);self.root.mkdir(parents=True,exist_ok=True)
        self.account=str(account);self.group=str(group)
        self.session_id=session_id;self.knowledge_publication=knowledge_publication
        self.dbpath=self.root/'learning.sqlite3'
        with self.db() as d:
            d.executescript('''CREATE TABLE IF NOT EXISTS materials(kind TEXT,id TEXT,at REAL,body TEXT,PRIMARY KEY(kind,id));
CREATE TABLE IF NOT EXISTS published(kind TEXT,id TEXT,body TEXT,PRIMARY KEY(kind,id));
CREATE TABLE IF NOT EXISTS days(day TEXT PRIMARY KEY,state TEXT,run TEXT,cutoff REAL);
CREATE TABLE IF NOT EXISTS applied(run TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS publication_applied(run TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);''')
    @contextmanager
    def db(self):
        d=sqlite3.connect(self.dbpath,timeout=20)
        try:
            with d:yield d
        finally:d.close()
    def collect_creators(self,items,now=None):
        self.collect([],[],now,creators=items)
    def collect(self,messages,searches,now=None,*,creators=()):
        now=time.time() if now is None else now
        with self.db() as d:
            for kind,items in [('messages',messages),('search-completions',searches),('creator-content',creators)]:
                for item in items:
                    if now-RETENTION<=item['at']<=now and not item.get('is_self') and not item.get('synthetic'):
                        if item.get('account',self.account)!=self.account or item.get('group',self.group)!=self.group:continue
                        d.execute('INSERT OR IGNORE INTO materials VALUES(?,?,?,?)',(kind,str(item['id']),item['at'],json.dumps(item,ensure_ascii=False)))
            d.execute('DELETE FROM materials WHERE at<?',(now-RETENTION,))
            for kind in ['messages','search-completions','creator-content']:
                folder=self.root/'inbox'/kind;folder.mkdir(parents=True,exist_ok=True)
                byday={}
                for at,body in d.execute('SELECT at,body FROM materials WHERE kind=? ORDER BY at,id',(kind,)):
                    day=dt.datetime.fromtimestamp(at,TZ).strftime('%Y-%m-%d');byday.setdefault(day,[]).append(body)
                for day,rows in byday.items():
                    tmp=folder/(day+'.tmp');tmp.write_text('\n'.join(rows)+'\n',encoding='utf-8');tmp.replace(folder/(day+'.jsonl'))
                for p in folder.glob('*.jsonl'):
                    if p.stem not in byday:p.unlink()
        for manifest in (self.root/'runs').glob('*/manifest.json'):
            if json.loads(manifest.read_text())['cutoff']>=now-RETENTION:continue
            run=manifest.parent
            for name in ('input/messages.jsonl','input/search-completions.jsonl','input/creator-content.jsonl','input/messages.json','input/search-completions.json','input/video-reading.json','execution.jsonl'):
                path=run/name
                if path.resolve().is_relative_to(self.root.resolve()) and path.is_file():path.unlink()
            video=run/'input/video'
            if video.resolve().is_relative_to(self.root.resolve()) and video.is_dir() and not video.is_symlink():
                shutil.rmtree(video)
    def record_search(self,message_id,gap,findings,sources,now=None):
        now=time.time() if now is None else now
        with self.db() as d:
            if not d.execute("SELECT 1 FROM materials WHERE kind='messages' AND id=?",(str(message_id),)).fetchone():raise ValueError('message_not_in_current_group')
        item=dict(id=uuid.uuid4().hex,at=now,message_id=str(message_id),gap=gap,findings=findings,sources=sources)
        self.collect([], [item],now);return {'recorded':True,'id':item['id']}
    def prepare(self,now=None):
        now=time.time() if now is None else now
        with self.db() as d:
            cursor=d.execute("SELECT value FROM settings WHERE key='cursor'").fetchone();cursor=float(cursor[0]) if cursor else 0
            rows=d.execute('SELECT kind,body FROM materials WHERE at>=? AND at>? AND at<=? ORDER BY at,id',(now-RETENTION,cursor,now)).fetchall()
            ids={json.loads(body)['id'] for kind,body in rows if kind=='messages'}
            for kind,body in list(rows):
                if kind!='search-completions':continue
                ref=json.loads(body)['message_id']
                if ref in ids:continue
                original=d.execute("SELECT body FROM materials WHERE kind='messages' AND id=? AND at>=?",(ref,now-RETENTION)).fetchone()
                if original:rows.append(('messages',original[0]));ids.add(ref)
        return dict(messages=[json.loads(v) for k,v in rows if k=='messages'],searches=[json.loads(v) for k,v in rows if k=='search-completions'],creators=[json.loads(v) for k,v in rows if k=='creator-content'],cutoff=now)
    def read(self,query='',limit=12):
        result={'expressions':[],'meanings':[]}
        with self.db() as d:
            for kind,body in d.execute('SELECT kind,body FROM published ORDER BY kind,id'):
                value=json.loads(body)
                if not query or query.casefold() in body.casefold():result[kind].append(value)
        return {k:v[:max(1,min(limit,100))] for k,v in result.items()}
    def finish_publication_retry(self,run,publication):
        if publication.get('status')!='published':return
        run=Path(run)
        manifest=json.loads((run/'manifest.json').read_text(encoding='utf-8'))
        admission=json.loads((run/'review/tag-admission.json').read_text(encoding='utf-8'))
        clean={'expressions':[],'meanings':[]}
        for record in admission['records']:
            if record['status']=='approved':clean[record['candidate']['kind']].append(record['value'])
        for kind,values in clean.items():write(run/'published'/(kind+'.json'),values)
        with self.db() as db:
            if not db.execute('SELECT 1 FROM publication_applied WHERE run=?',(str(run),)).fetchone():
                for kind,values in clean.items():
                    for value in values:db.execute('INSERT OR REPLACE INTO published VALUES(?,?,?)',(kind,value['id'],json.dumps(value,ensure_ascii=False)))
                db.execute('INSERT INTO publication_applied VALUES(?)',(str(run),))
            db.execute('INSERT OR IGNORE INTO applied VALUES(?)',(str(run),))
            cursor=db.execute("SELECT value FROM settings WHERE key='cursor'").fetchone()
            cutoff=max(float(cursor[0]) if cursor else 0,manifest['cutoff'])
            db.execute("INSERT OR REPLACE INTO settings VALUES('cursor',?)",(str(cutoff),))
            db.execute("UPDATE days SET state='completed' WHERE run=?",(str(run),))
        summary={name:sum(r['status']==state for r in admission['records']) for name,state in
                 [('approved','approved'),('pending','pending'),('discarded','discarded')]}
        apply=dict(state='completed',run=str(run),accepted={k:len(v) for k,v in clean.items()},
                   tag_admission={**summary,'evidence':str(run/'review/tag-admission.json')},
                   knowledge_publication=publication)
        write(run/'apply.json',apply)
        validation=json.loads((run/'review/validation.json').read_text(encoding='utf-8'))
        validation['accepted']=apply['accepted'];write(run/'review/validation.json',validation)
        receipt=json.loads((run/'run-receipt.json').read_text(encoding='utf-8'))
        receipt['result']=apply
        receipt['publication_recovery']=dict(status='completed',at=dt.datetime.now(dt.timezone.utc).isoformat())
        write(run/'run-receipt.json',receipt)
        (run/'summary.md').write_text('# 每日学习结果\n\n'+json.dumps(apply,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    def recover_publications(self,now):
        if not self.knowledge_publication:return
        for manifest in sorted((self.root/'runs').glob('*/manifest.json')):
            at=json.loads(manifest.read_text())['cutoff'];run=manifest.parent
            if not now-RETENTION<=at<=now:continue
            if not (run/'review/tag-admission.json').exists():continue
            publication=run/'tag-publication.json'
            if not publication.exists():continue
            publication=json.loads(publication.read_text())
            if publication.get('status')!='published':continue
            with self.db() as db:
                applied=db.execute('SELECT 1 FROM publication_applied WHERE run=?',(str(run),)).fetchone()
            receipt=run/'run-receipt.json';apply=run/'apply.json'
            complete=(applied and apply.exists() and receipt.exists()
                and json.loads(apply.read_text()).get('state')=='completed'
                and json.loads(receipt.read_text()).get('result',{}).get('knowledge_publication',{}).get('status')=='published')
            if not complete:self.finish_publication_retry(run,publication)
    def run(self,model,now=None,*,retry_failed=False,retry_publication=False,tag_sessions=None):
        now=time.time() if now is None else now;day=dt.datetime.fromtimestamp(now,TZ).strftime('%Y-%m-%d')
        self.recover_publications(now)
        run=self.root/'runs'/(dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+uuid.uuid4().hex[:8])
        with self.db() as d:
            d.execute('BEGIN IMMEDIATE')
            previous=d.execute('SELECT state,run FROM days WHERE day=?',(day,)).fetchone()
            reuse=previous and not (retry_failed and previous[0]=='failed')
            if not reuse:
                run.mkdir(parents=True);d.execute('INSERT OR REPLACE INTO days VALUES(?,?,?,?)',(day,'started',str(run),now))
        if reuse:
            result=dict(state='already_'+previous[0],run=previous[1])
            if previous[0]=='completed' and self.knowledge_publication and retry_publication:
                from learning_tag_publication import publish_pending
                result['knowledge_publication']=publish_pending(self,self.knowledge_publication,Path(previous[1]))
                self.finish_publication_retry(previous[1],result['knowledge_publication'])
            return result
        with recorded(run, purpose='learning', harness='codex', session_id=self.session_id, configuration={'model':'gpt-6-astra','effort':'medium','service_tier':'default','release':str(Path(__file__).resolve().parents[2])}) as execution:
            batch=self.prepare(now)
            write(run/'manifest.json',dict(day=day,account=self.account,group=self.group,cutoff=now,model='gpt-6-astra',effort='medium',service_tier='default',retry_of=previous[1] if previous else None))
            for name,key in [('messages','messages'),('search-completions','searches'),('creator-content','creators')]:
                path=run/'input'/(name+'.jsonl');path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in batch[key]),encoding='utf-8')
            write(run/'input/existing-learning.json',self.read(limit=100))
            try:
                output=model(batch,run) if batch['messages'] or batch['searches'] or batch['creators'] else dict(expressions=[],meanings=[])
                write(run/'review/candidates.json',output)
                sources={str(x['id']):x for x in batch['messages']+batch['searches']+batch['creators']}
                clean={'expressions':[],'meanings':[]};rejected=[]
                drafts={'expressions':[],'meanings':[]}
                for kind in clean:
                    seen=set()
                    for item in output.get(kind,[]):
                        ids=item.get('source_ids',[])
                        if not ids or any(str(i) not in sources for i in ids):
                            rejected.append(dict(kind=kind,item=item,reason='unknown_source'));continue
                        keys=('situation','surface_form','style') if kind=='expressions' else ('term','meaning','usage','conditions','kind')
                        if any(not isinstance(item.get(k),str) for k in keys):raise ValueError('invalid_publication_fields')
                        if kind=='expressions':
                            quote=item.get('evidence_quote','')
                            if not quote or not any(quote in sources[str(i)].get('text','') for i in ids):
                                rejected.append(dict(kind=kind,item=item,reason='quote_missing'));continue
                        elif item['kind'] not in ('group','community','fact'):raise ValueError('invalid_meaning_kind')
                        value={k:item[k] for k in keys}
                        identity=value.get('term',value.get('surface_form',''))
                        value['id']=uuid.uuid5(uuid.NAMESPACE_URL,self.account+'/'+self.group+'/'+kind+'/'+identity).hex
                        if value['id'] in seen:
                            rejected.append(dict(kind=kind,item=item,reason='duplicate_identity'));continue
                        seen.add(value['id'])
                        clean[kind].append(value)
                        drafts[kind].append(item)
                referenced={str(i) for kind in clean for item in output.get(kind,[]) for i in item.get('source_ids',[]) if str(i) in sources}
                write(run/'review/evidence.json',{i:sources[i] for i in referenced})
                write(run/'review/assessments.json',{'rejected':rejected})
                write(run/'review/validation.json',{'valid':True,'accepted':{k:len(v) for k,v in clean.items()}})
                from learning_tag_admission import admit
                clean, admission = admit(self, clean, drafts, sources, run, sessions=tag_sessions)
                publication=None
                if self.knowledge_publication:
                    from learning_tag_publication import publish_pending
                    publication=publish_pending(self,self.knowledge_publication,run)
                    if publication.get('status')!='published':
                        clean={'expressions':[],'meanings':[]}
                write(run/'review/validation.json',{'valid':True,'accepted':{k:len(v) for k,v in clean.items()},'tag_admission':admission})
                for kind,values in clean.items():write(run/'published'/(kind+'.json'),values)
                with self.db() as d:
                    for kind,values in clean.items():
                        for value in values:d.execute('INSERT OR REPLACE INTO published VALUES(?,?,?)',(kind,value['id'],json.dumps(value,ensure_ascii=False)))
                    if publication and publication.get('status')=='published':
                        d.execute('INSERT INTO publication_applied VALUES(?)',(str(run),))
                    d.execute('INSERT INTO applied VALUES(?)',(str(run),))
                    d.execute("INSERT OR REPLACE INTO settings VALUES('cursor',?)",(str(now),))
                    d.execute("UPDATE days SET state='completed' WHERE day=?",(day,))
                receipt=dict(state='completed',run=str(run),accepted={k:len(v) for k,v in clean.items()},tag_admission=admission)
                if publication is not None:receipt['knowledge_publication']=publication
                write(run/'apply.json',receipt);write(self.root/'state.json',dict(last_completed_day=day,last_run=str(run),cursor=now))
                (run/'summary.md').write_text('# 每日学习结果\n\n'+json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                execution['result']=receipt
                return receipt
            except Exception as exc:
                with self.db() as d:d.execute("UPDATE days SET state='failed' WHERE day=?",(day,))
                write(run/'apply.json',dict(state='failed',error=str(exc)));raise
