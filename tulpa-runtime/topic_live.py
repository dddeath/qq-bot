"""Live event/state boundary; lifecycle actions come from the host conversation."""
import json,os,random,threading,time
from pathlib import Path
from topic_state import TopicState,Limits
from topic_dialogue import dialogue_context,interpret


class LiveTopics:
    def __init__(self, root, group, maintainer, *, config=None, profiles=None):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.group=group;self.maintainer=maintainer;self.profiles=profiles or {}
        self.lock=threading.RLock();config=dict(config or {})
        for key in ('group_limits','topic_limits'):
            if key in config and isinstance(config[key],dict):config[key]=Limits(**config[key])
        self.state=TopicState(**config);self.seen=set();self.inflight=set()
        self.fields=('messages','topics','maintenance','next_topic','queue','decisions','pending')
        stored=self.root/'state.json'
        if stored.exists():
            data=json.loads(stored.read_text(encoding='utf-8'))
            if data['group']!=group:raise ValueError('stored group mismatch')
            for key in self.fields:setattr(self.state,key,data['state'][key])
            self.seen=set(data['seen'])
            for q in self.state.queue:
                if q['status']=='responding':q['status']='unknown'
            self.save('restored')

    def save(self,event,**fields):
        data=dict(group=self.group,seen=sorted(self.seen),state={k:getattr(self.state,k) for k in self.fields})
        temp=self.root/'state.tmp'
        temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        os.replace(temp,self.root/'state.json')
        record=dict(at=time.time(),event=event,**fields)
        with (self.root/'timeline.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')

    def ingest(self,event,now):
        if event['conversation_id']!=self.group:raise ValueError('different group')
        mid=str(event.get('onebot_message_id') or 'event:'+str(event['id']))
        with self.lock:
            if event.get('recalled'):
                self.seen.add(mid)
                self.state.cancel_target(mid,now,reason='recalled');self.save('recalled',message_id=mid);return
            if mid in self.seen or mid in self.inflight:return
            self.inflight.add(mid)
            m=self.state.receive(dict(id=mid,event_id=event['id'],group=self.group,at=event['received_at'],
                 qq_at=event['timestamp']/1000,sender=event['sender_id'],text=event['content'],
                 segments=event.get('segments',[]),is_self=event.get('is_self',False),notice_type=event.get('notice_type')))
            view=self.state.view(now)
            senders={x['sender'] for x in view['messages']}
            profiles={qq:{k:v for k,v in p.items() if k in ('participant_type','source')}
                      for qq,p in self.profiles.get(self.group,{}).items() if qq in senders}
            request=dict(message=m,topics=view['topics'],recent_messages=view['messages'],now=now,
                         dialogue_context=dialogue_context(m,view),participant_profiles=profiles)
        started=time.monotonic()
        try:
            decision=self.maintainer(request)
            direct,interject=interpret(decision,m,view['messages'])
            if decision.get('topic_id') is not None and decision['topic_id'] not in {t['id'] for t in view['topics']}:
                raise ValueError('maintainer referenced an unknown topic')
            if m.get('notice_type')=='poke':direct=True
            decision=dict(decision,direct=direct,should_reply=interject)
            with self.lock:
                if mid in self.seen:return
                self.seen.add(mid)
                if not any(x['id']==mid for x in self.state.messages):
                    self.save('classification_expired',message_id=mid);return
                if decision.get('topic_id') in self.state.topics:
                    self.assign(mid,decision['topic_id'],decision,now)
                else:self.state.defer_assignment(mid,decision,now)
                self.save('classified',message=m,decision=decision,elapsed_s=time.monotonic()-started)
        except Exception as exc:
            with self.lock:
                self.seen.add(mid)
                self.save('classification_error',message=m,error=str(exc));raise
        finally:
            with self.lock:self.inflight.discard(mid)

    def assign(self,mid,tid,decision,now):
        result=self.state.assign(mid,tid,direct=decision['direct'],should_reply=decision['should_reply'],
                                 now=now,draw=random.random(),reason=decision.get('reason',''))
        self.save('assigned',decision=result)
        return result

    def work(self,now):
        with self.lock:
            for tid in self.state.expired_topics(now):
                self.state.retire_topic(tid,now,reason='idle',actor='main',pending_disposition='cancel')
            result=self.state.view(now)
            self.save('work_read')
            return result

    def check(self,mid,plan_id,now):
        with self.lock:
            q=next((q for q in self.state.queue if q['message_id']==mid),None)
            if q is None:raise ValueError('target is not queued')
            if q.get('plan_id') and q['plan_id']!=plan_id:raise ValueError('target already claimed')
            return self.state.check_reply(q['id'],now)

    def claim(self,mid,plan_id,now):
        with self.lock:
            if self.check(mid,plan_id,now)['state']!='ready':raise ValueError('target is not ready')
            q=next(q for q in self.state.queue if q['message_id']==mid)
            q.update(plan_id=plan_id,status='responding');self.save('claimed',message_id=mid,plan_id=plan_id)

    def refresh(self,mid,now,unchanged):
        with self.lock:
            q=next(q for q in self.state.queue if q['message_id']==mid)
            if q['status']=='responding':raise ValueError('send in progress; wait for its receipt')
            self.state.refresh_reply(q['id'],now,unchanged=unchanged)
            self.save('refreshed',message_id=mid,unchanged=unchanged)

    def receipt(self,plan_id,outcome,now):
        with self.lock:
            q=next((q for q in self.state.queue if q.get('plan_id')==plan_id),None)
            if q is None or q['status']!='responding':return
            if outcome not in ('SUCCEEDED','UNKNOWN','INTERRUPTED'):return
            q.update(status={'SUCCEEDED':'sent','UNKNOWN':'unknown','INTERRUPTED':'failed'}[outcome],completed_at=now)
            self.save('receipt',plan_id=plan_id,outcome=outcome)

    def manage(self,mid,action,now,*,topic_id=None,title='',retire_topic_id=None):
        with self.lock:
            self.work(now)
            if action=='retire':
                self.state.retire_topic(topic_id,now,reason='main_completed');self.save('retired',topic_id=topic_id);return
            if action=='dismiss':
                if any(q['message_id']==mid and q['status']=='responding' for q in self.state.queue):
                    raise ValueError('send in progress; wait for its receipt')
                self.state.cancel_target(mid,now,reason='main_silence');self.save('dismissed',message_id=mid);return
            if mid in self.state.decisions:return self.state.decisions[mid]
            pending=self.state.pending.get(mid)
            if not pending:raise ValueError('pending message expired or missing')
            if action=='defer':return dict(action='defer')
            if action not in ('create','reuse'):raise ValueError('unknown lifecycle action')
            if action=='create':
                if retire_topic_id:self.state.retire_topic(retire_topic_id,now,reason='main_replacement')
                topic_id=self.state.create_topic(title,now)['id']
            return self.assign(mid,topic_id,pending['decision'],now)
