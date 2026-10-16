import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from creator_learning import CreatorCollector
NOW=1800000000
class Feed:
    def __init__(self):self.round=0;self.checked=[];self.reads=[]
    def catalog(self,a,section,cursor=None):
        return {'items':[] if section=='dynamics' or self.round else [dict(id='v:BV1234567890',published_at=NOW-900000,row={'bvid':'BV1234567890'})]}
    def parts(self,bvid):
        self.checked.append(bvid)
        return {'bvid':bvid,'pages':[{'page':1,'cid':10,'ctime':NOW-900000},
          {'page':2 if self.round==0 else 3,'cid':20,'ctime':NOW-30},
          {'page':3 if self.round==0 else 2,'cid':30,'ctime':NOW-60},
          {'page':4,'cid':40,'ctime':None}]+([{'page':5,'cid':50,'ctime':NOW+86300}] if self.round else [])}
    def read(self,item):
        self.reads.append(item)
        return {'status':'ok','text':'content','sources':[item['row']['source_url']]}
class Multipart(unittest.TestCase):
    def test_legacy_first_part_receipt_is_not_relearned_or_rewritten(self):
        class Legacy:
            def catalog(self,a,section,cursor=None):
                return {'items':[] if section=='dynamics' else [dict(id='v:BV1234567890',published_at=NOW-1)]}
            def read(self,item):
                return {'status':'ok','scope':'part_1_subtitles','metadata':{'bvid':'BV1234567890','pages':[{'page':1,'cid':20},{'page':2,'cid':30}]}}
        with tempfile.TemporaryDirectory() as t:
            c=CreatorCollector(t,{})
            old=c.run([{'uid':1,'enabled':True}],Legacy(),NOW)
            receipt=Path(old['run'])/'records.json';before=receipt.read_bytes()
            result=c.run([{'uid':1,'enabled':True}],Feed(),NOW+86400)
            self.assertEqual([x['content_id'] for x in result['materials']],['v:BV1234567890:cid:30'])
            self.assertEqual(receipt.read_bytes(),before)

    def test_scan_caps_and_known_multipart_rotation(self):
        class Many(Feed):
            def catalog(self,a,section,cursor=None):
                return {'items':[] if section=='dynamics' else [dict(id='v:BV'+str(i+self.round*100),published_at=NOW-i,row={}) for i in range(40)]}
        with tempfile.TemporaryDirectory() as t:
            f=Many();c=CreatorCollector(t,{})
            c.run([{'uid':1,'enabled':True}],f,NOW)
            self.assertEqual(len(f.checked),20)
            f.round=1;f.checked=[]
            second=c.run([{'uid':1,'enabled':True}],f,NOW+86400)
            self.assertEqual(len(f.checked),30)
            self.assertEqual(len(set(f.checked)),30)
            self.assertEqual(len(second['materials']),2)
            f.round=2;f.checked=[]
            c2=CreatorCollector(t,{'latest_video_check_limit':2,'video_check_limit':3})
            c2.run([{'uid':1,'enabled':True}],f,NOW+172800)
            self.assertEqual(len(f.checked),3)

    def test_selected_part_reaches_real_provider_and_daily_video_input(self):
        from bilibili_creator_provider import BilibiliProvider
        from daily_video import enrich_videos
        from unittest.mock import patch
        from types import SimpleNamespace
        requests=[]
        def transport(cmd,**kw):
            r=json.loads(kw['input']);requests.append(r)
            if r['name']=='get_bilibili_creator_content':
                data={r['arguments']['section']:([dict(bvid='BV1234567890',published_at='2020-01-01T00:00:00Z')] if r['arguments']['section']=='videos' else [])}
            elif r['name']=='get_video_metadata':
                data={'bvid':'BV1234567890','pages':[{'page':1,'cid':10,'ctime':NOW-900000},{'page':7,'cid':70,'ctime':NOW-1}]}
            else:
                self.assertEqual(r['name'],'get_video_transcript');self.assertEqual(r['arguments']['page'],7)
                data={'transcript':'第七 P 字幕','page':7}
            return SimpleNamespace(returncode=0,stdout=json.dumps({'status':'ok','data':data}))
        with tempfile.TemporaryDirectory() as t,patch('subprocess.run',side_effect=transport):
            result=CreatorCollector(t,{}).run([{'uid':1,'enabled':True}],BilibiliProvider({'node':'node','call_script':'call.mjs'}),NOW)
            self.assertEqual(result['materials'][0]['content']['text'],'第七 P 字幕')
            videos=[]
            def context(url):videos.append(url);return {'source_url':url,'missing':[]}
            def frames(url,folder,count):videos.append(url);return {'status':'error','images':[]}
            enrich_videos({'creators':result['materials']},Path(t)/'learning',{'enabled':True},context_reader=context,frame_reader=frames)
            self.assertEqual(videos,['https://www.bilibili.com/video/BV1234567890/?p=7']*2)

    def test_old_bv_new_parts_sorted_by_time_and_revisited_after_catalog_disappears(self):
        with tempfile.TemporaryDirectory() as t:
            feed=Feed();c=CreatorCollector(t,{})
            first=c.run([{'uid':1,'enabled':True}],feed,NOW)
            self.assertEqual([x['content_id'] for x in first['materials']],['v:BV1234567890:cid:20','v:BV1234567890:cid:30'])
            self.assertEqual(feed.reads[0]['page'],2)
            self.assertIn('p=2',first['materials'][0]['content']['sources'][0])
            self.assertEqual(first['accounts'][0]['part_scan']['unknown_time'][0]['cid'],40)
            feed.round=1
            second=CreatorCollector(t,{}).run([{'uid':1,'enabled':True}],feed,NOW+86400)
            self.assertEqual([x['content_id'] for x in second['materials']],['v:BV1234567890:cid:50'])
            self.assertEqual(len(feed.checked),2)
if __name__=='__main__':unittest.main()
