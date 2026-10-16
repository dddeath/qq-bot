import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from daily_learning import Learning
from daily_learning_worker import model
from daily_video import enrich_videos

PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5ioAAAAASUVORK5CYII='


class DailyVideo(unittest.TestCase):
    def test_production_reader_passes_selected_part_and_limits_to_both_transports(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as t:
            source='https://www.bilibili.com/video/BV1KXYc6aEFR/?p=2'
            batch={'creators':[dict(id='x',content_id='v:BV1KXYc6aEFR',content={'sources':[source]})]}
            requests=[]
            def transport(cmd,**kwargs):
                request=json.loads(kwargs['input']);requests.append(request)
                if 'name' in request:
                    self.assertEqual(request['name'],'get_video_context')
                    self.assertEqual(request['arguments']['bvid_or_url'],source)
                    self.assertEqual(request['arguments']['comment_limit'],4)
                    return SimpleNamespace(returncode=0,stdout=json.dumps({'status':'ok','data':{
                        'page':2,'source_url':source,'materials':{},'missing':['subtitles']}}))
                self.assertEqual(request['video'],source)
                self.assertEqual(request['count'],1)
                self.assertEqual(request['timeout_ms'],30000)
                return SimpleNamespace(returncode=0,stdout=json.dumps({'status':'error','error':'download_failed','images':[]}))
            settings={'enabled':True,'max_grids_per_video':1,'video_timeout_seconds':30,'comment_limit':4,
                      'bilibili_provider':{'node':'node','call_script':'call.mjs'}}
            with patch('subprocess.run',side_effect=transport):
                self.assertEqual(enrich_videos(batch,Path(t),settings),[])
            self.assertEqual(len(requests),2)
            self.assertEqual(batch['creators'][0]['video_reading']['missing'],['subtitles','frames'])

    def test_batch_budget_failures_and_missing_material_preserve_existing_text(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); calls=[]
            batch={'creators':[dict(id=str(i),content_id='v:BV'+str(i),content={'text':'原字幕'}) for i in range(5)]}
            def context(video):
                calls.append(video)
                if video.endswith('BV0/'):raise RuntimeError('ACCESS_DENIED')
                return {'missing':['subtitles'],'materials':{'subtitles':{'status':'error'}}}
            def frames(video,folder,count):
                self.assertEqual(count,2)
                if video.endswith('BV1/'):raise TimeoutError('frames timeout')
                folder.mkdir(parents=True)
                import base64
                paths=[]
                for i in range(4):
                    path=folder/f'{i}.png';path.write_bytes(base64.b64decode(PNG))
                    paths.append({'path':str(path),'mimeType':'image/png'})
                return {'status':'ok','images':paths,'timeline':['00:01']}
            images=enrich_videos(batch,root,{'enabled':True},context_reader=context,frame_reader=frames)
            self.assertEqual(len(calls),3)
            self.assertEqual(len(images),4)
            self.assertTrue(all(x['content']['text']=='原字幕' for x in batch['creators']))
            records=[x['video_reading'] for x in batch['creators']]
            self.assertEqual([x['status'] for x in records],['partial','partial','partial','skipped_budget','skipped_budget'])
            self.assertIn('text_context',records[0]['missing'])
            self.assertIn('frames',records[1]['missing'])
            self.assertIn('subtitles',records[2]['missing'])
            self.assertEqual(len(records[2]['frames']['images']),2)
            self.assertTrue(records[2]['frames']['truncated'])
            # A second invocation has its own configurable budget, including zero.
            other={'creators':[dict(id='x',content_id='v:BV9',content={})]}
            self.assertEqual(enrich_videos(other,root/'next',{'enabled':True,'max_videos_per_batch':0},context_reader=context,frame_reader=frames),[])
            self.assertEqual(len(calls),3)

    def test_video_material_and_real_image_bytes_reach_daily_model_and_audit(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root/'config.toml').write_text('[mcp_servers.qq]\ncommand="unused"', encoding='utf-8')
            k = Learning(root/'data', 'bot', 'group')
            creator = dict(id='bilibili:1:v:BV1KXYc6aEFR', content_id='v:BV1KXYc6aEFR', at=99,
                           content={'text':'已有字幕'}, creator={'uid':1})
            k.collect_creators([creator],100)
            def context(video):
                return dict(page=1,source_url=video,missing=[],materials={
                    'description':{'status':'ok','data':{'description':'作者简介'}},
                    'subtitles':{'status':'ok','data':{'transcript':'[00:12] 对白'}},
                    'comments':{'status':'ok','data':{'comments':[{'content':'观众解释'}]}},
                    'danmaku':{'status':'ok','data':{'items':[{'at_seconds':12,'text':'反差'}]}}})
            def frames(video, folder, count):
                import base64
                folder.mkdir(parents=True)
                image=folder/'grid.png';image.write_bytes(base64.b64decode(PNG))
                return dict(status='ok',images=[{'path':str(image),'mimeType':'image/png'}],
                            timeline=['Grid 1: 00:12, 00:24'])
            class Process:
                returncode=0
                def __init__(self,cmd,**kw):
                    self.cmd=cmd;self.cwd=kw['cwd']
                def communicate(proc,prompt,timeout):
                    self.assertIn('作者简介',prompt);self.assertIn('观众解释',prompt)
                    self.assertIn('00:24',prompt);self.assertIn('--image',proc.cmd)
                    image=Path(proc.cmd[proc.cmd.index('--image')+1])
                    self.assertEqual(image.read_bytes()[:8],b'\x89PNG\r\n\x1a\n')
                    self.assertIn('mcp_servers.qq.enabled=false',proc.cmd)
                    output=dict(expressions=[],meanings=[dict(term='反差',meaning='画面与对白的反差',
                        usage='讨论该片段',conditions='',kind='community',source_ids=[creator['id']],assessment='字幕与画面')])
                    (proc.cwd/'review/answer.json').write_text(json.dumps(output),encoding='utf-8')
            with patch.dict('os.environ',{'CODEX_HOME':str(root)}),patch('daily_learning_worker.subprocess.Popen',Process):
                result=k.run(lambda batch,run:model(batch,run,video_config={'enabled':True},
                    context_reader=context,frame_reader=frames),100)
            run=Path(result['run'])
            audit=json.loads((run/'review/evidence.json').read_text(encoding='utf-8'))
            self.assertEqual(audit[creator['id']]['video_reading']['status'],'partial')
            self.assertEqual(audit[creator['id']]['video_reading']['frames']['coverage']['status'],'unknown')
            self.assertTrue((run/'input/video-reading.json').exists())
            published=json.dumps(k.read(),ensure_ascii=False)
            for forbidden in ('source_ids','video_reading','grid.png','assessment'):
                self.assertNotIn(forbidden,published)
            image=next((run/'input/video').rglob('*.png'))
            k.collect_creators([],100+604801)
            self.assertFalse(image.exists())
            self.assertFalse((run/'input/video-reading.json').exists())
            self.assertTrue((run/'review/evidence.json').exists())


if __name__=='__main__':unittest.main()

