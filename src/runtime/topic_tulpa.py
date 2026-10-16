"""Background topic association for native Tulpa freshness checks."""
import json,os,queue,threading,time
from pathlib import Path
from topic_freshness import FreshnessTopics
from topic_codex import CodexProvider

class TopicHost:
    def __init__(self,chat,settings):
        self.chat=chat;self.settings=settings;self.sessions={};self.offered=set();self.lock=threading.RLock()
        self.errors=[];self.jobs=queue.Queue()
        self.thread=threading.Thread(target=self.process,daemon=True);self.thread.start()

    def enabled(self,sid):return self.chat.row(sid)['conversation_id']==self.settings['group']

    def session(self,sid):
        with self.lock:
            if sid not in self.sessions:
                if not self.enabled(sid):raise ValueError('topic group not enabled')
                root=Path(self.settings['evidence_root'])/sid
                self.sessions[sid]=FreshnessTopics(root,self.settings['group'],CodexProvider('freshness',root/'calls'),config=self.settings['state'])
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
            finally:self.jobs.task_done()

def install():
    from chatlocal import mcp_chat
    if getattr(mcp_chat,'topic_live_installed',False):return
    settings_path=os.environ.get('QQ_TOPIC_SETTINGS')
    if not settings_path:return
    settings=json.loads(Path(settings_path).read_text())
    if settings.get('mode')!='freshness_only':raise ValueError('Only freshness_only topic mode is supported')
    install_freshness(settings)

def allow_fresh(chat,p,rows,now):
    host=getattr(chat,'topic_host',None)
    if host is None or not host.enabled(p['session_id']):return False
    data=json.loads(p['payload'])
    fresh=[m['id'] for m in rows if m['id']>data['watermark']]
    return host.session(p['session_id']).allow(data['target_event_id'],fresh,data['read_at'],now)

def topic_ready(chat,sid):
    # Existing Tulpa hooks call this; association updates do not wake the main chat.
    return False

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
