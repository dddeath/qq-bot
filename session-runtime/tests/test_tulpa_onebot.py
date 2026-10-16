import unittest
import json
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from tulpa_onebot import BoundOneBot


class BoundOneBotTest(unittest.TestCase):
    def test_wrong_login_and_expired_window_never_write(self):
        calls=[]
        def endpoint(action,payload):
            calls.append(action)
            return {'status':'ok','retcode':0,'data':{'user_id':457}}
        with self.assertRaisesRegex(ValueError,'account'):
            BoundOneBot('309','112',endpoint).call('set_qq_profile',{'nickname':'test'})
        self.assertEqual(calls,['get_login_info'])
        calls.clear()
        with self.assertRaisesRegex(ValueError,'expired'):
            BoundOneBot('309','112',endpoint,send_before=100,clock=lambda:101).call('set_qq_profile',{'nickname':'test'})
        self.assertEqual(calls,[])

    def test_own_profile_and_bound_group_use_recipient_account(self):
        sent=[]
        def endpoint(action,payload):
            sent.append((action,payload))
            return {'status':'ok','retcode':0,'data':{'user_id':309} if action=='get_login_info' else {'message_id':42}}
        api=BoundOneBot('309','112',endpoint)
        self.assertEqual(api.call('set_qq_profile',{'nickname':'噗伊'})['retcode'],0)
        self.assertEqual(api.call('send_group_msg',{'group_id':112,'message':[{'type':'image','data':{'file':'base64://abc'}}]})['data']['message_id'],42)
        with self.assertRaises(ValueError):api.call('send_group_msg',{'group_id':983,'message':'wrong'})
        with self.assertRaises(ValueError):api.call('set_group_card',{'group_id':112,'user_id':457,'card':'wrong'})
        self.assertEqual([a for a,p in sent if a!='get_login_info'],['set_qq_profile','send_group_msg'])

    def test_tulpa_http_endpoint_returns_onebot_receipt_and_never_retries_unknown_write(self):
        from tulpa_onebot import http_server
        calls=[]
        def endpoint(action,payload):
            calls.append(action)
            if action=='get_login_info':return {'status':'ok','retcode':0,'data':{'user_id':309}}
            raise TimeoutError('remote receipt lost')
        server=http_server(BoundOneBot('309','112',endpoint),'fixture-token',port=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            request=Request(f'http://127.0.0.1:{server.server_port}/send_group_msg',data=json.dumps({'group_id':112,'message':'test'}).encode(),headers={'Authorization':'Bearer fixture-token','Content-Type':'application/json'})
            with self.assertRaises(HTTPError) as failure:urlopen(request)
            self.assertEqual(failure.exception.code,502)
            result=json.load(failure.exception)
            self.assertEqual(result['status'],'failed')
            self.assertEqual(result['wording'],'transport_result_unknown')
            self.assertEqual(calls,['get_login_info','send_group_msg'])
        finally:server.shutdown();server.server_close();thread.join()
