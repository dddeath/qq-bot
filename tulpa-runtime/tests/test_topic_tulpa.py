"""Real Tulpa MCP boundary with offline QQ and decision-model endpoints."""
import json,os,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
try:
    from chatlocal.store import Store
except ImportError:
    Store=None

@unittest.skipIf(Store is None,'requires deployed Tulpa source; run server isolated suite')
class TulpaTopicTests(unittest.TestCase):
    def test_native_input_and_reply_do_not_wait_for_maintenance_or_require_queue(self):
        from chatlocal.mcp_access import MCPAccess
        from chatlocal.mcp_tools import MCPTools
        from chatlocal.message_sender import QQSender
        from topic_tulpa import install
        class QQ:
            def login(self):return '123'
            def call(self,action,args,**kw):
                if action=='get_group_list':return [{'group_id':456,'group_name':'test'}]
                if action=='get_group_info':return {'group_id':456,'group_name':'test'}
                if action=='get_login_info':return {'user_id':123,'nickname':'QA'}
                raise AssertionError(action)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            settings=root/'settings.json'
            settings.write_text(json.dumps(dict(mode='freshness_only',group='123:group:456',state={'bot_id':'123'},member_root=str(root/'members'),evidence_root=str(root/'state'))))
            with patch.dict(os.environ,QQ_TOPIC_SETTINGS=str(settings)):install()
            access=MCPAccess(Store(root/'chat.sqlite'));access.configure(True,18777)
            with patch('chatlocal.onebot.Client',return_value=QQ()):
                created=access.create(dict(name='test',platforms=['qq'],conversations=[['qq','123:group:456']],chat=True,send=True))
            receiver=SimpleNamespace(start=lambda:None,stop=lambda:None,status=lambda:dict(state='connected',account='123'))
            gate=threading.Event()
            def decision(request):
                if request['message']['text']=='blocked':gate.wait(5)
                return dict(topic_id=None,addressee='bot',intent='question',reply_to_message_id=None,should_interject=False,reason='test request')
            with patch('chatlocal.mcp_chat.EventReceiver',return_value=receiver),patch('topic_tulpa.CodexProvider',return_value=decision):
                mcp=MCPTools(access)
                sent=[]
                sender=QQSender({'REPLY_ONEBOT_URL':'http://127.0.0.1:9','REPLY_ONEBOT_TOKEN':''})
                def native(action,args,**kw):
                    if action=='send_group_msg':sent.append(args);return {'message_id':111}
                    return QQ().call(action,args,**kw)
                sender.call=native;mcp.actions.client_factory=QQ;mcp.actions.sender_factory=lambda:sender
                cancel=threading.Event()
                def invoke(name,**args):return mcp.call(created['token'],name,args,cancel).structuredContent
                start=invoke('start_chat_session',conversation_id='123:group:456',persona='test',idempotency_key='topics-test-session')
                sid=start['session']['id'];chat=mcp.chat
                event=dict(post_type='message',message_type='group',self_id=123,group_id=456,user_id=789,
                           time=int(time.time()),sender={'nickname':'tester'},message_id=100,
                           message=[{'type':'text','data':{'text':'Explain ice'}}])
                chat.receive(event);chat.topic_host.jobs.join()
                raw=invoke('wait_chat_messages',session_id=sid,timeout_seconds=1)
                self.assertNotIn('topic_next_call',raw)
                self.assertNotIn('topic_state',raw)
                self.assertEqual(raw['messages'][0]['content'],'Explain ice')
                target=raw['messages'][0]['id']
                time.sleep(chat.turns.policy()['quiet_seconds']+.02)
                plan=invoke('plan_chat_reply',session_id=sid,batch_id=raw['input_batch']['id'],action='reply',intent='explain',target_event_id=target,expressions=['text'])
                self.assertEqual(plan['state'],'READY',plan)
                chat.receive(event|{'message_id':101,'message':[{'type':'text','data':{'text':'blocked'}}]})
                time.sleep(chat.turns.policy()['quiet_seconds']+.02)
                # A pending maintenance model must not gate the reply within grace.
                result=invoke('send_chat_reply',session_id=sid,plan_id=plan['plan_id'],bubbles=[{'kind':'text','text':'Ice is less dense.'}])
                self.assertEqual(result['state'],'SUCCEEDED',result)
                again=invoke('send_chat_reply',session_id=sid,plan_id=plan['plan_id'],bubbles=[{'kind':'text','text':'Ice is less dense.'}])
                self.assertEqual(again['state'],'SUCCEEDED',again)
                self.assertEqual(len(sent),1)
                gate.set();chat.topic_host.jobs.join()
                invoke('stop_chat_session',session_id=sid)
