import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from local_knowledge import Knowledge

def page(root,path,text):
    p=Path(root)/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')

class KnowledgeScope(unittest.TestCase):
    def test_startup_includes_only_root_index_and_member_map(self):
        from startup_knowledge import render
        with tempfile.TemporaryDirectory() as t:
            page(t,'INDEX.md','总索引 [UP](creators.md)')
            page(t,'group-memory/1/2/INDEX.md','成员简表 member-7 1000000005')
            page(t,'creators.md','创作者完整资料')
            page(t,'group-memory/1/2/members/1000000005.md','详细画像正文')
            page(t,'learning.sqlite3','学习数据库内容')
            result=render(t,'1','2')
            self.assertIn('总索引',result);self.assertIn('成员简表',result)
            for excluded in ['创作者完整资料','详细画像正文','学习数据库内容']:
                self.assertNotIn(excluded,result)

    def test_current_member_and_creators_readable_other_group_excluded(self):
        with tempfile.TemporaryDirectory() as t:
            page(t,'INDEX.md','总索引')
            page(t,'creators.md','固定UP 里雪りあ')
            page(t,'group-memory/1/2/INDEX.md','member-7 1000000005')
            path='group-memory/1/2/members/1000000005.md'
            page(t,path,'member-7 B站 UID 3000000007')
            page(t,'group-memory/1/3/members/other.md','其他群 member-7')
            k=Knowledge(t,account='1',group='2')
            self.assertTrue(k.read('creators.md')['found'])
            self.assertEqual(k.read(path)['text'],'member-7 B站 UID 3000000007')
            self.assertFalse(k.read('group-memory/1/3/members/other.md')['found'])
            self.assertEqual({x['path'] for x in k.search('member-7')['results']},{path,'group-memory/1/2/INDEX.md'})

if __name__=='__main__':unittest.main()
