import tempfile,unittest
from pathlib import Path
from sessions import Sessions

class SessionsTest(unittest.TestCase):
 def test_both_harnesses_preserve_native_context_across_reopen(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'sessions.db'
   with Sessions(path) as api:
    a=api.create(harness='codex',account_id='1000000011',group_id='2000000001',model='gpt-6.1-sol',effort='low',native_session_id='existing-codex-thread')
    b=api.create(harness='antigravity',account_id='1000000009',group_id='2000000003',model='gemini-3.8-flash-low',effort='low')
   with Sessions(path) as api:
    self.assertEqual(api.get(a['session_id'])['native_session_id'],'existing-codex-thread')
    self.assertEqual(api.get(b['session_id'])['harness'],'antigravity')
    self.assertNotEqual(a['session_id'],b['session_id'])
    self.assertEqual(len(api.list()),2)

if __name__=='__main__':unittest.main()

class ExecutionTest(unittest.TestCase):
 def test_send_records_answer_and_resumes_the_same_native_thread(self):
  with tempfile.TemporaryDirectory() as tmp:
   with Sessions(Path(tmp)/'s.db') as api:
    s=api.create(harness='antigravity',account_id='a',group_id='g',model='flash',effort='low')
    def execute(session,prompt):
     return {'native_session_id':session['native_session_id'] or 'native-1','response':'answer:'+prompt,'events':[{'event':'result'}],'exit_code':0,'status':'success'}
    first=api.send(s['session_id'],'hello',request_id='m1',execute=execute)
    duplicate=api.send(s['session_id'],'hello',request_id='m1',execute=lambda *a: self.fail('duplicate execution'))
    second=api.send(s['session_id'],'next',request_id='m2',execute=execute)
    self.assertEqual(first,duplicate)
    self.assertEqual(second['native_session_id'],'native-1')
    self.assertEqual(api.get(s['session_id'])['status'],'idle')
    self.assertEqual(len(api.history(s['session_id'])),2)
 def test_unknown_execution_blocks_new_messages_without_losing_native_id(self):
  with tempfile.TemporaryDirectory() as tmp:
   with Sessions(Path(tmp)/'s.db') as api:
    s=api.create(harness='codex',account_id='a',group_id='g',model='sol',effort='low',native_session_id='keep-me')
    def broken(*a):raise TimeoutError('uncertain result')
    r=api.send(s['session_id'],'hello',request_id='m1',execute=broken)
    self.assertEqual(r['status'],'unknown')
    self.assertEqual(api.get(s['session_id'])['native_session_id'],'keep-me')
    with self.assertRaisesRegex(ValueError,'not idle'):api.send(s['session_id'],'next',request_id='m2',execute=broken)
