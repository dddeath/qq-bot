import tempfile
import unittest
from pathlib import Path
from bridge import Bridge


def event(mid=1, **changes):
    e = dict(post_type='message', message_type='group', self_id=1000000009,
             group_id=2000000003, user_id=1000000004, message_id=mid, time=100,
             message=[{'type': 'at', 'data': {'qq': '1000000009'}},
                      {'type': 'text', 'data': {'text': '冰为什么会浮起来？'}}])
    e.update(changes)
    return e


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'state.sqlite3'
        self.b = Bridge(self.path, account='1000000009', group='2000000003')

    def tearDown(self):
        self.b.close()
        self.tmp.cleanup()

    def test_only_target_group_real_mention_is_admitted_once(self):
        self.assertIsNone(self.b.accept(event(group_id=2000000001), 101))
        self.assertIsNone(self.b.accept(event(self_id=1000000011), 101))
        self.assertIsNone(self.b.accept(event(user_id=1000000009), 101))
        self.assertIsNone(self.b.accept(event(message=[{'type':'text','data':{'text':'@1000000009 hi'}}]), 101))
        job = self.b.accept(event(), 101)
        self.assertEqual(job['text'], '冰为什么会浮起来？')
        self.assertEqual(job['sender'], '1000000004')
        self.assertIsNone(self.b.accept(event(), 102))
        self.b.close()
        self.b = Bridge(self.path, account='1000000009', group='2000000003')
        self.assertIsNone(self.b.accept(event(), 103))

    def test_browser_streaming_and_old_reply_do_not_send(self):
        job = self.b.accept(event(), 101)
        claim = self.b.claim_browser(102)
        self.assertEqual(claim['id'], job['id'])
        self.assertIsNone(self.b.claim_browser(103))
        self.b.submitted(job['id'], 104)
        self.b.observe(job['id'], request_seen=False, text='旧回答', complete=True, now=105)
        self.assertIsNone(self.b.claim_reply(106))
        self.b.observe(job['id'], request_seen=True, text='冰的密度', complete=False, now=107)
        self.assertIsNone(self.b.claim_reply(108))
        self.b.observe(job['id'], request_seen=True, text='冰的密度低于液态水。', complete=True, now=110)
        self.assertIsNone(self.b.claim_reply(110.5))
        self.b.observe(job['id'], request_seen=True, text='冰的密度低于液态水。', complete=True, now=112)
        reply = self.b.claim_reply(113)
        self.assertEqual(reply['answer'], '冰的密度低于液态水。')
        self.assertEqual(reply['group'], '2000000003')
        self.assertIsNone(self.b.claim_reply(114))
        self.b.sent(job['id'], receipt='9001', now=115)
        result = self.b.get(job['id'])
        self.assertEqual(result['state'], 'SENT')
        self.assertEqual(result['durations'], dict(queue=1, submit=2, generation=8, reply_queue=1, send=2, total=14))

    def test_timeout_and_restart_never_repeat_browser_submission(self):
        job = self.b.accept(event(), 101)
        self.b.claim_browser(102)
        self.b.expire(403, timeout=300)
        self.assertEqual(self.b.get(job['id'])['state'], 'UNKNOWN')
        self.b.accept(event(2), 404)
        self.b.close()
        self.b = Bridge(self.path, account='1000000009', group='2000000003')
        self.assertIsNone(self.b.claim_browser(405))
        self.assertIsNone(self.b.claim_reply(405))

    def test_unknown_qq_send_blocks_resend_and_next_submission(self):
        job = self.b.accept(event(), 101)
        self.b.claim_browser(102);self.b.submitted(job['id'], 103)
        for now in (104,106):
            self.b.observe(job['id'], request_seen=True, text='测试回答', complete=True, now=now)
        self.b.claim_reply(107)
        self.b.unknown(job['id'], 'QQ timeout', 108)
        self.b.accept(event(2), 109)
        self.assertIsNone(self.b.claim_reply(110))
        self.assertIsNone(self.b.claim_browser(110))
        self.assertEqual(self.b.get(job['id'])['error'], 'QQ timeout')

    def test_sender_uses_original_group_plain_text_and_requires_receipt(self):
        from transport import send_next
        job = self.b.accept(event(), 101)
        self.b.claim_browser(102);self.b.submitted(job['id'], 103)
        for now in (104,106):
            self.b.observe(job['id'], request_seen=True, text='[CQ:at,qq=all] 原样文本', complete=True, now=now)
        calls = []
        def qq(action, body):
            calls.append((action, body))
            if action == 'get_login_info':
                return {'status':'ok','retcode':0,'data':{'user_id':1000000009}}
            return {'status':'ok','retcode':0,'data':{'message_id':9002}}
        result = send_next(self.b, qq, clock=lambda:110)
        self.assertEqual(result['receipt'], '9002')
        self.assertEqual(calls[-1], ('send_group_msg', {'group_id':2000000003,'message':[{'type':'text','data':{'text':'[CQ:at,qq=all] 原样文本'}}]}))
        self.assertIsNone(send_next(self.b, qq, clock=lambda:111))

    def test_missing_receipt_and_wrong_login_never_repeat_send(self):
        from transport import send_next
        for wrong_account in (True, False):
            with self.subTest(wrong_account=wrong_account):
                path = Path(self.tmp.name) / f'{wrong_account}.sqlite3'
                b = Bridge(path, account='1000000009', group='2000000003')
                j=b.accept(event(),101);b.claim_browser(102);b.submitted(j['id'],103)
                for now in (104,106):
                    b.observe(j['id'],request_seen=True,text='测试',complete=True,now=now)
                sends=[]
                def qq(action, body):
                    if action=='get_login_info':
                        return {'retcode':0,'data':{'user_id':1000000011 if wrong_account else 1000000009}}
                    sends.append(body)
                    return {'status':'ok','retcode':0,'data':{}}
                self.assertEqual(send_next(b,qq,clock=lambda:110)['state'],'UNKNOWN')
                self.assertIsNone(send_next(b,qq,clock=lambda:111))
                self.assertEqual(len(sends),0 if wrong_account else 1)
                b.close()

    def test_authenticated_http_handoff_preserves_one_shot_delivery(self):
        import json
        import threading
        import urllib.request
        import urllib.error
        from server import make_server
        job=self.b.accept(event(),101)
        def qq(action, body):
            return {'status':'ok','retcode':0,'data':{'user_id':1000000009} if action=='get_login_info' else {'message_id':9010}}
        server=make_server(dict(database=str(self.path),account='1000000009',group='2000000003',port=0,bridge_token='test-secret'),qq)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def call(path,body=None,token='test-secret'):
            req=urllib.request.Request(f'http://127.0.0.1:{server.server_port}'+path,data=json.dumps(body or {}).encode(),headers={'Authorization':'Bearer '+token})
            with urllib.request.urlopen(req) as r:return json.load(r)
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                call('/claim',token='wrong')
            self.assertEqual(error.exception.code,401)
            self.assertEqual(call('/claim')['id'],job['id'])
            call('/submitted',{'id':job['id']})
            self.assertIsNone(call('/send'))
            call('/unknown',{'id':job['id'],'reason':'test browser timeout'})
            self.assertIsNone(call('/claim'))
            self.assertIsNone(call('/send'))
        finally:
            server.shutdown();thread.join();server.server_close()
