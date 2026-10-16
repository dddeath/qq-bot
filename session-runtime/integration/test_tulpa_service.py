"""Real Tulpa tools, isolated databases, and a simulated external QQ endpoint."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import io
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tulpa_onebot import BoundOneBot, http_server


class TulpaServiceTest(unittest.TestCase):
    def test_recipient_grant_delivers_full_messages_and_own_profile(self):
        from tulpa_service import prepare, start_chat
        calls=[]
        def qq(action,payload):
            calls.append((action,payload))
            data={'get_login_info':{'user_id':309,'nickname':'Pwie'},
                  'get_group_list':[{'group_id':112,'group_name':'test'}],
                  'get_group_info':{'group_id':112,'group_name':'test'},
                  'get_stranger_info':{'nickname':'Pwie'},
                  'get_group_member_info':{'group_id':112,'user_id':payload.get('user_id',309),'card':'Pwie'},
                  'send_group_msg':{'message_id':777}}.get(action,{})
            return {'status':'ok','retcode':0,'data':data}
        http=http_server(BoundOneBot('309','112',qq),'fixture',port=0)
        threading.Thread(target=http.serve_forever,daemon=True).start()
        receiver=SimpleNamespace(start=lambda:None,stop=lambda:None,status=lambda:dict(state='connected',account='309'))
        try:
            source=Path(os.environ['TULPA_SOURCE'])
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                config=dict(source=str(source),account_id='309',group_id='112',port=18778,
                            onebot={'url':f'http://127.0.0.1:{http.server_port}','token':'fixture','ws':'ws://127.0.0.1:9'},
                            grant_file=str(root/'grant.json'))
                settings=root/'topic-settings.json'
                settings.write_text(json.dumps({'mode':'freshness_only','group':'309:group:112','state':{'stale_grace_seconds':45,'max_topics':5,'idle_seconds':600},'evidence_root':str(root/'topics')}))
                config['topic_settings']=str(settings)
                config['chat_policy']={'quiet_seconds':.1,'reply_cooldown_seconds':.5}
                maintainer=patch('topic_tulpa.CodexProvider',return_value=lambda _:dict(topic_id=None))
                maintainer.start();self.addCleanup(maintainer.stop)
                with patch('chatlocal.mcp_chat.EventReceiver',return_value=receiver):
                    service,grant=prepare(config)
                cancel=threading.Event()
                def invoke(name,**args):return service.tools.call(grant['token'],name,args,cancel).structuredContent
                persona=root/'persona.md';persona.write_text('Pwie')
                config.update(persona_file=str(persona),start_key='pwie-integration')
                started=start_chat(service,grant,config)
                sid=started['session']['id']
                event=dict(post_type='message',message_type='group',self_id=309,group_id=112,user_id=789,time=__import__('time').time(),sender={'nickname':'member'},message_id=100,
                           message=[{'type':'at','data':{'qq':'309'}},{'type':'text','data':{'text':'看这张图'}},{'type':'image','data':{'file':'picture.png','url':'http://127.0.0.1/image.png'}}])
                service.tools.chat.receive(event)
                self.assertTrue(hasattr(service.tools.chat,'topic_host'),'recipient freshness adapter was not installed')
                service.tools.chat.topic_host.jobs.join()
                result=invoke('wait_chat_messages',session_id=sid,timeout_seconds=1)
                self.assertEqual(len(result['messages']),1,result)
                self.assertIn('看这张图',result['messages'][0]['content'])
                self.assertNotIn('topic_state',result)
                from PIL import Image
                raw=io.BytesIO();Image.new('RGB',(8,8),(255,0,0)).save(raw,format='PNG')
                with patch('chatlocal.mcp_chat_media.download',return_value=raw.getvalue()):
                    image=service.tools.call(grant['token'],'read_chat_image',{'session_id':sid,'event_id':result['messages'][0]['id'],'index':0},cancel)
                self.assertTrue(any(c.type=='image' for c in image.content),image)
                service.tools.chat.receive(event|{'message_id':101,'message':[{'type':'text','data':{'text':'普通群消息也交付'}}]})
                follow=invoke('wait_chat_messages',session_id=sid,acknowledge_through_id=result['read_through_id'],timeout_seconds=1)
                self.assertIn('普通群消息也交付',[m['content'] for m in follow['messages']])
                target=follow['messages'][0]['id']
                time.sleep(.15)
                plan=invoke('plan_chat_reply',session_id=sid,batch_id=follow['input_batch']['id'],action='reply',intent='respond naturally',target_event_id=target,expressions=['sticker'])
                self.assertEqual(plan['state'],'READY',plan)
                service.tools.chat.receive(event|{'message_id':102,'message':[{'type':'text','data':{'text':'another message'}}]})
                time.sleep(.15)
                args=dict(session_id=sid,plan_id=plan['plan_id'],bubbles=[{'kind':'sticker','sticker_id':image.structuredContent['sticker_id']}])
                sent=invoke('send_chat_reply',**args)
                self.assertEqual(sent['state'],'SUCCEEDED',sent)
                self.assertEqual(invoke('send_chat_reply',**args)['state'],'SUCCEEDED')
                self.assertEqual(len([1 for a,p in calls if a=='send_group_msg']),1)
                capability=invoke('get_self_qq_capabilities',session_id=sid)
                self.assertEqual((capability['account'],capability['group_id']),('309','112'))
                profile=invoke('set_self_qq_nickname',session_id=sid,nickname='Pwie new',idempotency_key='nickname-one')
                self.assertTrue(any(a=='set_qq_profile' and p=={'nickname':'Pwie new'} for a,p in calls),profile)
                poke=invoke('poke_chat_member',session_id=sid,event_id=target,idempotency_key='poke-once')
                self.assertTrue(any(a=='group_poke' and p=={'group_id':112,'user_id':789} for a,p in calls),poke)
                denied=invoke('start_chat_session',conversation_id='457:group:983',persona='wrong',idempotency_key='wrong-account')
                self.assertNotIn('session',denied)
                second,again=prepare(config)
                self.assertEqual(again['id'],grant['id'])
                invoke('stop_chat_session',session_id=sid)
        finally:http.shutdown();http.server_close()
