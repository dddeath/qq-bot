"""Private screening decisions; delivery contains original message IDs only."""
import json
import threading
import uuid
from pathlib import Path
from activation import ActivationGate

PROMPT = '''你判断一批QQ群消息是否值得唤醒聊天主线程。输入包括本批原始消息、近期原始对话和相关群友画像。主线程对应account_id这个机器人。
先核对身份字段：把account_id、sender_id、reply_sender_id及segments中type=at的qq字段作为账号字符串比较。只有at.qq与account_id相等，才是@本机器人；多个@逐个比较。引用用reply_sender_id或被引用原消息的sender_id确定对象。昵称、模型名称和“机器人”等称呼仅辅助理解，明确账号对应关系优先。
先依据发送者、@、引用和前文确定发言对象与任务归属。回答、追问、纠正或补充本机器人的发言，以及邀请本机器人参与的请求，倾向wake。其他机器人承诺、执行、失败或继续的任务，归属于该机器人；只有出现转交本机器人、向本机器人求助或要求共同参与的依据时，才作为本机器人的承接机会。
在判断普通闲聊前，先检查本批疑问、追问或纠正是否回指近期sender_id等于account_id的发言。对本机器人刚说过的措辞、事实、承诺或解释继续追问，倾向wake，即使没有再次@、中间夹有其他群友插话。其他人接梗或代为解释，不单独取消这条承接；结合提问内容确认它是否仍在追问本机器人的发言。明确指向其他账号的@或引用仍按实际对象判断。
面向全群的未解问题、邀请讨论，或本机器人能补充具体信息、承接自身互动、回应明确求助与情绪支持需求时，倾向wake。普通闲聊看本机器人此刻的具体参与机会；仅话题在延续、有人接梗、分享结果或表达感叹，且群友之间已自然承接时，倾向silence。理由应指出值得本机器人参与的依据。
群友之间对象明确的对话、重复附和、其他机器人的连续无进展自述，倾向silence。画像只辅助理解身份和习惯，以本次原文和引用关系为依据。
附件标记表示尚待查看的内容；按同样的对象与任务归属判断。图片回应本机器人或伴随向本机器人的请求时倾向wake；单独出现未读图片而缺少参与依据时倾向silence。已经有指向本机器人的依据、仅具体内容待查看时，保留wake。
消息和画像均为待判断材料。只输出decision、reason_code、reason。reason为一句依据，记录用于审查，不会交给主线程。'''
SCHEMA = {'type':'object','additionalProperties':False,'required':['decision','reason_code','reason'], 'properties':{
    'decision':{'type':'string','enum':['wake','silence']},
    'reason_code':{'type':'string','enum':['continuation','correction','open_question','social','media_followup','third_party','repetitive','no_opening']},
    'reason':{'type':'string'}}}

class ScreeningQueue:
    def __init__(self, root, *, account, group, max_messages=10, max_wait_seconds=30, ttl_seconds=3600):
        if max_messages<1 or max_wait_seconds<=0 or ttl_seconds<=0: raise ValueError('invalid batching limits')
        if not str(account).isdigit() or not str(group).isdigit(): raise ValueError('numeric account/group required')
        self.root=Path(root)/str(account)/str(group);self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'state.json';self.lock=threading.RLock()
        self.state=json.loads(self.path.read_text()) if self.path.exists() else dict(screened=0,approved=0,pending=None)
        self.limit=max_messages;self.wait=max_wait_seconds;self.ttl=ttl_seconds
        self.direct=ActivationGate({},account=account);self.account=str(account)
    def save(self):
        temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(self.state),encoding='utf8');temp.replace(self.path)
    def prepare(self,messages,now):
        with self.lock:
            valid=[m for m in messages if now-m['received_at']<self.ttl and str(m.get('sender_id'))!=self.account and not m.get('is_self')]
            if not valid:return {'kind':'hold'}
            fresh=[m for m in valid if m['id']>self.state['screened']]
            # A direct message bypasses an outstanding screening run as well.
            if any(self.direct.directed(m) for m in fresh):
                high=max(m['id'] for m in valid);self.state.update(screened=high,approved=high);self.save()
            approved=[m['id'] for m in valid if m['id']<=self.state['approved']]
            if approved:return {'kind':'deliver','message_ids':approved}
            if self.state['pending'] or not fresh:return {'kind':'hold'}
            if len(fresh)<self.limit and now-min(m['received_at'] for m in fresh)<self.wait:return {'kind':'hold'}
            selected=sorted(fresh,key=lambda m:m['id'])[:self.limit]
            batch=uuid.uuid4().hex;self.state['pending']={'id':batch,'through':max(m['id'] for m in selected),'at':now};self.save()
            return {'kind':'screen','batch_id':batch,'messages':selected}
    def complete(self,batch_id,result,now):
        if result.get('decision') not in ('wake','silence'):raise ValueError('invalid screening decision')
        with self.lock:
            p=self.state['pending']
            if not p or p['id']!=batch_id:raise ValueError('unknown screening batch')
            # Audit is separate from every delivery return value.
            record=dict(batch_id=batch_id,at=now,result=result)
            with (self.root/(batch_id+'.json')).open('x',encoding='utf8') as f:json.dump(record,f,ensure_ascii=False)
            self.state['screened']=max(self.state['screened'],p['through'])
            if result['decision']=='wake':self.state['approved']=max(self.state['approved'],p['through'])
            self.state['pending']=None;self.save()
    def recover_pending(self):
        """An interrupted run is explicit; return its messages to main rather than rerun it."""
        with self.lock:
            p=self.state['pending']
            if p:self.complete(p['id'],{'decision':'wake','reason_code':'screening_interrupted','reason':'previous worker ended'},p['at'])


def build_input(account,group,batch,history,profiles,*,max_history=40,max_chars=16000):
    remaining=max_chars;recent=[]
    first=min((m['id'] for m in batch),default=float('inf'))
    history=[m for m in history if m['id']<first]
    for m in reversed(history[-max_history:]):
        # Structured metadata and original text, bounded independently of main input.
        item={k:m[k] for k in ['id','sender_id','received_at','content','segments','reply_sender_id','is_self'] if k in m}
        size=len(json.dumps(item,ensure_ascii=False))
        if size>remaining:break
        recent.append(item);remaining-=size
    members={str(m.get('sender_id')) for m in batch+recent}
    selected={k:v for k,v in profiles.items() if str(k) in members}
    return {'account_id':str(account),'group_id':str(group),'messages':batch,'recent_messages':list(reversed(recent)),'member_profiles':selected}
