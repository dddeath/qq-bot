import sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from video_exploration import explore_video
from unittest.mock import patch

class ExplorationTests(unittest.TestCase):
    def test_segment_transport_returns_timed_images_to_model_after_sparse_grid(self):
        from video_exploration_runtime import read_exploration
        import json
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as t:
            def decide(s,remaining):
                n=len(s['reads'])
                if n==0:return dict(purpose_record=dict(question='定位操作',relation='high',relation_reason='回答视频操作问题',parent_read=None,expected_gain='操作位置'),action=dict(kind='grids',purpose='targeted'))
                if n==1:return dict(purpose_record=dict(question='核对变化',relation='high',relation_reason='回答视频操作问题',parent_read=1,expected_gain='变化过程'),action=dict(kind='frames',purpose='targeted',start_seconds=40,end_seconds=42,interval_seconds=1))
                self.assertEqual(s['reads'][1]['result']['images'][0]['requested_at_seconds'],40)
                return dict(sufficient=True,no_unread_material=True,action=None)
            def transport(cmd,**kw):
                req=json.loads(kw['input']);out=Path(req['output']);out.mkdir(parents=True)
                if req['kind']=='frames':
                    self.assertEqual([req[k] for k in ('start_seconds','end_seconds','interval_seconds')],[40,42,1])
                im=out/'frame.png';im.write_bytes(b'fixture')
                return SimpleNamespace(returncode=0,stdout=json.dumps(dict(status='ok',images=[dict(path=str(im),requested_at_seconds=40)])))
            with patch('subprocess.run',side_effect=transport):
                r=read_exploration('v?p=4',{},Path(t)/'run',{},decide=decide)
            self.assertEqual(r['stop_reason'],'sufficient')
            self.assertEqual(len(r['reads']),2)

    def test_visual_budget_bounds_segments_and_cumulative_frames_before_transport(self):
        with tempfile.TemporaryDirectory() as t:
            calls=[]
            def decide(s,remaining):
                start=len(s['reads'])*10
                return dict(action=dict(kind='frames',purpose='targeted',start_seconds=start,end_seconds=start+7,interval_seconds=1))
            r=explore_video('v',{},Path(t)/'run',{},decide,lambda a,t:calls.append(a) or dict(status='error'))
            self.assertEqual(len(calls),3)
            self.assertEqual(r['stop_reason'],'visual_budget_exhausted')
            self.assertEqual(r['budget']['sampled_frames_used'],24)
            for i,action in enumerate([dict(kind='frames',purpose='targeted',start_seconds=0,end_seconds=13,interval_seconds=2),dict(kind='frames',purpose='targeted',start_seconds=0,end_seconds=8,interval_seconds=1)]):
                r=explore_video('v',{},Path(t)/str(i),{},lambda s,t:dict(action=action),lambda a,t:self.fail('over-budget read'))
                self.assertEqual(r['stop_reason'],'visual_budget_exhausted')

    def test_model_contract_exposes_only_fields_supported_by_each_read_action(self):
        from video_exploration_runtime import decision_schema
        variants=decision_schema()['properties']['action']['anyOf']
        actions={v['properties']['kind']['enum'][0]:v for v in variants if v.get('type')=='object'}
        self.assertEqual(set(actions),{'chapter_grid','description','chapters','comments','subtitles','danmaku','grids','frame','frames'})
        self.assertEqual(set(actions['grids']['properties']),{'kind','purpose'})
        self.assertEqual(set(actions['frames']['properties']),{'kind','purpose','start_seconds','end_seconds','interval_seconds'})
        self.assertFalse(actions['frames']['additionalProperties'])
        self.assertEqual(actions['frames']['properties']['interval_seconds']['minimum'],0.25)

    def test_transport_reads_selected_thread_and_returns_material_to_next_decision(self):
        from video_exploration_runtime import read_exploration
        from types import SimpleNamespace
        import json
        with tempfile.TemporaryDirectory() as t:
            def decide(s,t):
                if not s['reads']:return dict(purpose_record=dict(question='查回复承接',relation='high',relation_reason='社区用法目标',parent_read=None,expected_gain='解释'),sufficient=False,action=dict(kind='comments',purpose='targeted',root_id='123',page=2))
                self.assertEqual(s['reads'][0]['result']['data']['items'][0]['parent_id'],'124')
                return dict(sufficient=True,no_unread_material=True,reason='后续回复解释为反讽',action=None)
            def transport(cmd,**kw):
                request=json.loads(kw['input'])
                self.assertEqual(request['name'],'get_video_comment_threads')
                self.assertEqual(request['arguments'],{'bvid_or_url':'https://www.bilibili.com/video/BV1KXYc6aEFR/?p=2','root_id':'123','page':2,'page_size':10})
                self.assertLessEqual(kw['timeout'],300)
                return SimpleNamespace(returncode=0,stdout=json.dumps({'status':'ok','data':{'items':[{'id':'125','root_id':'123','parent_id':'124','text':'反话[doge]'}]}}))
            with patch('subprocess.run',side_effect=transport):
                r=read_exploration('https://www.bilibili.com/video/BV1KXYc6aEFR/?p=2',{'page':2},Path(t)/'run',{'bilibili_provider':{'node':'node','call_script':'call.mjs'}},decide=decide)
            self.assertEqual(r['stop_reason'],'sufficient')
            self.assertEqual(r['decisions'][-1]['reason'],'后续回复解释为反讽')
    def test_failed_read_spends_one_unit_and_ratio_zero_allows_stop(self):
        with tempfile.TemporaryDirectory() as t:
            def fail(a,t):raise RuntimeError('read timeout')
            def decide(s,t):
                return dict(sufficient=bool(s['reads']),action=None if s['reads'] else dict(kind='comments',purpose='explore',page=2))
            r=explore_video('v',{},Path(t)/'failure',{},decide,fail)
            self.assertEqual(r['budget']['exploration_used'],1)
            self.assertEqual(r['reads'][0]['result']['status'],'error')
            r=explore_video('v',{},Path(t)/'zero',{'exploration_budget_ratio':0},lambda s,t:dict(sufficient=True,action=None),lambda a,t:self.fail('unexpected read'))
            self.assertEqual(r['stop_reason'],'sufficient')
            self.assertEqual(len(r['reads']),0)
    def test_daily_exploration_checks_sparse_result_before_further_model_reading(self):
        from daily_video import enrich_videos
        with tempfile.TemporaryDirectory() as t:
            batch={'creators':[dict(id='x',content_id='v:BV1KXYc6aEFR',content={'sources':['https://www.bilibili.com/video/BV1KXYc6aEFR/?p=2']})]}
            def decide(state,remaining):
                self.assertEqual(state['context']['page'],2)
                self.assertEqual(state['reads'][0]['action']['kind'],'grids')
                return dict(sufficient=True,reason='字幕足够',action=None,no_unread_material=True)
            result=enrich_videos(batch,Path(t),{'enabled':True,'exploration':{'enabled':True}},
                context_reader=lambda v:{'page':2,'materials':{'description':{'data':{'title':'学习主题'}}},'missing':[]},
                frame_reader=lambda *a:self.fail('legacy reader not used'),decision_maker=decide,exploration_reader=lambda a,t:{'status':'error','images':[]})
            self.assertEqual(result,[])
            self.assertEqual(batch['creators'][0]['video_reading']['exploration']['stop_reason'],'sufficient')
    def test_sufficient_text_still_gets_reserved_exploration_without_downloading(self):
        def decide(state,remaining):
            if not state['reads']:
                return dict(sufficient=True,reason='字幕已解释，但抽查另一页评论',action={'kind':'comments','purpose':'explore','page':2})
            return dict(sufficient=True,reason='未发现新线索',action=None)
        def read(action,remaining):
            self.assertEqual(action['kind'],'comments')
            return dict(status='ok',items=[{'text':'新评论'}])
        with tempfile.TemporaryDirectory() as t:
            r=explore_video('BV1KXYc6aEFR',{'materials':{}},Path(t)/'run',{},decide,read)
            self.assertEqual(r['budget']['exploration_limit'],2)
            self.assertEqual(r['budget']['exploration_used'],1)
            self.assertEqual(r['stop_reason'],'sufficient')
            self.assertEqual(r['reads'][0]['action']['page'],2)
            self.assertTrue((Path(t)/'run/report.json').exists())

    def test_targeted_and_exploration_pools_cannot_spend_each_other_and_repeats_cost_nothing(self):
        with tempfile.TemporaryDirectory() as t:
            n=[0]
            def decide(state,remaining):
                n[0]+=1
                return dict(sufficient=False,reason='继续补读',action=dict(kind='comments',purpose='targeted',page=n[0]))
            r=explore_video('BV1KXYc6aEFR',{},Path(t)/'run',{'max_read_units':5},decide,lambda a,t:{'status':'ok'})
            self.assertEqual(len(r['reads']),4)
            self.assertEqual(r['budget']['targeted_used'],4)
            self.assertEqual(r['stop_reason'],'purpose_budget_exhausted')
            r=explore_video('BV1KXYc6aEFR',{},Path(t)/'repeat',{},lambda s,t:dict(sufficient=False,action=dict(kind='comments',purpose='explore',page=2)),lambda a,t:{'status':'ok'})
            self.assertEqual(len(r['reads']),1)
            self.assertEqual(r['stop_reason'],'duplicate_read')

    def test_stop_before_exploration_reprompts_and_timeout_or_failure_is_recorded(self):
        with tempfile.TemporaryDirectory() as t:
            def decide(s,remaining):
                if s.get('exploration_required'):
                    return dict(sufficient=True,action={'kind':'comments','purpose':'explore','page':2})
                return dict(sufficient=True,action=None)
            r=explore_video('BV1KXYc6aEFR',{},Path(t)/'explore',{},decide,lambda a,t:{'status':'ok'})
            self.assertEqual(len(r['reads']),1)
            clock=[0]
            def slow(s,remaining):
                clock[0]=301
                return dict(sufficient=False,action={'kind':'grids','purpose':'targeted'})
            r=explore_video('BV1KXYc6aEFR',{},Path(t)/'timeout',{},slow,lambda a,t:self.fail('expired read'),now=lambda:clock[0])
            self.assertEqual(r['stop_reason'],'timeout')
            def broken(s,t):raise RuntimeError('model unavailable')
            r=explore_video('BV1KXYc6aEFR',{},Path(t)/'failure',{},broken,lambda a,t:{})
            self.assertEqual(r['stop_reason'],'decision_failed')
            self.assertTrue((Path(t)/'failure/report.json').exists())

    def test_invalid_configuration_and_actions_do_not_read(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError):
                explore_video('BV1KXYc6aEFR',{},Path(t)/'bad',{'exploration_budget_ratio':1.1},lambda s,t:{},lambda a,t:{})
            r=explore_video('BV1KXYc6aEFR',{},Path(t)/'action',{},lambda s,t:dict(action={'kind':'shell','purpose':'targeted'}),lambda a,t:self.fail('unexpected read'))
            self.assertEqual(r['stop_reason'],'invalid_action')

    def test_selected_images_feed_next_decision_and_daily_attachments_with_original_text(self):
        from daily_video import enrich_videos
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);image=root/'sample.png';image.write_bytes(b'fixture-image')
            batch={'creators':[dict(id='x',content_id='v:BV1KXYc6aEFR',content={'text':'已有原文'})]}
            def decide(s,remaining):
                if not s['reads']:return dict(purpose_record=dict(question='查看技能',relation='high',relation_reason='技能测评主题',parent_read=None,expected_gain='技能文字'),sufficient=False,action=dict(kind='grids',purpose='targeted'))
                self.assertEqual(s['reads'][0]['result']['images'][0]['path'],str(image))
                return dict(sufficient=True,reason='画面中的技能文字',no_unread_material=True,action=None)
            r=enrich_videos(batch,root,{'enabled':True,'exploration':{'enabled':True}},context_reader=lambda v:{'materials':{'description':{'status':'ok','data':{'title':'技能测评'}}},'missing':[]},
                decision_maker=decide,exploration_reader=lambda a,t:{'status':'ok','images':[{'path':str(image)}],'timeline':['00:12']})
            self.assertEqual(r,[str(image)])
            self.assertEqual(batch['creators'][0]['content']['text'],'已有原文')
            self.assertEqual(batch['creators'][0]['video_reading']['frames']['images'][0]['attachment_number'],1)

    def test_real_transport_contract_disables_tools_and_attaches_previous_images(self):
        from video_exploration_runtime import make_decider
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'config.toml').write_text('[mcp_servers.qq]\ncommand="unused"')
            image=root/'frame.png';image.write_bytes(b'fixture-image')
            class Process:
                returncode=0
                def __init__(proc,cmd,**kwargs):
                    self.assertIn('mcp_servers.qq.enabled=false',cmd)
                    self.assertIn(str(image),cmd)
                    proc.folder=kwargs['cwd']
                def communicate(proc,prompt,timeout):
                    self.assertIn('评论承接',prompt)
                    (proc.folder/'answer.json').write_text(json.dumps(dict(sufficient=True,no_unread_material=True,reason='已核对',action=None)),encoding='utf-8')
            import json
            with patch.dict('os.environ',{'CODEX_HOME':str(root)}),patch('video_exploration_runtime.subprocess.Popen',Process):
                r=make_decider(root/'run')({'reads':[{'result':{'images':[{'path':str(image)}]}}],'context':'评论承接'},20)
            self.assertEqual(r['reason'],'已核对')
            self.assertTrue((root/'run/decision-01/execution-result.json').exists())

if __name__=='__main__':unittest.main()
