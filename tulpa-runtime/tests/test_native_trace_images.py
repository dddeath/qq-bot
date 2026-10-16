import base64,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_reading_traces import collect_traces
PNG='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='
class NativeImageTests(unittest.TestCase):
 def test_collected_images_are_readable_and_bound_to_real_call_without_changing_raw_output(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);src=root/'sessions';src.mkdir()
   output={'type':'response_item','payload':{'type':'custom_tool_call_output','call_id':'c1','output':[{'type':'input_text','text':'00:05'},{'type':'input_image','image_url':'data:image/png;base64,'+PNG}]}}
   rows=[{'type':'session_meta','payload':{'id':'child','source':{'subagent':{'thread_spawn':{'parent_thread_id':'parent'}}}}},{'type':'response_item','payload':{'type':'custom_tool_call','name':'exec','call_id':'c1','input':'real call'}},output]
   source=src/'s.jsonl';source.write_text('\n'.join(map(json.dumps,rows)))
   for run in ['one','two']:
    result=collect_traces(src,root/run,parent_thread_ids=['parent'],scope='g');report=json.loads(Path(result['snapshots'][0]['report']).read_text())
    read=report['reads'][0];self.assertEqual(len(read['result']['images']),1)
    im=read['result']['images'][0];self.assertEqual(Path(im['path']).read_bytes(),base64.b64decode(PNG));self.assertEqual(im['call_id'],'c1')
    self.assertEqual(read['result']['raw_outputs'],[output])
    if run=='one':first=Path(im['path']);before=first.read_bytes()
    else:self.assertNotEqual(first,Path(im['path']));self.assertEqual(first.read_bytes(),before)
if __name__=='__main__':unittest.main()
