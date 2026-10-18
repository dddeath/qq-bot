"""Async pre-delivery screening; private decisions never enter Tulpa payloads."""
import concurrent.futures
import json
import sys
import time
from pathlib import Path
from screening import ScreeningQueue, build_input
from topic_codex import CodexProvider

class ScreeningService:
    def __init__(self, config):
        self.config=config;self.queues={};self.jobs={};self.batch_ids={}
        self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=2,thread_name_prefix='screening')
    def select(self,cid,messages,history,now):
        account,_,group=cid.split(':');settings=self.config['bots'][account]
        limits=settings.get('batching',{})
        if cid not in self.queues:
            q=ScreeningQueue(self.config['screening_runtime']['state_root'],account=account,group=group,
                max_messages=limits.get('max_messages',10),max_wait_seconds=limits.get('max_wait_seconds',30),ttl_seconds=settings.get('buffer_ttl_seconds',3600))
            q.recover_pending();self.queues[cid]=q
        q=self.queues[cid]
        job=self.jobs.get(cid)
        if job and job.done():
            try:result=job.result()
            except Exception as exc:result={'batch_id':self.batch_ids[cid],'result':{'decision':'wake','reason_code':'screening_error','reason':type(exc).__name__}}
            q.complete(result['batch_id'],result['result'],now);del self.jobs[cid]
        decision=q.prepare(messages,now)
        if decision['kind']=='deliver':
            ids=set(decision['message_ids']);return [m for m in messages if m['id'] in ids]
        if decision['kind']=='screen':
            self.batch_ids[cid]=decision['batch_id']
            self.jobs[cid]=self.pool.submit(self.run,cid,decision,history)
        return []
    def run(self,cid,batch,history):
        account,_,group=cid.split(':');runtime=self.config['screening_runtime'];profiles={}
        # Paths explicitly scoped by account and group; no global member scan.
        refs=runtime.get('profile_files',{}).get(cid,{})
        members={str(m.get('sender_id')) for m in batch['messages']+history[-40:]}
        for qq in members:
            if qq in refs:profiles[qq]=Path(refs[qq]).read_text(encoding='utf-8')[:2000]
        request=build_input(account,group,batch['messages'],history,profiles)
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'sessions'))
        from sessions import Sessions
        settings=self.config['bots'][account].get('screening',{})
        model=settings.get('model','gpt-6-luna');effort=settings.get('effort','low');fast=settings.get('fast',True)
        started=time.time();result=None;evidence=None;session_id=None;native=None;usage=None
        try:
            with Sessions(runtime['sessions_database']) as api:
                found=[s for s in api.list() if s.get('purpose')=='screening' and s.get('account_id')==account and s.get('group_id')==group]
                session=found[0] if found else api.create(harness='codex',model=model,effort=effort,account_id=account,group_id=group,purpose='screening',bot_ref=self.config.get('bot_ref'))
                session_id=session['session_id']
            result=CodexProvider('screening',runtime['evidence_root'],model=model,effort=effort,fast=fast,timeout_seconds=runtime.get('timeout_seconds',90))(request)
            evidence=result.pop('_evidence',None);native=result.pop('_native_session_id',None);usage=result.pop('_usage',None)
            if result.get('decision') not in ('wake','silence'):raise ValueError('invalid decision')
        except Exception as exc:
            # One failed batch wakes main on its original messages; no automatic model retry.
            result={'decision':'wake','reason_code':'screening_error','reason':type(exc).__name__}
        if session_id:
            record={'request_id':batch['batch_id'],'session_id':session_id,'status':'success' if evidence else 'failed',
                'started_at':started,'elapsed_seconds':time.time()-started,'response':result,'evidence':evidence,
                'model':model,'effort':effort,'service_tier':'fast' if fast else None,'input_message_ids':[m['id'] for m in batch['messages']],
                'bot_ref':self.config.get('bot_ref'),'native_session_id':native,'usage':usage}
            with Sessions(runtime['sessions_database']) as api:
                with api.db:api.db.execute('INSERT INTO turns(session,request,body) VALUES(?,?,?)',(session_id,batch['batch_id'],json.dumps(record,ensure_ascii=False)))
        return {'batch_id':batch['batch_id'],'result':result}
