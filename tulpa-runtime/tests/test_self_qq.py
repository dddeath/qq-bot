import io,json,sqlite3,tempfile,threading,unittest
from PIL import Image
from chatlocal.onebot import OneBotUncertain
from pathlib import Path
from types import SimpleNamespace
from chatlocal.mcp_self_qq import SelfQQ, schemas
from chatlocal.agent_tools import tool
from chatlocal.mcp_tools import argument_problems

class Endpoint:
    def __init__(self):self.writes=[];self.nickname='QA';self.fail=None
    def login(self):return '123'
    def call(self,action,payload,**kwargs):
        if action=='get_login_info':return {'user_id':123,'nickname':self.nickname}
        if action=='get_stranger_info':return {'nickname':self.nickname,'long_nick':'old signature'}
        if action=='get_group_member_info':return {'user_id':payload['user_id'],'card':'old card'}
        if action=='nc_get_user_status':return {'status':10,'ext_status':0}
        self.writes.append((action,payload))
        if self.fail:raise self.fail
        if action=='set_qq_profile':self.nickname=payload['nickname']
        return None

class SelfQQTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        def connect():
            db=sqlite3.connect(self.root/'db.sqlite');db.row_factory=sqlite3.Row;return db
        self.endpoint=Endpoint();self.grant={'id':'g','scope':{'chat':True,'send':True}}
        self.row={'id':'a'*32,'grant_id':'g','conversation_id':'123:group:456','active':1}
        self.chat=SimpleNamespace(access=SimpleNamespace(path=self.root/'db.sqlite',connect=connect),actions=SimpleNamespace(client_factory=lambda:self.endpoint),receiver=SimpleNamespace(status=lambda:{'state':'connected','account':'123'}),validate=lambda sid,gid:(self.grant,self.row))
        (self.root/'mcp-self-qq.json').write_text(json.dumps({'grant_ids':['g'],'conversation_ids':['123:group:456'],'enabled':True}))
        self.api=SelfQQ(self.chat)
    def tearDown(self):self.tmp.cleanup()
    def call(self,name,**kwargs):return self.api.call(self.grant,name,{'session_id':'a'*32,**kwargs},threading.Event())
    def test_nickname_updates_only_logged_in_account_and_replays_receipt(self):
        result=self.call('set_self_qq_nickname',nickname='GPT',idempotency_key='nickname-1')
        self.assertEqual(result['state'],'SUCCEEDED')
        self.assertEqual(self.endpoint.nickname,'GPT')
        self.call('set_self_qq_nickname',nickname='GPT',idempotency_key='nickname-1')
        self.assertEqual(self.endpoint.writes,[('set_qq_profile',{'nickname':'GPT'})])

    def test_signature_group_card_and_status_are_self_scoped(self):
        cases=[('set_self_qq_signature',{'signature':'在群里待着'},('set_self_longnick',{'longNick':'在群里待着'})),
               ('set_self_qq_group_card',{'card':'GPT'},('set_group_card',{'group_id':456,'user_id':123,'card':'GPT'})),
               ('set_self_qq_status',{'wording':'看图','face_id':'1'},('set_diy_online_status',{'wording':'看图','face_id':'1','face_type':'1'}))]
        for i,(name,args,expected) in enumerate(cases):
            with self.subTest(name=name):
                result=self.call(name,idempotency_key='profile-'+str(i),**args)
                self.assertEqual(result['state'],'SUCCEEDED');self.assertEqual(self.endpoint.writes[-1],expected)

    def test_avatar_uses_read_pixels_and_poke_uses_delivered_member(self):
        from chatlocal.mcp_chat_media import ChatMedia
        self.grant['scope'].update(chat_images=True,chat_sticker_send=True)
        self.chat.live_target=lambda g,c:c
        with self.chat.access.connect() as db:
            db.executescript('CREATE TABLE chat_sessions(id TEXT,active INTEGER); CREATE TABLE chat_inbox(id INTEGER,session_id TEXT,media TEXT,payload TEXT,delivered INTEGER DEFAULT 0);')
            db.execute('INSERT INTO chat_sessions VALUES(?,1)',(self.row['id'],))
            db.execute('INSERT INTO chat_inbox VALUES(4,?,?,?,1)',(self.row['id'],'[]',json.dumps({'sender_id':'789','is_self':False})))
            db.execute('INSERT INTO chat_inbox VALUES(5,?,?,?,0)',(self.row['id'],'[]',json.dumps({'sender_id':'789','is_self':False})))
        self.row['offered']=4
        media=ChatMedia(self.chat);self.chat.media=media
        image=self.root/'approved';image.mkdir();buf=io.BytesIO();Image.new('RGB',(8,8),'white').save(buf,format='PNG');raw=buf.getvalue();(image/'avatar.png').write_bytes(raw)
        (self.root/'mcp-community.json').write_text(json.dumps({'conversation_ids':['123:group:456'],'directory':str(image),'items':[{'file':'avatar.png'}]}))
        listing,_=media.call(self.grant,'list_chat_stickers',{'session_id':self.row['id'],'source':'community'},threading.Event());aid=listing['items'][0]['sticker_id']
        with self.assertRaises(ValueError):self.call('set_self_qq_avatar',sticker_id=aid,idempotency_key='avatar-before-read')
        media.call(self.grant,'read_chat_sticker',{'session_id':self.row['id'],'sticker_id':aid},threading.Event())
        result=self.call('set_self_qq_avatar',sticker_id=aid,idempotency_key='avatar-after-read');self.assertEqual(result['state'],'SUCCEEDED')
        import base64
        self.assertEqual(self.endpoint.writes[-1],('set_qq_avatar',{'file':'base64://'+base64.b64encode(raw).decode()}))
        result=self.call('poke_chat_member',event_id=4,idempotency_key='poke-0001');self.assertEqual(result['state'],'SUCCEEDED')
        self.assertEqual(self.endpoint.writes[-1],('group_poke',{'group_id':456,'user_id':789}))
        with self.assertRaises(ValueError):self.call('poke_chat_member',event_id=5,idempotency_key='poke-0002')

    def test_unknown_operation_is_not_retried_under_new_key(self):
        self.endpoint.fail=OneBotUncertain('timeout')
        one=self.call('set_self_qq_nickname',nickname='GPT',idempotency_key='unknown-1')
        two=self.call('set_self_qq_nickname',nickname='GPT',idempotency_key='unknown-2')
        self.assertEqual(one['state'],'UNKNOWN');self.assertEqual(two['state'],'UNKNOWN');self.assertEqual(len(self.endpoint.writes),1)

    def test_schema_rejects_other_account_or_group_targets(self):
        spec=next(s['parameters'] for s in schemas(tool) if s['name']=='set_self_qq_group_card')
        self.assertTrue(argument_problems({'session_id':'a'*32,'card':'x','idempotency_key':'test-key','user_id':'999'},spec))
        self.row['conversation_id']='123:group:999'
        with self.assertRaises(ValueError):self.call('set_self_qq_group_card',card='x',idempotency_key='badgroup')

if __name__=='__main__':unittest.main()
