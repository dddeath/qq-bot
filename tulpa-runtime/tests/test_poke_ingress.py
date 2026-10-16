"""OneBot receive -> public chat context, with an offline QQ endpoint."""
import json,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from chatlocal.store import Store
from chatlocal.mcp_access import MCPAccess
from chatlocal.mcp_actions import MCPActions
from chatlocal.mcp_chat import MCPChat
from chatlocal.message_sender import QQSender

class QQ:
    def login(self):return '123'
    def call(self,action,args,**kwargs):
        if action=='get_group_list':return [{'group_id':456,'group_name':'test'}]
        if action=='get_group_info':return {'group_id':456,'group_name':'test'}
        if action=='get_login_info':return {'user_id':123,'nickname':'QA'}
        if action=='get_stranger_info':return {'nickname':'QA','long_nick':'signature'}
        if action=='get_group_member_info':return {'user_id':args['user_id'],'card':'QA'}
        if action=='set_group_card':return None
        raise AssertionError('Unexpected QQ request: '+action)

class PokeTests(unittest.TestCase):
    def test_mcp_dispatch_exposes_six_actions_and_rejects_foreign_target(self):
        from chatlocal.mcp_tools import MCPTools
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'chat.sqlite');access=MCPAccess(store);access.configure(True,18777)
            with patch('chatlocal.onebot.Client',return_value=QQ()):created=access.create(dict(name='test',platforms=['qq'],conversations=[['qq','123:group:456']],chat=True,send=True))
            receiver=SimpleNamespace(start=lambda:None,stop=lambda:None,status=lambda:dict(state='connected',account='123'))
            with patch('chatlocal.mcp_chat.EventReceiver',return_value=receiver):mcp=MCPTools(access)
            mcp.actions.client_factory=QQ;mcp.actions.sender_factory=lambda:SimpleNamespace(prepare=lambda target,confirm:dict(account='123',name='test',kind='group',peer='456'))
            token=created['token'];cancel=threading.Event()
            def invoke(name,args):return mcp.call(token,name,args,cancel).structuredContent
            start=invoke('start_chat_session',dict(conversation_id='123:group:456',persona='test',idempotency_key='mcp-test-session'));sid=start['session']['id']
            self.assertEqual(invoke('get_self_qq_capabilities',{'session_id':sid})['error_code'],'tool_unavailable')
            (Path(folder)/'mcp-self-qq.json').write_text(json.dumps({'enabled':True,'grant_ids':[created['id']],'conversation_ids':['123:group:456']}))
            tools=invoke('get_self_qq_capabilities',{'session_id':sid})['tools'];self.assertEqual(len(tools),8)
            args=dict(session_id=sid,card='GPT',idempotency_key='set-card-1')
            self.assertEqual(invoke('set_self_qq_group_card',args|{'user_id':999})['error_code'],'invalid_arguments')
            self.assertEqual(invoke('set_self_qq_group_card',args)['state'],'SUCCEEDED')
            invoke('stop_chat_session',{'session_id':sid})
            self.assertEqual(invoke('set_self_qq_group_card',args|{'idempotency_key':'set-card-2'})['error_code'],'self_qq_rejected')

    def test_only_poke_to_self_reaches_chat_context_and_is_deduplicated(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'chat.sqlite');access=MCPAccess(store);access.configure(True,18777)
            with patch('chatlocal.onebot.Client',return_value=QQ()):
                created=access.create(dict(name='test',platforms=['qq'],conversations=[['qq','123:group:456']],chat=True,send=True))
            grant=access.by_id(created['id'],source=False)
            sender=SimpleNamespace(prepare=lambda target,confirm:dict(account='123',name='test',kind='group',peer='456'))
            actions=MCPActions(access,client_factory=QQ,sender_factory=lambda:sender)
            receiver=SimpleNamespace(start=lambda:None,stop=lambda:None,status=lambda:dict(state='connected',account='123'))
            with patch('chatlocal.mcp_chat.EventReceiver',return_value=receiver):chat=MCPChat(access,actions)
            session=chat.start(grant,dict(conversation_id='123:group:456',persona='test',idempotency_key='poke-test-session'),threading.Event())
            sid=session['session']['id']
            event=dict(post_type='notice',notice_type='notify',sub_type='poke',self_id=123,group_id=456,user_id=789,target_id=123,time=int(time.time()))
            chat.receive(event);chat.receive(event);chat.receive(event|{'target_id':999});chat.receive(event|{'group_id':999});chat.receive(event|{'user_id':123})
            context=chat.get(grant,sid)['context']['messages']
            self.assertEqual(len(context),1)
            self.assertEqual(context[0]['notice_type'],'poke');self.assertEqual(context[0]['sender_id'],'789')
            self.assertEqual(context[0]['poke_target_id'],'123');self.assertEqual(context[0]['onebot_message_id'],'')
            self.assertIn('戳了你',context[0]['content'])
            sent=[]
            def native(action,args,**kwargs):
                if action=='send_group_msg':
                    sent.append(args);return {'message_id':111}
                return QQ().call(action,args,**kwargs)
            real_sender=QQSender({'REPLY_ONEBOT_URL':'http://127.0.0.1:9','REPLY_ONEBOT_TOKEN':''})
            real_sender.call=native
            actions.sender_factory=lambda:real_sender
            policy=chat.turns.policy()
            chat.turns.policy=lambda:policy|{'quiet_seconds':0}
            current=chat.get(grant,sid)
            plan=chat.turns.plan(grant,dict(session_id=sid,batch_id=current['input_batch']['id'],
                action='reply',intent='Respond to the poke',target_event_id=context[0]['id'],expressions=['text']),threading.Event())
            self.assertEqual(plan['state'],'READY',plan)
            result=chat.turns.submit(grant,dict(session_id=sid,plan_id=plan['plan_id'],
                bubbles=[{'kind':'text','text':'角都给你戳歪了'}]),threading.Event())
            self.assertEqual(result['state'],'SUCCEEDED',result)
            self.assertEqual(sent,[{'group_id':456,'message':[{'type':'text','data':{'text':'角都给你戳歪了'}}]}])
            with self.assertRaises(ValueError):
                chat.send(grant,dict(session_id=sid,idempotency_key='quote-poke',text='invalid quote',
                    reply_to_event_id=context[0]['id'],quote=True),threading.Event())
            self.assertEqual(len(sent),1)
            chat.stop(sid)

if __name__=='__main__':unittest.main()
