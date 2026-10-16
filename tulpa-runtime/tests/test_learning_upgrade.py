import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
class LearningUpgrade(unittest.TestCase):
 def test_sparse_coverage_preserves_missing_slots_and_never_claims_continuous_viewing(self):
  from daily_video import frame_coverage
  meta={'duration_seconds':100,'range':{'start_seconds':0,'end_seconds':100},'selection':[{'time':5,'status':'ok'},{'time':95,'status':'missing'}]}
  c=frame_coverage({'status':'ok','images':[{'path':'a'}],'timeline':[json.dumps(meta)]})
  self.assertEqual(c['status'],'partial');self.assertFalse(c['continuous']);self.assertEqual(c['missing_slots'],1)
  self.assertEqual(frame_coverage({'status':'ok','images':[{}],'timeline':['00:01–01:33']})['status'],'unknown')
 def test_learning_gets_sparse_images_before_first_model_decision(self):
  from video_exploration_runtime import read_exploration
  with tempfile.TemporaryDirectory() as t:
   calls=[]
   def decide(state,remaining):
    self.assertEqual(state['reads'][0]['action']['kind'],'grids')
    self.assertEqual(state['reads'][0]['result']['images'][0]['path'],'fixture')
    return {'action':None,'sufficient':True,'no_unread_material':True}
   result=read_exploration('v',{'materials':{'description':{'data':{'title':'test'}}}},Path(t)/'run',{'task_mode':'learning','force_sparse_overview':True,'exploration':{'exploration_budget_ratio':0}},decide=decide,reader=lambda a,r:(calls.append(a) or {'status':'ok','images':[{'path':'fixture'}]}),overview_reader=lambda *a:{})
   self.assertEqual(result['stop_reason'],'sufficient');self.assertEqual(len(calls),1)
 def test_review_emits_approval_requests_without_applying_changes(self):
  from reading_review import review_readings
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'input.json';p.write_text('{"reads":[]}')
   result=review_readings([p],Path(t)/'review',lambda *a:{'reads':[]},lambda *a:{'scores':{'purpose_deviation':0,'exploration_insufficient':2,'targeted_insufficient':1},'findings':[],'recommendations':['adjust exploration budget'],'limitations':[]})
   self.assertFalse(result['parameters_applied']);requests=json.loads((Path(result['directory'])/'change-requests.json').read_text());self.assertEqual(requests[0]['status'],'pending_controller_review')
if __name__=='__main__':unittest.main()
