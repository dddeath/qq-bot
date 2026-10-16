import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_reading_traces import convert_trace

def message(second,text,role='assistant'):
 return {'timestamp':f'2026-10-16T01:00:{second:02d}Z','type':'response_item','payload':{'type':'message','role':role,'channel':'commentary','content':[{'type':'output_text','text':text}]}}
def marker(second,kind,value):return message(second,kind+' '+json.dumps(value))
def call(second):return {'timestamp':f'2026-10-16T01:00:{second:02d}Z','type':'response_item','payload':{'type':'function_call','name':'read','call_id':'real-1','arguments':'{}'}}
class DailyTraceTests(unittest.TestCase):
 def test_entry_records_goal_video_and_budget_even_with_encrypted_task(self):
  task={'goal':'核对视频的护盾变化','video':'https://www.bilibili.com/video/BV15euuzWEcC/?p=2','budget':{'max_read_units':10,'timeout_seconds':300,'exploration_budget_ratio':0.2},'event_id':'test-event'}
  r=convert_trace([message(0,'<environment_context>x</environment_context>','user'),marker(1,'READING_TASK',task),call(2)],{'id':'child'},scope='fixture',source='f')
  self.assertEqual(r['context']['goal'],task['goal']);self.assertEqual(r['video'],task['video'])
  self.assertEqual(r['context']['budget']['max_read_units'],10)
  self.assertEqual(r['context']['task_source']['line'],2)
  self.assertEqual(r['context']['task_source']['basis'],'assistant_declared_at_entry')

 def test_outcome_and_stop_are_linked_to_real_completed_read(self):
  purpose={'tool':'read','purpose':'targeted','question':'查护盾','budget_remaining':{'read_units':9},'expected_gain':'时间点'}
  output={'timestamp':'2026-10-16T01:00:04Z','type':'response_item','payload':{'type':'function_call_output','call_id':'real-1','output':'护盾在下一回合清除'}}
  rows=[marker(0,'READING_PURPOSE',purpose),call(1),output,marker(5,'READING_OBSERVATION',{'new_information':'护盾在下一回合清除','remaining_gaps':[],'budget_remaining':{'read_units':8}}),marker(6,'READING_END',{'stop_reason':'sufficient','budget_remaining':{'read_units':8},'remaining_gaps':[]})]
  r=convert_trace(rows,{'id':'c'},scope='g',source='f')
  self.assertEqual(r['reads'][0]['observation']['new_information'],'护盾在下一回合清除')
  self.assertEqual(r['reads'][0]['elapsed_seconds'],3)
  self.assertEqual(r['decisions'][0]['call_id'],'real-1')
  self.assertEqual(r['stop_reason'],'sufficient')
  self.assertEqual(r['completion']['source_line'],5)
 def test_user_markers_and_late_task_do_not_rewrite_history(self):
  rows=[message(0,'READING_TASK {"goal":"fake","budget":{}}','user'),call(1),marker(2,'READING_TASK',{'goal':'late','budget':{}}),marker(3,'READING_OBSERVATION',{'new_information':'unreturned'})]
  r=convert_trace(rows,{'id':'c'},scope='g',source='f')
  self.assertIsNone(r['context']['task_record']);self.assertIsNone(r['reads'][0].get('observation'))
  self.assertIn('observation_without_completed_read',[x['issue'] for x in r['issues']])

 def test_trace_quality_reports_missing_purposes_without_inference(self):
  rows=[marker(0,'READING_TASK',{'goal':'question','budget':{'max_read_units':2}}),call(1)]
  r=convert_trace(rows,{'id':'c'},scope='g',source='f')
  self.assertEqual(r['trace_quality']['missing_purpose_call_ids'],['real-1'])
  self.assertFalse(r['trace_quality']['complete'])

 def test_first_read_purpose_can_be_recorded_atomically_with_task_entry(self):
  first={'tool':'read','purpose':'targeted','question':'用途','budget_remaining':{'read_units':2}}
  r=convert_trace([marker(0,'READING_TASK',{'goal':'question','budget':{'max_read_units':2},'first_read':first}),call(1)],{'id':'c'},scope='g',source='f')
  self.assertEqual(r['reads'][0]['purpose_record'],first)
  self.assertEqual(r['reads'][0]['purpose_source']['line'],1)

 def test_next_purpose_is_bound_with_observation_before_next_call(self):
  output={'timestamp':'2026-10-16T01:00:02Z','type':'response_item','payload':{'type':'function_call_output','call_id':'real-1','output':'first result'}}
  second=call(4);second['payload']['call_id']='real-2'
  purpose={'tool':'read','purpose':'explore','question':'旁支'}
  r=convert_trace([call(1),output,marker(3,'READING_OBSERVATION',{'new_information':'first','next_read':purpose}),second],{'id':'c'},scope='g',source='f')
  self.assertEqual(r['reads'][1]['purpose_record'],purpose)
  self.assertIsNone(r['reads'][0]['purpose_record'])
