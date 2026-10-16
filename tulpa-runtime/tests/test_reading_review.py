import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
class ReviewTests(unittest.TestCase):
 def test_native_missing_purpose_is_not_scored(self):
  from reading_review import review_readings
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);src=root/'native.json'
   src.write_text(json.dumps({'native_thread_id':'child','reads':[{'purpose_record':None}]}))
   assessment={'scores':{'purpose_deviation':2,'exploration_insufficient':None,'targeted_insufficient':None},'findings':[]}
   r=review_readings([src],root/'reviews',lambda *a:{'reads':[]},lambda *a:assessment)
   self.assertIsNone(r['items'][0]['assessment']['scores']['purpose_deviation'])
   self.assertIn('No contemporaneous purpose records',r['items'][0]['assessment']['limitations'][0])
 def test_review_extends_independently_and_preserves_original(self):
  from reading_review import review_readings
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);src=root/'original.json';src.write_text(json.dumps({'video':'v','context':{'purpose_anchor':'技能'},'reads':[],'decisions':[]}));original=src.read_bytes()
   def extend(record,folder,limits):
    self.assertEqual(limits['max_read_units'],2)
    return {'reads':[{'read_id':1,'result':{'status':'ok','data':'发现核心机制'}}]}
   def judge(payload,remaining):
    return {'scores':{'purpose_deviation':0,'exploration_insufficient':1,'targeted_insufficient':2},'findings':[{'category':'targeted_insufficient','original_read_ids':[],'extension_read_ids':[1],'explanation':'补读发现核心机制','decision_assessment':'原材料已有线索'}],'recommendations':['优先核心机制'],'limitations':[]}
   a=review_readings([src],root/'reviews',extend,judge)
   b=review_readings([src],root/'reviews',extend,judge)
   self.assertNotEqual(a['directory'],b['directory'])
   self.assertEqual(src.read_bytes(),original)
   self.assertFalse(a['parameters_applied'])
   self.assertEqual(a['items'][0]['assessment']['scores']['targeted_insufficient'],2)
 def test_daily_selection_uses_record_time_and_scope_not_mtime(self):
  from reading_review_runtime import select_daily_reports
  with tempfile.TemporaryDirectory() as t:
   root=Path(t)
   for name,date,scope in [('today','2026-10-15T02:00:00+00:00','g1'),('old','2026-10-14T02:00:00+00:00','g1'),('other','2026-10-15T02:00:00+00:00','g2')]:
    d=root/name;d.mkdir();(d/'report.json').write_text(json.dumps({'recorded_at':date,'context':{'task_mode':'reading','audit_scope':scope}}))
   self.assertEqual([p.parent.name for p in select_daily_reports(root,'2026-10-15','g1')],['today'])
 def test_elapsed_review_budget_stops_before_scoring(self):
  from reading_review import review_readings
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);src=root/'original.json';src.write_text('{"reads":[]}');clock=[0]
   def extend(record,folder,limits):clock[0]=301;return {'reads':[]}
   r=review_readings([src],root/'reviews',extend,lambda *a:self.fail('budget exceeded'),now=lambda:clock[0])
   self.assertEqual(r['items'][0]['error'],'review_budget_exhausted')

 def test_invalid_evidence_reference_is_rejected(self):
  from reading_review import review_readings
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);src=root/'original.json';src.write_text('{"reads":[]}')
   assessment={'scores':{'purpose_deviation':1,'exploration_insufficient':0,'targeted_insufficient':0},'findings':[{'category':'purpose_deviation','original_read_ids':[99],'extension_read_ids':[]}]}
   r=review_readings([src],root/'reviews',lambda *a:{'reads':[]},lambda *a:assessment)
   self.assertEqual(r['items'][0]['error'],'invalid_evidence_reference')
