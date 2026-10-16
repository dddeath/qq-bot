"""Tulpa hooks for the configured live group; original QQ dispatch stays in Tulpa."""
import json,os,queue,threading,time
from pathlib import Path
from topic_live import LiveTopics
from topic_freshness import FreshnessTopics
from topic_codex import CodexProvider
from topic_dialogue import load_member_profiles

TOOLS={'get_chat_topic_work','manage_chat_topic','refresh_chat_topic_reply'}


class TopicHost:
    def __init__(self,chat,settings):
        self.chat=chat;self.settings=settings;self.sessions={};self.offered=set();self.lock=threading.RLock()
        self.versions={};self.read_versions={}
        self.errors=[]
        self.jobs=queue.Queue();self.closed=False
        self.thread=threading.Thread(target=self.process,daemon=True);self.thread.start()

    def enabled(self,sid):return self.chat.row(sid)['conversation_id']==self.settings['group']

    def session(self,sid):
        with self.lock:
            if sid not in self.sessions:
                if not self.enabled(sid):raise ValueError('topic group not enabled')
                root=Path(self.settings['evidence_root'])/sid
                if self.settings.get('mode')=='freshness_only':
                    self.sessions[sid]=FreshnessTopics(root,self.settings['group'],CodexProvider('freshness',root/'calls'),config=self.settings['state'])
                else:
                    self.sessions[sid]=LiveTopics(root,self.settings['group'],CodexProvider('maintainer',root/'calls'),
                        config=self.settings['state'],profiles=load_member_profiles(self.settings['member_root']))
            return self.sessions[sid]

    def capture(self,sid):
        if not self.enabled(sid):return
        with self.lock:
            for event in self.chat.turns.data(sid):
                key=(sid,event['id'],bool(event.get('recalled')))
                if key not in self.offered:
                    self.offered.add(key);self.jobs.put((sid,event))

    def process(self):
        while True:
            sid,event=self.jobs.get()
            try:
                if self.chat.row(sid)['active']:self.session(sid).ingest(event,time.time())
            except Exception as exc:
                with self.lock:
                    self.errors=(self.errors+[dict(session_id=sid,event_id=event['id'],error=str(exc))])[-10:]
                root=Path(self.settings['evidence_root']);root.mkdir(parents=True,exist_ok=True)
                with (root/'errors.jsonl').open('a',encoding='utf-8') as f:
                    f.write(json.dumps(dict(at=time.time(),session_id=sid,event_id=event['id'],error=str(exc)),ensure_ascii=False)+'\n')
            finally:
                with self.lock:self.versions[sid]=self.versions.get(sid,0)+1
                signal=self.chat.events.get(sid)
                if signal and self.settings.get('mode')!='freshness_only':signal.set()
                self.jobs.task_done()

    def ready(self,sid):
        with self.lock:return self.versions.get(sid,0)>self.read_versions.get(sid,0)

    def work(self,grant,sid):
        _,row=self.chat.validate(sid,grant['id'])
        self.capture(sid)
        with self.lock:version=self.versions.get(sid,0)
        live=self.session(sid);view=live.work(time.time())
        with self.lock:self.read_versions[sid]=version
        ids={m['event_id'] for m in view['messages']}
        rows=[m for m in self.chat.turns.data(sid) if m['id'] in ids]
        with self.chat.access.connect() as db:
            db.executemany('UPDATE chat_inbox SET delivered=1 WHERE session_id=? AND id=?',[(sid,m['id']) for m in rows])
        return dict(session_id=sid,topic_state=view,input_batch=self.chat.turns.batch(row,rows),
                    processing=self.jobs.unfinished_tasks,
                    classification_errors=[e for e in self.errors if e['session_id']==sid],
                    instruction='主聊天为 pending_assignments 选择新建、复用或暂缓；有空位时重看暂缓请求。只回答 queue 中 queued 的一个目标。已结束目标不重复回答。没有可执行工作则继续 wait，不循环空读。')

    def call(self,grant,name,args):
        sid=args['session_id'];self.chat.validate(sid,grant['id'])
        live=self.session(sid)
        if name=='get_chat_topic_work':return self.work(grant,sid)
        if name=='manage_chat_topic':
            live.manage(args.get('message_id'),args['action'],time.time(),topic_id=args.get('topic_id'),
                        title=args.get('title',''),retire_topic_id=args.get('retire_topic_id'))
        elif name=='refresh_chat_topic_reply':live.refresh(args['message_id'],time.time(),args['unchanged'])
        return self.work(grant,sid)

    def target(self,p):
        data=json.loads(p['payload']);sid=p['session_id']
        if not self.enabled(sid) or data['action']!='reply':return None
        live=self.session(sid)
        with live.lock:
            mid=next((q['message_id'] for q in live.state.queue if q['target']['event_id']==data['target_event_id']),None)
        if mid is None:raise ValueError('reply target is not in topic queue')
        return live,mid


def schemas(tool):
    sid=dict(type='string',minLength=32,maxLength=32)
    return [tool('get_chat_topic_work','读取轻量维护者结果、待分配消息和回应队列，主聊天负责话题生命周期。',dict(session_id=sid),['session_id']),
            tool('manage_chat_topic','主聊天新建/复用/回收话题。defer保留请求，有空位后重新分配；dismiss关闭无需继续回应的目标。',
                 dict(session_id=sid,message_id=dict(type='string'),action=dict(type='string',enum=['create','reuse','retire','defer','dismiss']),
                      topic_id=dict(type='string'),retire_topic_id=dict(type='string'),title=dict(type='string',maxLength=200)),['session_id','action']),
            tool('refresh_chat_topic_reply','超过宽限且话题有更新时，主聊天阅读差量并确认是否仍可沿用回答。',
                 dict(session_id=sid,message_id=dict(type='string'),unchanged=dict(type='boolean')),['session_id','message_id','unchanged'])]


