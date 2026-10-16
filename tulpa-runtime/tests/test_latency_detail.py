import unittest
from latency_detail import native_lifecycles, build_report, save_report
from tempfile import TemporaryDirectory
from pathlib import Path


def native(at, kind, **fields):
    return {'timestamp': at, 'type': 'response_item', 'payload': {'type': kind, **fields}}


class LifecycleTests(unittest.TestCase):
    def test_token_drop_does_not_invent_compaction(self):
        rows=[{'timestamp':1,'type':'event_msg','payload':{'type':'token_count','info':{'model_context_window':828400,'last_token_usage':{'input_tokens':10000}}}},
              {'timestamp':2,'type':'event_msg','payload':{'type':'token_count','info':{'model_context_window':828400,'last_token_usage':{'input_tokens':1000}}}}]
        r=native_lifecycles(rows)
        self.assertEqual(r['context_usage'][-1]['input_tokens'],1000)
        self.assertEqual(r['context_usage'][-1]['model_context_window'],828400)
        self.assertEqual(r['compaction_observation'],'not_observed')
    def test_reports_keep_receiver_only_and_are_independent(self):
        report=build_report([],inbox=[{'id':1,'session_id':'s','received_at':2}])
        self.assertEqual(report['messages'][0]['status'],'receiver_only')
        self.assertIsNone(report['messages'][0]['first_reply_s'])
        with TemporaryDirectory() as tmp:
            one=save_report(tmp,report); before={p.name:p.read_bytes() for p in one.iterdir()}
            two=save_report(tmp,report)
            self.assertNotEqual(one,two)
            self.assertEqual(before,{p.name:p.read_bytes() for p in one.iterdir()})
            self.assertIn('timeline.json',before)
            self.assertIn('report.md',before)
    def test_message_timeline_bubbles_and_overlap_not_double_counted(self):
        def e(at, typ, tool, ident, args, result=None):
            return {'observed_at':at,'event':{'type':typ,'item':{'id':ident,'tool':tool,'arguments':args,'result':{'structured_content':result or {}}}}}
        rows=[e(3,'item.completed','wait_chat_messages','w',{'session_id':'s'}, {'session_id':'s','messages':[
            {'id':1,'timestamp':1000,'received_at':2,'is_self':False},
            {'id':2,'timestamp':1000,'received_at':2,'is_self':False}]}),
            e(17,'item.completed','plan_chat_reply','old',{'session_id':'s','target_event_id':1},{'state':'REJECTED','error_code':'stale'}),
            e(18,'item.started','plan_chat_reply','p',{'session_id':'s','target_event_id':1}),
            e(19,'item.completed','plan_chat_reply','p',{'session_id':'s'}, {'plan_id':'p1','decision':{'target_event_id':1}}),
            e(20,'item.started','send_chat_reply','x',{'session_id':'s','plan_id':'p1'}),
            e(24,'item.completed','send_chat_reply','x',{'session_id':'s','plan_id':'p1'}, {'state':'SUCCEEDED','bubbles':[
                {'receipt':{'result':{'message_id':10,'timestamp':21}}},
                {'receipt':{'result':{'message_id':11,'timestamp':23}}}]})]
        native_rows=[native(4,'function_call',name='web.run',call_id='a',arguments='{}'),
                     native(6,'function_call',name='image_gen.imagegen',call_id='b',arguments='{}'),
                     native(10,'function_call_output',call_id='a',output='ok'),
                     native(12,'function_call_output',call_id='b',output='ok')]
        report=build_report(rows,native_rows,tail_seconds=10)
        m=report['messages'][0]
        self.assertEqual(m['first_reply_s'],20)
        self.assertEqual(m['last_reply_s'],22)
        self.assertEqual(m['tool_overlap_s'],8)
        self.assertEqual(m['timeline']['host_delivered'],3)
        self.assertEqual(len(m['replies']),2)
        self.assertIn('search_overlap',m['tail_labels'])
        self.assertIn('image_generation_overlap',m['tail_labels'])
        self.assertIn('stale_replanning',m['tail_labels'])
        self.assertEqual(m['plans'][0]['error_code'],'stale')
        self.assertEqual(report['messages'][1]['status'],'delivered_without_reply')
        self.assertEqual(report['summary']['first_reply_s']['p95'],20)

    def test_image_yield_and_wait_is_one_full_lifecycle(self):
        rows = [
            native(10, 'function_call', name='exec', call_id='a', arguments='await tools.image_gen__imagegen({prompt:"hi"})'),
            native(11, 'function_call_output', call_id='a', output='Script running with cell ID 7'),
            native(12, 'function_call', name='wait', call_id='b', arguments='{"cell_id":"7"}'),
            native(20, 'function_call_output', call_id='b', output='Script running with cell ID 7'),
            native(25, 'function_call', name='wait', call_id='c', arguments='{"cell_id":"7"}'),
            native(40, 'function_call_output', call_id='c', output=[{'type':'input_text','text':'Script completed'},{'type':'image','data':'OMITTED'}]),
        ]
        result = native_lifecycles(rows)
        self.assertEqual(len(result['tools']), 1)
        span = result['tools'][0]
        self.assertEqual((span['start'], span['end'], span['duration_s']), (10,40,30))
        self.assertEqual(span['status'], 'completed')
        self.assertEqual(span['wait_count'], 2)
        self.assertEqual(span['observation_gap_s'], 6)
        self.assertEqual([p['phase'] for p in span['phases']], ['request','yield','wait','yield','wait','result'])

    def test_scope_reset_incomplete_search_and_explicit_compaction(self):
        rows = [native(1,'function_call',name='exec',call_id='a',arguments='await tools.web__run({})'),
                native(2,'function_call_output',call_id='a',output='Script running with cell ID 7'),
                {'timestamp':3,'type':'event_msg','payload':{'type':'task_started'}},
                native(4,'function_call',name='wait',call_id='a',arguments='{"cell_id":"7"}'),
                native(5,'function_call_output',call_id='a',output='Script completed'),
                {'timestamp':6,'type':'event_msg','payload':{'type':'context_compaction_started'}},
                {'timestamp':9,'type':'compacted','payload':{}}]
        result = native_lifecycles(rows)
        self.assertIsNone(result['tools'][0]['end'])
        self.assertEqual(result['compactions'][0]['duration_s'],3)
        self.assertEqual(native_lifecycles([])['compaction_observation'],'not_observed')

    def test_failed_fetch_is_completed_but_not_successful_and_dangling_compaction_retained(self):
        rows=[native(1,'function_call',name='web.run',call_id='a',arguments='{}'),
              native(3,'function_call_output',call_id='a',output='Failed to fetch URL: (412) Precondition Failed'),
              {'timestamp':4,'type':'event_msg','payload':{'type':'context_compaction_started'}},
              {'timestamp':5,'type':'event_msg','payload':{'type':'task_started'}}]
        r=native_lifecycles(rows)
        self.assertEqual(r['tools'][0]['outcome'],'error_observed')
        self.assertEqual(r['tools'][0]['status'],'completed')
        self.assertIsNone(r['compactions'][0]['end'])


if __name__ == '__main__': unittest.main()
