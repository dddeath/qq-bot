import tempfile,unittest,sys,json
from pathlib import Path
from harnesses import Harnesses

class HarnessTest(unittest.TestCase):
 def test_session_specific_harness_configuration_is_used_and_recorded(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);script=root/'cli.py'
   script.write_text('import json,os\nprint(json.dumps({"event":"result","result":{"status":"SUCCESS","response":os.environ["BOT_SCOPE"],"conversation_id":"same-native"}}))')
   config=root/'harness.json';config.write_text(json.dumps({'command':[sys.executable,str(script)],'cwd':tmp,'env':{'BOT_SCOPE':'pwie'}}))
   result=Harnesses({},root/'evidence')({'harness':'antigravity','model':'flash','effort':'low','native_session_id':'same-native','runtime_refs':{'harness_config':str(config)}},'q')
   self.assertEqual(result['response'],'pwie')
   self.assertEqual(result['harness_config_ref'],str(config))
 def test_native_events_normalize_and_resume_arguments_are_retained(self):
  for harness in ('codex','antigravity'):
   with self.subTest(harness=harness), tempfile.TemporaryDirectory() as tmp:
    script=Path(tmp)/'cli.py'
    if harness=='codex':events=[{'type':'thread.started','thread_id':'native-c'},{'type':'item.completed','item':{'type':'agent_message','text':'answer'}},{'type':'turn.completed','usage':{'input_tokens':1}}]
    else:events=[{'event':'result','result':{'conversation_id':'native-a','status':'SUCCESS','response':'answer'}}]
    script.write_text('import sys,json\nprint(json.dumps('+repr(events[0])+'))\n'+''.join('print(json.dumps('+repr(e)+'))\n' for e in events[1:]))
    adapter=Harnesses({harness:{'command':[sys.executable,str(script)],'cwd':tmp}},Path(tmp)/'evidence')
    result=adapter({'harness':harness,'model':'test','effort':'low','native_session_id':'resume-id'},'question')
    self.assertEqual(result['status'],'success');self.assertEqual(result['response'],'answer')
    self.assertIn('resume-id',result['command']);self.assertEqual(len(result['events']),len(events))
 def test_exit_zero_with_denied_actions_is_not_success(self):
  with tempfile.TemporaryDirectory() as tmp:
   script=Path(tmp)/'cli.py';script.write_text('print(\'{"event":"result","result":{"status":"SUCCESS","response":"","denied_actions":[{"action":"mcp"}]}}\')')
   adapter=Harnesses({'antigravity':{'command':[sys.executable,str(script)],'cwd':tmp}},Path(tmp)/'evidence')
   self.assertEqual(adapter({'harness':'antigravity','model':'test','effort':'low','native_session_id':None},'q')['status'],'unknown')