def install():
    from chatlocal import mcp_chat
    from chatlocal.mcp_chat_turns import ChatTurns,TurnRejected
    if getattr(mcp_chat,'topic_live_installed',False):return
    settings_path=os.environ.get('QQ_TOPIC_SETTINGS')
    if not settings_path:return
    settings=json.loads(Path(settings_path).read_text())
    if settings.get('mode')=='freshness_only':
        return install_freshness(settings)
    old_init=mcp_chat.MCPChat.__init__;old_call=mcp_chat.MCPChat.call
    old_receive=mcp_chat.MCPChat.receive;old_schemas=mcp_chat.schemas
    old_check=ChatTurns.check;old_save=ChatTurns.save
    def init(self,*args,**kwargs):
        old_init(self,*args,**kwargs);self.topic_host=TopicHost(self,settings)
    def receive(self,event,**kwargs):
        result=old_receive(self,event,**kwargs)
        group=f"{event.get('self_id')}:group:{event.get('group_id')}"
        if group==settings['group']:
            with self.access.connect() as db:
                rows=db.execute('SELECT id FROM chat_sessions WHERE active=1 AND conversation_id=?',(group,)).fetchall()
            for row in rows:self.topic_host.capture(row['id'])
        return result
    def call(self,grant,name,args,cancel):
        if name in TOOLS:
            self.permission(grant);return self.topic_host.call(grant,name,args)
        result=old_call(self,grant,name,args,cancel)
        if name in ('wait_chat_messages','get_chat_session') and self.topic_host.enabled(args['session_id']):
            self.topic_host.capture(args['session_id'])
            result['topic_next_call']=dict(tool='get_chat_topic_work',arguments=dict(session_id=args['session_id']))
        return result
    def check(self,p,cancel,**kwargs):
        try:target=self.chat.topic_host.target(p)
        except ValueError as exc:raise TurnRejected('topic_not_ready',str(exc))
        if target:
            live,mid=target
            try:state=live.check(mid,p['id'],time.time())['state']
            except ValueError as exc:raise TurnRejected('topic_not_ready',str(exc))
            if state!='ready':raise TurnRejected('needs_refresh' if state=='needs_refresh' else 'topic_not_ready',state)
        return old_check(self,p,cancel,**kwargs)
    def save(self,p,state,queue=None,reason=''):
        if state=='SENDING':
            target=self.chat.topic_host.target(p)
            if target:target[0].claim(target[1],p['id'],time.time())
        result=old_save(self,p,state,queue,reason)
        if self.chat.topic_host.enabled(p['session_id']):self.chat.topic_host.session(p['session_id']).receipt(p['id'],state,time.time())
        return result
    mcp_chat.CHAT_TOOLS.update(TOOLS)
    mcp_chat.schemas=lambda tool:old_schemas(tool)+schemas(tool)
    mcp_chat.MCPChat.__init__=init;mcp_chat.MCPChat.call=call;mcp_chat.MCPChat.receive=receive
    ChatTurns.check=check;ChatTurns.save=save
    mcp_chat.topic_live_installed=True


def allow_fresh(chat,p,rows,now):
    """Called only at Tulpa's ordinary-new-message stale check."""
    host=getattr(chat,'topic_host',None)
    if host is None:return False
    if host.settings.get('mode')=='freshness_only':
        data=json.loads(p['payload'])
        if not host.enabled(p['session_id']):return False
        fresh=[m['id'] for m in rows if m['id']>data['watermark']]
        return host.session(p['session_id']).allow(data['target_event_id'],fresh,data['read_at'],now)
    target=host.target(p)
    if target is None:return False
    live,mid=target
    if live.check(mid,p['id'],now)['state']!='ready':return False
    with live.lock:
        q=next(q for q in live.state.queue if q['message_id']==mid)
        if now-q['snapshot_at']<=live.state.stale_grace_seconds:return True
        fresh=[m for m in rows if m['id']>json.loads(p['payload'])['watermark']]
        return all(str(m.get('onebot_message_id') or 'event:'+str(m['id'])) in live.state.decisions for m in fresh)


def topic_ready(chat,sid):
    host=getattr(chat,'topic_host',None)
    return bool(host and host.settings.get('mode')!='freshness_only' and host.ready(sid))


def install_freshness(settings):
    """Leave native input, reply selection and receipt handling untouched."""
    from chatlocal import mcp_chat
    old_init=mcp_chat.MCPChat.__init__;old_receive=mcp_chat.MCPChat.receive
    def init(self,*args,**kwargs):
        old_init(self,*args,**kwargs);self.topic_host=TopicHost(self,settings)
    def receive(self,event,**kwargs):
        result=old_receive(self,event,**kwargs)
        if f"{event.get('self_id')}:group:{event.get('group_id')}"==settings['group']:
            with self.access.connect() as db:
                sessions=db.execute('SELECT id FROM chat_sessions WHERE active=1 AND conversation_id=?',(settings['group'],)).fetchall()
            for row in sessions:self.topic_host.capture(row['id'])
        return result
    mcp_chat.MCPChat.__init__=init;mcp_chat.MCPChat.receive=receive
    mcp_chat.topic_live_installed=True
