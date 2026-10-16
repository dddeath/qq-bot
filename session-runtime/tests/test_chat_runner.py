import tempfile
import unittest
from pathlib import Path
from sessions import Sessions


class ChatRunnerTest(unittest.TestCase):
    def test_unknown_native_result_and_expired_window_stop_continuations(self):
        from chat_runner import run
        with tempfile.TemporaryDirectory() as tmp, Sessions(Path(tmp)/'db') as api:
            session=api.create(harness='antigravity',account_id='309',group_id='112',model='flash',effort='low')
            calls=[]
            def execute(s,prompt):
                calls.append(prompt)
                return dict(status='unknown',response='',native_session_id='retained-native')
            stopped=run(api,session['session_id'],execute=execute,prompt='chat',active=lambda:True,deadline=100,clock=lambda:101,pause=lambda _:None)
            self.assertEqual(stopped,{'reason':'window_closed','turns':[]})
            result=run(api,session['session_id'],execute=execute,prompt='chat',active=lambda:True,deadline=100,clock=lambda:1,pause=lambda _:None)
            self.assertEqual(result['reason'],'native_result_unknown')
            self.assertEqual(len(calls),1)
            self.assertEqual(api.get(session['session_id'])['native_session_id'],'retained-native')

    def test_continuations_keep_native_thread_and_do_not_forward_cli_final_text(self):
        from chat_runner import run
        with tempfile.TemporaryDirectory() as tmp, Sessions(Path(tmp)/'db') as api:
            session=api.create(harness='antigravity',account_id='309',group_id='112',model='flash',effort='low',native_session_id='same-native')
            calls=[]
            def execute(s,prompt):
                calls.append((s['native_session_id'],prompt))
                return dict(status='success',native_session_id='same-native',response='internal completion')
            result=run(api,session['session_id'],execute=execute,prompt='use Tulpa and continue receiving',active=lambda:len(calls)<2,deadline=100,clock=lambda:1,pause=lambda _:None)
            self.assertEqual(len(calls),2)
            self.assertTrue(all(sid=='same-native' for sid,_ in calls))
            self.assertEqual(len(api.history(session['session_id'])),2)
            self.assertEqual(result['reason'],'chat_stopped')


    def test_denied_auxiliary_read_abandons_action_and_continues_same_thread(self):
        from chat_runner import run
        with tempfile.TemporaryDirectory() as tmp, Sessions(Path(tmp)/'db') as api:
            session=api.create(harness='antigravity',account_id='309',group_id='983',model='flash',effort='high',native_session_id='same-native')
            calls=[]
            def execute(s,prompt):
                calls.append((s['native_session_id'],prompt))
                if len(calls)==1:return denied_read()
                return dict(status='success',native_session_id='same-native',response='internal')
            result=run(api,session['session_id'],execute=execute,prompt='chat',active=lambda:len(calls)<2,deadline=100,clock=lambda:1,pause=lambda _:None)
            self.assertEqual(len(calls),2)
            self.assertEqual(calls[1][0],'same-native')
            self.assertIn('放弃',calls[1][1])
            self.assertEqual(api.history(session['session_id'])[0]['status'],'unknown')
            self.assertEqual(api.get(session['session_id'])['status'],'idle')
            self.assertEqual(result['reason'],'chat_stopped')

    def test_unknown_send_receipt_and_other_failures_still_stop(self):
        from chat_runner import run
        import copy
        bad=denied_read()
        bad['events'].insert(0,{'event':'step_update','step_update':{'step_index':0,'step_type':'tool','tool_name':'call_mcp_tool','state':'DONE','tool_info':{'parameters':{'ToolName':'send_chat_reply'},'output':'{"state":"UNKNOWN"}'}}})
        timeout=denied_read();timeout['error']='timeout; native result unknown'
        wrong=denied_read();wrong['events'][0]['step_update']['tool_info']['parameters']['CommandLine']='rm /tmp/example'
        for value in (bad,timeout,wrong):
            with self.subTest(value=value),tempfile.TemporaryDirectory() as tmp,Sessions(Path(tmp)/'db') as api:
                session=api.create(harness='antigravity',account_id='309',group_id='983',model='flash',effort='high',native_session_id='same-native')
                calls=[]
                def execute(s,p):calls.append(p);return copy.deepcopy(value)
                result=run(api,session['session_id'],execute=execute,prompt='chat',active=lambda:len(calls)<2,deadline=100,clock=lambda:1,pause=lambda _:None)
                self.assertEqual(result['reason'],'native_result_unknown');self.assertEqual(len(calls),1)
                self.assertEqual(api.get(session['session_id'])['status'],'unknown')

    def test_prior_image_read_failure_does_not_mask_final_read_denial(self):
        from continuation_policy import auxiliary_read_denial
        result=denied_read()
        result['events'].insert(0,{'event':'step_update','step_update':{'step_index':0,'step_type':'tool','tool_name':'call_mcp_tool','state':'ERROR','tool_info':{'parameters':{'ServerName':'tulpa','ToolName':'read_chat_image'},'error':{'message':'image exceeds 6 MiB'}}}})
        self.assertTrue(auxiliary_read_denial(result))

def denied_read():
    return dict(status='unknown',native_session_id='same-native',exit_code=0,error=None,denied=True,events=[
        {'event':'step_update','step_update':{'step_index':1,'step_type':'tool','tool_name':'run_command','state':'ERROR','tool_info':{'parameters':{'CommandLine':'grep -n "poke_chat_member" /home/test/.system_generated/logs/transcript.jsonl'},'error':{'type':'TOOL_ERROR','message':'permission check failed: user denied permission to run command'}}}},
        {'event':'result','result':{'status':'SUCCESS','denied_actions':[{'action':'command'}]}}])
