import tempfile, unittest, json, os
from pathlib import Path
from sessions import Sessions

class AdoptTest(unittest.TestCase):
 def test_adopt_keeps_native_runner_and_blocks_duplicate_execution(self):
  with tempfile.TemporaryDirectory() as tmp:
   run=Path(tmp)/'run';run.mkdir()
   (run/'codex.pid').write_text(str(os.getpid()))
   (run/'run.jsonl').write_text(json.dumps({'type':'thread.started','thread_id':'native-live'})+'\n')
   with Sessions(Path(tmp)/'s.db') as api:
    kwargs=dict(harness='codex',account_id='1000000011',group_id='2000000001',model='gpt-6.1-sol',effort='low',native_session_id='native-live',run_path=str(run),tulpa_session_id='tulpa-live')
    s=api.adopt(**kwargs)
    self.assertEqual(api.adopt(**kwargs)['session_id'],s['session_id'])
    self.assertEqual(api.get(s['session_id'])['native_session_id'],'native-live')
    self.assertEqual(api.get(s['session_id'])['status'],'running')
    with self.assertRaisesRegex(ValueError,'externally managed'):
     api.send(s['session_id'],'hello',request_id='r1',execute=lambda *a: self.fail('started duplicate'))
    self.assertEqual(api.history(s['session_id'])[0]['event']['thread_id'],'native-live')
    with self.assertRaisesRegex(ValueError,'already registered'):
     api.create(harness='codex',account_id='1000000011',group_id='2000000001',model='gpt-6.1-sol',effort='low',native_session_id='native-live')
    api.detach(s['session_id'])
    self.assertTrue((run/'run.jsonl').exists())
    self.assertEqual(api.list(),[])
