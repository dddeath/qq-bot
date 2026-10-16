import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from video_exploration_runtime import read_exploration

class ReadingPurposeTests(unittest.TestCase):
 def test_overview_precedes_decision_and_uses_learning_topic(self):
  with tempfile.TemporaryDirectory() as t:
   events=[]
   def overview(video,remaining):
    events.append('overview')
    return {'materials':{'description':{'status':'ok','data':{'title':'角色技能测评','owner':{'name':'作者'},'desc':'机制','pages':[{'page':1,'duration':90}]}},'chapters':{'status':'ok','data':[]},'subtitles':{'status':'unavailable'}}}
   def decide(s,remaining):
    events.append('decide')
    self.assertEqual(s['context']['purpose_anchor'],'角色技能测评')
    self.assertEqual(s['context']['overview']['materials']['chapters']['status'],'ok')
    self.assertGreater(s['budget']['remaining_seconds'],0)
    self.assertEqual(s['budget']['remaining_decisions'],12)
    return dict(sufficient=True,no_unread_material=True,action=None)
   r=read_exploration('v',{},Path(t)/'run',{'task_mode':'learning'},decide=decide,overview_reader=overview)
   self.assertEqual(events,['overview','decide'])
   self.assertEqual(r['stop_reason'],'sufficient')
   self.assertEqual(r['budget']['targeted_used'],0)
 def test_targeted_requires_anchor_relation_and_explore_parent_is_traced(self):
  from video_exploration import explore_video
  with tempfile.TemporaryDirectory() as t:
   calls=[]
   def decide(s,remaining):
    if not s['reads']:return dict(action={'kind':'comments','purpose':'explore'},purpose_record={'question':'顺便看昵称','relation':'unrelated','relation_reason':'旁支','parent_read':None,'expected_gain':'社区用法'},observation='')
    return dict(action={'kind':'comments','purpose':'targeted','page':2},purpose_record={'question':'继续查昵称','relation':'unrelated','relation_reason':'仍为旁支','parent_read':1,'expected_gain':'昵称来历'},observation='出现昵称')
   r=explore_video('v',{'purpose_anchor':'解释技能'},Path(t)/'run',{'purpose_contract':True},decide,lambda a,t:calls.append(a) or {'status':'ok'})
   self.assertEqual(len(calls),1)
   self.assertEqual(r['stop_reason'],'purpose_mismatch')
   self.assertEqual(r['reads'][0]['purpose_record']['question'],'顺便看昵称')

 def test_budget_exhaustion_not_reported_as_sufficient(self):
  from video_exploration import explore_video
  with tempfile.TemporaryDirectory() as t:
   r=explore_video('v',{},Path(t)/'run',{'max_read_units':1,'exploration_budget_ratio':0},lambda s,t:dict(action={'kind':'comments','purpose':'targeted'}),lambda a,t:dict(status='ok'))
   self.assertEqual(r['stop_reason'],'read_budget_exhausted')
   self.assertEqual(len(r['decisions']),1)
 def test_description_and_chapters_can_be_exploratory_or_targeted(self):
  from video_exploration import explore_video
  with tempfile.TemporaryDirectory() as t:
   for i,kind in enumerate(('description','chapters')):
    r=explore_video('v',{},Path(t)/str(i),{'max_read_units':1,'exploration_budget_ratio':1},lambda s,t:dict(action={'kind':kind,'purpose':'explore'}),lambda a,t:{'status':'ok'})
    self.assertEqual(len(r['reads']),1)
    self.assertEqual(r['budget']['exploration_used'],1)
 def test_chapter_overviews_share_global_budget_and_keep_purpose(self):
  from video_exploration import explore_video
  with tempfile.TemporaryDirectory() as t:
   def decide(s,t):
    i=len(s['reads'])
    return {'action':{'kind':'chapter_grid','purpose':'targeted','start_seconds':100+i*100,'end_seconds':190+i*100,'chapter_title':'机制','chapter_source':'inferred'}}
   r=explore_video('v',{'preflight':{'duration_seconds':1000}},Path(t)/'run',{},decide,lambda a,t:{'status':'ok'})
   self.assertEqual(len(r['reads']),2)
   self.assertEqual(r['budget']['chapter_reads_used'],2)
   self.assertEqual(r['stop_reason'],'visual_budget_exhausted')
