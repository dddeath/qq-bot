import sys,json,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
def row(t,p):return {'timestamp':'2026-10-15T01:00:%02dZ'%t,'type':'response_item','payload':p}
class NativeTraceTests(unittest.TestCase):
 def test_pairs_real_outputs_and_only_explicit_prior_assistant_purpose(self):
  from native_reading_traces import convert_trace
  rows=[row(0,{'type':'message','role':'user','content':[{'type':'input_text','text':'READING_PURPOSE {"purpose":"targeted"}'}]}),
        row(1,{'type':'message','role':'assistant','content':[{'type':'output_text','text':'READING_PURPOSE '+json.dumps({'purpose':'targeted','question':'核对技能','relation':'high','relation_reason':'用户问技能','expected_gain':'说明','tool':'get_video_metadata'})}]}),
        row(2,{'type':'function_call','name':'get_video_metadata','call_id':'a','arguments':'{"bvid_or_url":"BV123"}'}),
        row(5,{'type':'function_call_output','call_id':'a','output':'真实结果'}),
        row(6,{'type':'custom_tool_call','name':'exec','call_id':'b','input':'text(await tools.search({q:"x"}));'}),
        row(9,{'type':'custom_tool_call_output','call_id':'b','output':[{'type':'input_text','text':'truncated output'}]})]
  r=convert_trace(rows,{'id':'child'},scope='g',source='fixture')
  self.assertEqual(r['reads'][0]['elapsed_seconds'],3)
  self.assertEqual(r['reads'][0]['purpose_record']['question'],'核对技能')
  self.assertIsNone(r['reads'][1]['purpose_record'])
  self.assertEqual(r['reads'][1]['result']['raw_outputs'][0]['payload']['output'][0]['text'],'truncated output')
  self.assertEqual(r['reads'][1]['action']['kind'],'native_call')
  self.assertIsNone(r['reads'][1]['action']['purpose'])
 def test_collect_discovers_descendants_skips_unrelated_and_is_idempotent(self):
  from native_reading_traces import collect_traces
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);sessions=root/'sessions';sessions.mkdir()
   def put(name,parent):
    meta={'id':name,'source':{'subagent':{'thread_spawn':{'parent_thread_id':parent}}}}
    data=[{'type':'session_meta','payload':meta},row(2,{'type':'function_call','name':'read','call_id':'same','arguments':'{}'}),row(3,{'type':'function_call_output','call_id':'same','output':name})]
    p=sessions/(name+'.jsonl');p.write_text('\n'.join(json.dumps(x) for x in data)+'\n');return p
   child=put('child','main');put('grandchild','child');put('unrelated','other');before=child.read_bytes()
   a=collect_traces(sessions,root/'out',parent_thread_ids=['main'],scope='g')
   self.assertEqual(a['written'],2)
   reports=list((root/'out').rglob('report.json'));saved={str(p):p.read_bytes() for p in reports}
   b=collect_traces(sessions,root/'out',parent_thread_ids=['main'],scope='g')
   self.assertEqual(b['written'],0)
   self.assertEqual(child.read_bytes(),before)
   self.assertTrue(all(Path(p).read_bytes()==data for p,data in saved.items()))
   child.write_bytes(before+b'{"partial":')
   c=collect_traces(sessions,root/'out',parent_thread_ids=['main'],scope='g')
   self.assertEqual(c['written'],1)
   self.assertTrue(any(x.get('trailing_partial') for x in c['snapshots']))
 def test_latest_snapshot_selected_once_and_missing_output_is_not_success(self):
  from native_reading_traces import convert_trace
  from reading_review_runtime import select_daily_reports
  r=convert_trace([row(2,{'type':'function_call','name':'read','call_id':'a','arguments':'{}'})],{'id':'c'},scope='g',source='fixture')
  self.assertEqual(r['reads'][0]['result']['status'],'missing_output');self.assertIsNone(r['reads'][0]['elapsed_seconds'])
  with tempfile.TemporaryDirectory() as t:
   root=Path(t)
   for i in (1,2):
    p=root/str(i);p.mkdir();(p/'report.json').write_text(json.dumps({**r,'captured_at':'2026-10-15T02:00:0%dZ'%i}))
   result=select_daily_reports(root,'2026-10-15','g')
   self.assertEqual([p.parent.name for p in result],['2'])
 def test_wait_links_only_explicit_cell_id_and_does_not_invent_inner_duration(self):
  from native_reading_traces import convert_trace
  rows=[row(1,{'type':'custom_tool_call','name':'exec','call_id':'a','input':'await tools.read()'}),row(2,{'type':'custom_tool_call_output','call_id':'a','output':[{'type':'input_text','text':'Script running with cell ID 42'}]}),row(5,{'type':'function_call','name':'wait','call_id':'b','arguments':'{"cell_id":"42"}'}),row(9,{'type':'function_call_output','call_id':'b','output':'done'})]
  r=convert_trace(rows,{'id':'c'},scope='g',source='f')
  self.assertEqual(r['reads'][1]['continuation_of_call_id'],'a')
  self.assertEqual(r['reads'][0]['elapsed_seconds'],1)
  self.assertEqual(r['reads'][1]['elapsed_seconds'],4)
 def test_late_purpose_and_tool_output_markers_do_not_relabel_past_call(self):
  from native_reading_traces import convert_trace
  r=convert_trace([row(1,{'type':'function_call','name':'read','call_id':'a','arguments':'{}'}),row(2,{'type':'function_call_output','call_id':'a','output':'READING_PURPOSE {"purpose":"targeted","tool":"read"}'}),row(3,{'type':'message','role':'assistant','content':[{'type':'output_text','text':'READING_PURPOSE {"purpose":"explore","tool":"read"}'}]})],{'id':'c'},scope='g',source='f')
  self.assertIsNone(r['reads'][0]['purpose_record'])

 def test_inherited_calls_before_session_start_are_not_collected(self):
  from native_reading_traces import collect_traces
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);sessions=root/'s';sessions.mkdir()
   meta={'id':'c','timestamp':'2026-10-15T01:00:05Z','source':{'subagent':{'thread_spawn':{'parent_thread_id':'p'}}}}
   rows=[{'type':'session_meta','payload':meta},row(1,{'type':'function_call','name':'read','call_id':'old','arguments':'{}'}),row(8,{'type':'function_call','name':'read','call_id':'new','arguments':'{}'})]
   (sessions/'c.jsonl').write_text('\n'.join(map(json.dumps,rows))+'\n')
   r=collect_traces(sessions,root/'out',parent_thread_ids=['p'],scope='g')
   d=json.loads(Path(r['snapshots'][0]['report']).read_text())
   self.assertEqual([x['call_id'] for x in d['reads']],['new'])
   self.assertEqual(d['reads'][0]['source_line'],3)

 def test_environment_is_not_a_task_and_plain_delegation_is_preserved(self):
  from native_reading_traces import convert_trace
  env=row(1,{'type':'message','role':'user','content':[{'type':'input_text','text':'<environment_context>cwd</environment_context>'}]})
  encrypted=row(2,{'type':'agent_message','author':'/root','content':[{'type':'input_text','text':'Message Type: NEW_TASK\nPayload:\n'},{'type':'encrypted_content','encrypted_content':'opaque'}]})
  r=convert_trace([env,encrypted],{'id':'c'},scope='g',source='f')
  self.assertIsNone(r['context']['goal']);self.assertIn('task_goal_unavailable',r['limitations'])
  task=row(3,{'type':'message','role':'user','content':[{'type':'input_text','text':'Read this video'}]})
  r=convert_trace([env,task],{'id':'c'},scope='g',source='f')
  self.assertEqual(r['context']['goal'],'Read this video');self.assertEqual(r['context']['goal_source_line'],2)
 def test_audit_payload_is_bounded_and_omissions_are_explicit(self):
  from reading_review_runtime import bounded_review_payload
  original={'reads':[{'result':{'raw_outputs':['x'*2000000]},'read_id':1}]}
  payload=bounded_review_payload({'original':original,'extension':{'reads':[]}},max_chars=12000)
  self.assertLessEqual(len(json.dumps(payload,ensure_ascii=False)),12000)
  self.assertTrue(payload['audit_input_omissions']);self.assertEqual(len(original['reads'][0]['result']['raw_outputs'][0]),2000000)

