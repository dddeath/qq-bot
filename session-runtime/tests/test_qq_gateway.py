import unittest,tempfile
from pathlib import Path
from sessions import Sessions
from qq_gateway import Gateway
from control_plane import ControlPlane


class ConfiguredToolsTest(unittest.TestCase):
 def test_bound_tool_instructions_replace_old_knowledge_only_gate(self):
  with tempfile.TemporaryDirectory() as tmp, Sessions(Path(tmp)/'db') as api:
   s=api.create(harness='antigravity',account_id='10',group_id='20',model='m',effort='low')
   ControlPlane(api).bind(s['session_id'],purpose='chat',runtime_refs={'tool_instructions':'允许使用已加载的知识库与 B 站只读工具。'})
   def execute(session,prompt):
    self.assertIn('B 站只读工具',prompt)
    self.assertNotIn('本轮只允许这两个知识工具',prompt)
    return dict(status='success',response='ok',native_session_id='n')
   def qq(a,b):return {'status':'ok','retcode':0,'data':{'user_id':10} if a=='get_login_info' else {'message_id':42}}
   e={'post_type':'message','message_type':'group','self_id':10,'group_id':20,'user_id':30,'message_id':99,'message':[{'type':'at','data':{'qq':'10'}},{'type':'text','data':{'text':'question'}}]}
   self.assertEqual(Gateway(api,s['session_id'],execute=execute,qq=qq).handle(e)['receipt'],'42')

class GatewayTest(unittest.TestCase):
 def test_only_target_at_is_answered_once_and_unknown_send_is_not_retried(self):
  with tempfile.TemporaryDirectory() as tmp, Sessions(Path(tmp)/'s.db') as api:
   session=api.create(harness='antigravity',account_id='1000000009',group_id='2000000003',model='flash',effort='low')
   sent=[]
   def qq(action,body):
    if action=='get_login_info':return {'retcode':0,'data':{'user_id':1000000009}}
    sent.append(body);raise TimeoutError('receipt unknown')
   def run(s,p):return {'native_session_id':'n','status':'success','response':'answer','events':[]}
   g=Gateway(api,session['session_id'],execute=run,qq=qq)
   e={'post_type':'message','message_type':'group','self_id':1000000009,'group_id':2000000003,'user_id':1000000004,'message_id':123,'time':1,'message':[{'type':'at','data':{'qq':'1000000009'}},{'type':'text','data':{'text':'question'}}]}
   for bad in [dict(e,group_id=999),dict(e,self_id=99),dict(e,user_id=1000000009),dict(e,message=[{'type':'text','data':{'text':'no at'}}])]:self.assertIsNone(g.handle(bad))
   self.assertEqual(g.handle(e)['status'],'send_unknown')
   self.assertEqual(g.handle(e)['status'],'send_unknown')
   self.assertEqual(len(sent),1);self.assertEqual(sent[0]['group_id'],2000000003)
 def test_success_records_original_group_receipt(self):
  with tempfile.TemporaryDirectory() as tmp, Sessions(Path(tmp)/'s.db') as api:
   s=api.create(harness='codex',account_id='10',group_id='20',model='m',effort='low')
   def qq(a,b):return {'retcode':0,'status':'ok','data':{'user_id':10} if a=='get_login_info' else {'message_id':321}}
   g=Gateway(api,s['session_id'],execute=lambda s,p:{'status':'success','native_session_id':'n','response':'ok'},qq=qq)
   e={'post_type':'message','message_type':'group','self_id':10,'group_id':20,'user_id':30,'message_id':40,'message':[{'type':'at','data':{'qq':'10'}},{'type':'text','data':{'text':'hi'}}]}
   self.assertEqual(g.handle(e)['receipt'],'321')

class FailedReplyTest(unittest.TestCase):
 def test_null_data_preserves_qq_error_without_resending(self):
  with tempfile.TemporaryDirectory() as tmp, Sessions(Path(tmp)/'s.db') as api:
   s=api.create(harness='antigravity',account_id='10',group_id='20',model='m',effort='low')
   calls=[]
   def qq(a,b):
    if a=='get_login_info':return {'retcode':0,'data':{'user_id':10}}
    calls.append(a);return {'status':'failed','retcode':1200,'data':None,'message':'Ban state forbit write req'}
   g=Gateway(api,s['session_id'],execute=lambda s,p:{'status':'success','native_session_id':'n','response':'ok'},qq=qq)
   e={'post_type':'message','message_type':'group','self_id':10,'group_id':20,'user_id':30,'message_id':41,'message':[{'type':'at','data':{'qq':'10'}},{'type':'text','data':{'text':'hi'}}]}
   result=g.handle(e)
   self.assertEqual(result['qq_response']['message'],'Ban state forbit write req')
   self.assertNotIn('AttributeError',result['error'])
   self.assertEqual(g.handle(e)['status'],'send_unknown');self.assertEqual(len(calls),1)

class WindowTest(unittest.TestCase):
 def test_knowledge_prompt_and_expired_reply_are_enforced(self):
  with tempfile.TemporaryDirectory() as tmp, Sessions(Path(tmp)/'s.db') as api:
   s=api.create(harness='antigravity',account_id='10',group_id='20',model='m',effort='low')
   def run(s,p):
    self.assertIn('local-knowledge',p)
    self.assertNotIn('本轮不调用工具',p)
    return {'status':'success','native_session_id':'n','response':'ok'}
   def qq(a,b):self.fail('expired window must not call QQ')
   g=Gateway(api,s['session_id'],execute=run,qq=qq,send_before=1)
   e={'post_type':'message','message_type':'group','self_id':10,'group_id':20,'user_id':30,'message_id':42,'message':[{'type':'at','data':{'qq':'10'}},{'type':'text','data':{'text':'hi'}}]}
   self.assertEqual(g.handle(e)['error'],'RuntimeError: test window expired; reply not sent')
