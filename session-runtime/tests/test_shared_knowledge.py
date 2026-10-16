import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tulpa-runtime'))
from local_knowledge import Knowledge

class SharedKnowledgeTest(unittest.TestCase):
 def test_same_domain_library_keeps_member_profiles_scoped(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   for name,text in [('INDEX.md','Domains'),('arknights/INDEX.md','Shared game facts'),('group-memory/1000000011/2000000001/INDEX.md','White dragon members'),('group-memory/1000000009/2000000003/INDEX.md','Gemini members')]:
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')
   a=Knowledge(root,'1000000011','2000000001');b=Knowledge(root,'1000000009','2000000003')
   self.assertEqual(a.read('arknights/INDEX.md')['text'],b.read('arknights/INDEX.md')['text'])
   self.assertEqual(b.read('group-memory/1000000009/2000000003/INDEX.md')['text'],'Gemini members')
   self.assertFalse(b.read('group-memory/1000000011/2000000001/INDEX.md')['found'])
