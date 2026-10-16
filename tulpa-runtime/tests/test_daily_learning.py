import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from daily_learning import Learning
class Materials(unittest.TestCase):
 def test_seven_days_same_group_across_session_reload_and_search(self):
  with tempfile.TemporaryDirectory() as t:
   k=Learning(t,'1000000011','2000000001');now=1800000000
   k.collect([{'id':'old','at':now-604801,'text':'old','session':'a'},{'id':'a','at':now-604799,'text':'hello','session':'a'},{'id':'b','at':now-2,'text':'world','session':'b'}],[],now)
   k.record_search('b','缺少术语含义','查得释义',['https://example.com'],now)
   b=k.prepare(now)
   self.assertEqual([x['id'] for x in b['messages']],['a','b'])
   self.assertEqual(b['searches'][0]['message_id'],'b')
   self.assertEqual(k.prepare(now)['searches'],b['searches'])
class Daily(unittest.TestCase):
 def test_daily_once_clean_publish_and_independent_evidence(self):
  with tempfile.TemporaryDirectory() as t:
   k=Learning(t,'1000000011','2000000001');now=1800000000
   k.collect([{'id':'x','at':now-1,'text':'都查我病历了是吧','sender':'123','session':'one'}],[],now)
   calls=[]
   def model(batch,run):
    calls.append(str(run))
    return {'expressions':[{'situation':'被看穿习惯','surface_form':'都查我病历了是吧','style':'自嘲','source_ids':['x'],'evidence_quote':'都查我病历了是吧','assessment':'有原话'}],'meanings':[]}
   first=k.run(model,now);second=k.run(model,now+30)
   self.assertEqual(len(calls),1)
   self.assertEqual(second['state'],'already_completed')
   clean=k.read('病历');self.assertEqual(len(clean['expressions']),1)
   self.assertNotIn('source_ids',clean['expressions'][0]);self.assertNotIn('assessment',str(clean))
   self.assertTrue((Path(first['run'])/'review'/'candidates.json').exists())
   later=k.run(model,now+86400)
   self.assertNotEqual(first['run'],later['run'])
   self.assertEqual(k.read('病历'),clean)
class Validation(unittest.TestCase):
 def test_later_search_keeps_original_message_after_cursor(self):
  with tempfile.TemporaryDirectory() as t:
   k=Learning(t,'1000000011','2000000001');now=1800000000
   k.collect([{'id':'x','at':now-5,'text':'what is foo'}],[],now)
   k.run(lambda b,r:{'expressions':[],'meanings':[]},now)
   k.record_search('x','foo meaning','foo is bar',['https://example.com'],now+2)
   self.assertEqual(k.prepare(now+3)['messages'][0]['id'],'x')

 def test_cross_group_and_expired_material_not_learned(self):
  with tempfile.TemporaryDirectory() as t:
   k=Learning(t,'1000000011','2000000001');now=1800000000
   k.collect([{'id':'x','at':now,'text':'wrong group','group':'other'},{'id':'y','at':now,'text':'bot','is_self':True}],[],now)
   self.assertEqual(k.prepare(now)['messages'],[])
   with self.assertRaises(ValueError):k.record_search('x','gap','result',['https://example.com'],now)
 def test_raw_run_material_expires_but_published_content_remains(self):
  with tempfile.TemporaryDirectory() as t:
   k=Learning(t,'1000000011','2000000001');now=1800000000
   k.collect([{'id':'x','at':now-1,'text':'hello'}],[],now)
   run=k.run(lambda b,r:{'expressions':[],'meanings':[]},now)['run']
   k.collect([],[],now+604801)
   self.assertFalse((Path(run)/'input/messages.jsonl').exists())
   self.assertTrue((Path(run)/'apply.json').exists())
 def test_invalid_source_is_not_published(self):
  with tempfile.TemporaryDirectory() as t:
   k=Learning(t,'1000000011','2000000001');now=1800000000
   k.collect([{'id':'x','at':now-1,'text':'hello'}],[],now)
   def model(batch,run):return {'expressions':[{'source_ids':['invented'],'assessment':'test'}],'meanings':[]}
   result=k.run(model,now);self.assertEqual(result['accepted']['expressions'],0)
   self.assertEqual(k.read()['expressions'],[])
if __name__=='__main__':unittest.main()
