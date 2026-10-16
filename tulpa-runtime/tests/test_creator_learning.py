import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from creator_learning import CreatorCollector
from daily_learning import Learning
import json

NOW = 1800000000

class Feed:
    def catalog(self, account, section, cursor=None):
        if section == 'dynamics':
            return {'items':[{'id':'d:1','published_at':NOW-2,'text':'dynamic'}]}
        return {'items':[{'id':'v:1','published_at':NOW-1,'text':'video'},
                         {'id':'v:2','published_at':NOW-3,'text':'older video'},
                         {'id':'v:old','published_at':NOW-604801,'text':'expired'}]}
    def read(self, item):
        return {**item, 'status':'ok', 'sources':['https://example.com/'+item['id']]}

class Collection(unittest.TestCase):
    def test_newly_confirmed_account_can_join_without_refetching_existing_accounts(self):
        with tempfile.TemporaryDirectory() as t:
            c=CreatorCollector(t,{})
            c.run([{'uid':1,'enabled':True}],Feed(),NOW)
            second=c.run([{'uid':1,'enabled':True},{'uid':2,'enabled':True}],Feed(),NOW+5)
            self.assertEqual([x['creator']['uid'] for x in second['materials']],[2,2])
            self.assertEqual(c.run([{'uid':1,'enabled':True},{'uid':2,'enabled':True}],Feed(),NOW+10)['state'],'already_completed')
    def test_cap_across_sections_dedup_and_daily_claim(self):
        with tempfile.TemporaryDirectory() as t:
            c=CreatorCollector(t, {'lookback_days':7,'per_account_limit':2,'max_pages':1})
            accounts=[{'uid':1,'name':'creator','enabled':True}]
            first=c.run(accounts, Feed(), NOW)
            self.assertEqual([x['content_id'] for x in first['materials']], ['v:1','d:1'])
            self.assertEqual(c.run(accounts, Feed(), NOW+10)['state'],'already_completed')
            later=c.run(accounts, Feed(), NOW+86400)
            self.assertEqual([x['content_id'] for x in later['materials']], ['v:2'])
            self.assertNotEqual(first['run'], later['run'])

    def test_read_failures_and_catalog_truncation_are_recorded(self):
        class Broken(Feed):
            def catalog(self, account, section, cursor=None):
                if section=='dynamics': raise RuntimeError('ACCESS_DENIED')
                return {**super().catalog(account,section), 'next_cursor':'more'}
            def read(self,item): raise RuntimeError('removed')
        with tempfile.TemporaryDirectory() as t:
            c=CreatorCollector(t,{'per_account_limit':2,'max_pages':1})
            r=c.run([{'uid':1,'enabled':True}],Broken(),NOW)
            self.assertEqual(r['materials'],[])
            self.assertEqual([x['status'] for x in r['accounts'][0]['sections']],['truncated','error'])
            self.assertEqual([x['content']['status'] for x in r['records']],['read_failed','read_failed'])
            self.assertEqual(c.run([{'uid':1,'enabled':True}],Broken(),NOW+86400)['records'],[])

class Publication(unittest.TestCase):
    def test_existing_collection_is_delivered_after_restart_without_refetch(self):
        with tempfile.TemporaryDirectory() as t:
            c=CreatorCollector(Path(t)/'feeds',{})
            c.run([{'uid':1,'enabled':True}],Feed(),NOW)
            k=Learning(t,'bot','group')
            c.deliver(k,NOW+5)
            c.deliver(k,NOW+6)
            self.assertEqual(len(k.prepare(NOW+6)['creators']),2)
            self.assertEqual(k.prepare(NOW+6)['messages'],[])

    def test_creator_material_enters_daily_meanings_with_review_only_sources(self):
        with tempfile.TemporaryDirectory() as t:
            k=Learning(t,'bot','group')
            material=dict(id='bilibili:1:v:1',at=NOW-1,published_at=NOW-100,
                          creator={'uid':1,'name':'UP'},content={'text':'新赛季机制','sources':['https://example.com/v']})
            k.collect_creators([material],NOW)
            def model(batch,run):
                self.assertEqual(batch['creators'],[material])
                self.assertEqual(batch['messages'],[])
                return {'expressions':[], 'meanings':[dict(term='赛季机制',meaning='新机制说明',usage='讨论版本',conditions='当前版本',kind='fact',source_ids=[material['id']],assessment='UP公开内容')]}
            result=k.run(model,NOW)
            self.assertEqual(result['accepted']['meanings'],1)
            self.assertNotIn('sources',json.dumps(k.read()))
            evidence=json.loads((Path(result['run'])/'review/evidence.json').read_text(encoding='utf-8'))
            self.assertEqual(evidence[material['id']]['content']['sources'],['https://example.com/v'])
            self.assertTrue((Path(result['run'])/'input/creator-content.jsonl').exists())
            k.collect_creators([],NOW+604801)
            self.assertFalse((Path(result['run'])/'input/creator-content.jsonl').exists())

if __name__=='__main__': unittest.main()
