import unittest,json
from unittest.mock import patch
from qq_worker import call
class TransportTest(unittest.TestCase):
 def test_websocket_transport_ignores_events_and_returns_matching_receipt(self):
  class Socket:
   def __enter__(self):return self
   def __exit__(self,*a):pass
   def send(self,text):self.request=json.loads(text);self.index=0
   def recv(self,timeout=None):
    self.index+=1
    return json.dumps({'post_type':'heartbeat'} if self.index==1 else {'echo':self.request['echo'],'status':'ok','retcode':0,'data':{'message_id':456}})
  with patch('qq_worker.ws_connect',return_value=Socket()):
   r=call({'transport':'websocket','ws':'ws://127.0.0.1:13101','token':'fixture'},'send_group_msg',{'group_id':2000000003})
  self.assertEqual(r['data']['message_id'],456)
