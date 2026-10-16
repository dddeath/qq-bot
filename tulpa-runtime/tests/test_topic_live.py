import json,sys,tempfile,threading,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


class LiveTests(unittest.TestCase):
    def test_slow_maintainer_does_not_block_main_reading_existing_work(self):
        from topic_live import LiveTopics
        entered=threading.Event();release=threading.Event();read=threading.Event()
        def model(r):
            entered.set();release.wait(5)
            return dict(topic_id=None,addressee='bot',intent='question',reply_to_message_id=None,should_interject=False,reason='request')
        event=dict(id=3,onebot_message_id='qq-3',received_at=10,timestamp=10000,
                   conversation_id='a:group:g',sender_id='person',content='question',segments=[])
        with tempfile.TemporaryDirectory() as d:
            live=LiveTopics(Path(d),'a:group:g',model)
            worker=threading.Thread(target=live.ingest,args=(event,10));worker.start()
            self.assertTrue(entered.wait(2))
            def fetch():live.work(10);read.set()
            reader=threading.Thread(target=fetch);reader.start()
            ready=read.wait(.5);release.set();worker.join();reader.join()
            self.assertTrue(ready,'main work read waited for the external model')

    def test_main_can_close_silent_target_without_resampling(self):
        from topic_live import LiveTopics
        def model(r):return dict(topic_id=None,addressee='bot',intent='request',reply_to_message_id=None,should_interject=False,reason='request')
        event=dict(id=3,onebot_message_id='qq-3',received_at=10,timestamp=10000,
                   conversation_id='a:group:g',sender_id='person',content='please be quiet',segments=[])
        with tempfile.TemporaryDirectory() as d:
            live=LiveTopics(Path(d),'a:group:g',model)
            live.ingest(event,10);live.manage('qq-3','create',10,title='quiet')
            live.manage('qq-3','dismiss',11)
            self.assertEqual(live.work(11)['queue'][0]['status'],'cancelled')
            live.ingest(event,12)
            self.assertEqual(len(live.work(12)['queue']),1)

    def test_receipt_grace_and_restart_preserve_unknown_without_resend(self):
        from topic_live import LiveTopics
        def model(r):return dict(topic_id='T001' if r['topics'] else None,addressee='bot',intent='question',reply_to_message_id=None,should_interject=False,reason='question')
        event=dict(id=3,onebot_message_id='qq-3',received_at=10,timestamp=10000,
                   conversation_id='a:group:g',sender_id='person',content='question',segments=[],is_self=False)
        with tempfile.TemporaryDirectory() as d:
            live=LiveTopics(Path(d),'a:group:g',model)
            live.ingest(event,10);live.manage('qq-3','create',10,title='question')
            live.claim('qq-3','plan1',10)
            live.ingest(dict(event,id=4,onebot_message_id='qq-4',received_at=11),11)
            self.assertEqual(live.check('qq-3','plan1',55)['state'],'ready')
            self.assertEqual(live.check('qq-3','plan1',55.01)['state'],'needs_refresh')
            with self.assertRaises(ValueError):live.claim('qq-3','different',12)
            live.receipt('plan1','SUCCEEDED',56)
            restored=LiveTopics(Path(d),'a:group:g',model)
            self.assertEqual(restored.work(57)['queue'][0]['status'],'sent')
            restored.claim('qq-4','plan2',57)
            restarted=LiveTopics(Path(d),'a:group:g',model)
            self.assertEqual(restarted.work(58)['queue'][1]['status'],'unknown')
            with self.assertRaises(ValueError):restarted.claim('qq-4','plan3',58)

    def test_real_event_is_deduplicated_and_main_assigns_one_target(self):
        from topic_live import LiveTopics
        calls=[]
        def model(request):
            calls.append(request)
            return dict(topic_id=None,addressee='bot',intent='question',reply_to_message_id=None,should_interject=False,reason='question')
        event=dict(id=3,onebot_message_id='qq-3',received_at=10,timestamp=10000,
                   conversation_id='a:group:g',sender_id='person',content='question',segments=[],is_self=False)
        with tempfile.TemporaryDirectory() as d:
            live=LiveTopics(Path(d),'a:group:g',model)
            live.ingest(event,10);live.ingest(event,10)
            self.assertEqual(len(calls),1)
            self.assertEqual(live.work(10)['queue'],[])
            self.assertEqual(live.work(10)['pending_assignments'][0]['message']['event_id'],3)
            live.manage('qq-3','create',10,title='question')
            self.assertEqual(live.work(10)['queue'][0]['target']['event_id'],3)
            with self.assertRaises(ValueError):live.ingest(dict(event,conversation_id='a:group:other'),10)
