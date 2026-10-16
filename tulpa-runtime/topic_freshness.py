"""Private, bounded topic associations; never select replies or alter chat input."""
import json,threading,time
from pathlib import Path
from topic_state import Limits,bounded


class FreshnessTopics:
    def __init__(self,root,group,maintainer,*,config=None):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.group=group;self.maintainer=maintainer;self.lock=threading.RLock()
        c=config or {};self.grace=c.get('stale_grace_seconds',45)
        self.group_limits=Limits(**c.get('group_limits',{}))
        self.topic_limits=Limits(**c.get('topic_limits',dict(max_messages=50,max_age_seconds=1200,max_total_chars=8000)))
        self.max_topics=c.get('max_topics',5);self.idle=c.get('idle_seconds',600)
        self.message_chars=c.get('message_chars',2000)
        if not 1<=self.max_topics<=5 or self.idle<=0 or self.grace<0:raise ValueError('invalid freshness limits')
        self.messages=[];self.topics={};self.next_id=0

    def trim(self,now):
        self.messages=bounded(self.messages,self.group_limits,now)
        retained={m['id'] for m in self.messages}
        for tid,t in list(self.topics.items()):
            t['messages']=bounded([m for m in t['messages'] if m['id'] in retained],self.topic_limits,now)
            if now-t['updated']>=self.idle or not t['messages']:del self.topics[tid]

    def ingest(self,event,now):
        if event['conversation_id']!=self.group:raise ValueError('different group')
        with self.lock:
            self.trim(now)
            if event.get('recalled'):
                self.messages=[m for m in self.messages if m['id']!=event['id']]
                self.trim(now);return
            if any(m['id']==event['id'] for m in self.messages):return
            message=dict(id=event['id'],at=event['received_at'],sender=event['sender_id'],
                         text=event.get('content','')[:self.message_chars])
            self.messages.append(message);self.trim(now)
            request=json.loads(json.dumps(dict(message=message,topics=self.topics,recent_messages=self.messages)))
        started=time.monotonic();result=self.maintainer(request)
        with self.lock:
            self.trim(now)
            if message not in self.messages:return
            tid=result.get('topic_id')
            if tid is None:return
            if tid!='new' and tid not in self.topics:raise ValueError('unknown freshness topic')
            if tid=='new':
                if len(self.topics)>=self.max_topics:
                    del self.topics[min(self.topics,key=lambda k:self.topics[k]['updated'])]
                self.next_id+=1;tid='F'+str(self.next_id)
                self.topics[tid]=dict(messages=[],updated=now)
            self.topics[tid]['messages'].append(message);self.topics[tid]['updated']=message['at'];self.trim(now)
            with (self.root/'associations.jsonl').open('a',encoding='utf-8') as f:
                f.write(json.dumps(dict(at=now,event_id=message['id'],topic_id=tid,elapsed_s=time.monotonic()-started),ensure_ascii=False)+'\n')

    def allow(self,target_id,fresh_ids,read_at,now):
        """Unknown associations fall back to native checking outside the grace."""
        if 0<=now-read_at<=self.grace:return True
        with self.lock:
            self.trim(now)
            assignments={m['id']:tid for tid,t in self.topics.items() for m in t['messages']}
            target=assignments.get(target_id)
            return target is not None and all(i in assignments and assignments[i]!=target for i in fresh_ids)
