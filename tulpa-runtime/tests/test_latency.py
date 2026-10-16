import unittest
from latency import analyze, write_report
from tempfile import TemporaryDirectory
from pathlib import Path

class LatencyTests(unittest.TestCase):
    def test_stage_timings(self):
        def e(at,typ,item):return {'observed_at':at,'event':{'type':typ,'item':item}}
        data=[e(103,'item.completed',{'id':'w','tool':'wait_chat_messages','arguments':{'session_id':'s'},'result':{'structured_content':{'session_id':'s','messages':[{'id':1,'timestamp':100000,'received_at':101,'is_self':False}]}}}),
              e(105,'item.started',{'id':'p','tool':'plan_chat_reply','arguments':{'session_id':'s','target_event_id':1}}),
              e(106,'item.completed',{'id':'p','tool':'plan_chat_reply','arguments':{'session_id':'s','target_event_id':1},'result':{'structured_content':{'state':'READY','plan_id':'p1','decision':{'target_event_id':1}}}}),
              e(109,'item.started',{'id':'x','tool':'send_chat_reply','arguments':{'session_id':'s','plan_id':'p1'}}),
              e(112,'item.completed',{'id':'x','tool':'send_chat_reply','arguments':{'session_id':'s','plan_id':'p1'},'result':{'structured_content':{'state':'SUCCEEDED','bubbles':[{'state':'SUCCEEDED','expression':{'kind':'text'},'receipt':{'created':110,'result':{'timestamp':111,'message_id':7}}}]}}})]
        r=analyze(data)['replies'][0]
        self.assertEqual(r['segments_s'],{'qq_to_receiver':1,'receiver_to_host_delivery':2,'host_delivery_to_plan':2,'plan_tool':1,'plan_to_send':3,'send_to_receipt':2,'receipt_to_host':1})
        self.assertEqual(r['server_e2e_s'],11)
        self.assertEqual(r['receiver_to_receipt_s'],10)
        self.assertEqual(analyze(data)['summary']['server_e2e_s']['mean'],11)
    def test_missing_timestamps_remain_unknown(self):
        r=analyze([{'observed_at':4,'event':{'type':'item.completed','item':{'tool':'send_chat_reply','arguments':{},'result':{'structured_content':{'state':'SUCCEEDED','bubbles':[{'receipt':{'result':{'message_id':9}}}]}}}}}])
        self.assertIsNone(r['replies'][0]['server_e2e_s'])
    def test_reports_do_not_overwrite(self):
        with TemporaryDirectory() as d:
            a=write_report(Path(d),{'a':1});before=a.read_bytes();b=write_report(Path(d),{'a':2})
            self.assertNotEqual(a.parent,b.parent);self.assertEqual(a.read_bytes(),before)

if __name__=='__main__':unittest.main()
