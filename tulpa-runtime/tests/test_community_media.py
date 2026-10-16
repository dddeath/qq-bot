"""Offline media-tool integration tests; no QQ or model calls."""
import io,json,sqlite3,tempfile,threading,unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
from chatlocal.mcp_chat_media import ChatMedia

class MediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.path=self.root/'access.db'; self.sid='a'*32
        def connect():
            db=sqlite3.connect(self.path);db.row_factory=sqlite3.Row;return db
        self.connect=connect
        with connect() as db:
            db.executescript('CREATE TABLE chat_sessions(id TEXT, active INTEGER); CREATE TABLE chat_inbox(id INTEGER,session_id TEXT,media TEXT);')
            db.execute('INSERT INTO chat_sessions VALUES(?,1)',(self.sid,))
        self.grant={'id':'grant','scope':{'chat_images':True,'chat_sticker_send':True}}
        self.row={'id':self.sid,'grant_id':'grant','conversation_id':'123:group:456'}
        def no_network(): raise AssertionError('Unexpected QQ network request')
        chat=SimpleNamespace(access=SimpleNamespace(path=self.path,connect=connect),actions=SimpleNamespace(client_factory=no_network),
            receiver=SimpleNamespace(status=lambda:dict(state='connected',account='123')),
            validate=lambda sid,gid:(self.grant,self.row),live_target=lambda g,c: c)
        self.media=ChatMedia(chat);self.cancel=threading.Event()
        self.images=self.root/'approved';self.images.mkdir()
        buf=io.BytesIO();Image.new('RGB',(12,10),'white').save(buf,format='PNG');self.raw=buf.getvalue()
        (self.images/'greeting.png').write_bytes(self.raw)
        (self.root/'mcp-community.json').write_text(json.dumps({'conversation_ids':['123:group:456'],'directory':str(self.images),'items':[{'file':'greeting.png','description':'挥手招呼','tags':['招呼']}]}))
    def tearDown(self):self.tmp.cleanup()
    def call(self,name,**args):return self.media.call(self.grant,name,{'session_id':self.sid,**args},self.cancel)
    def test_community_can_be_listed_read_and_noted_for_context(self):
        listed,_=self.call('list_chat_stickers',source='community',query='招呼')
        self.assertEqual(len(listed['items']),1)
        item=listed['items'][0];self.assertFalse(item['sendable'])
        info,frames=self.call('read_chat_sticker',sticker_id=item['sticker_id'])
        self.assertTrue(frames);self.assertEqual(info['bytes'],len(self.raw))
        self.call('note_chat_sticker',sticker_id=item['sticker_id'],description='挥手招呼',tags=['招呼'])
        known,_=self.call('list_chat_stickers',source='library',query='招呼')
        self.assertTrue(known['items'][0]['sendable'])

    def test_generated_image_is_discovered_and_read_by_existing_tools(self):
        generated=self.root/'generated_images';thread=generated/'test-thread';thread.mkdir(parents=True)
        (thread/'exec-test.png').write_bytes(self.raw)
        cfg=self.root/'mcp-community.json';config=json.loads(cfg.read_text());config['generated_directory']=str(generated);cfg.write_text(json.dumps(config))
        listed,_=self.call('list_chat_stickers',source='community',query='生成')
        self.assertEqual(len(listed['items']),1)
        item=listed['items'][0]
        info,frames=self.call('read_chat_sticker',sticker_id=item['sticker_id'])
        self.assertTrue(frames);self.assertEqual(info['bytes'],len(self.raw))
        self.row['conversation_id']='123:group:999'
        hidden,_=self.call('list_chat_stickers',source='community',query='生成')
        self.assertEqual(hidden['items'],[])

    def test_existing_group_image_read_returns_pixels(self):
        with self.connect() as db:
            db.execute('INSERT INTO chat_inbox VALUES(1,?,?)',(self.sid,json.dumps([{'url':'https://qpic.cn/test.png'}])))
        with patch('chatlocal.mcp_chat_media.download',return_value=self.raw):
            info,frames=self.call('read_chat_image',event_id=1)
        self.assertTrue(frames);self.assertEqual(info['bytes'],len(self.raw))

    def test_other_group_has_no_community_images(self):
        self.row['conversation_id']='123:group:999'
        result,_=self.call('list_chat_stickers',source='community')
        self.assertEqual(result['items'],[])

    def test_oversized_original_is_reported_without_modification(self):
        (self.images/'greeting.png').write_bytes(b'x'*(6*1024*1024+1))
        result,_=self.call('list_chat_stickers',source='community')
        self.assertEqual(result['items'],[])
        self.assertEqual(result['unavailable'][0]['reason'],'exceeds_6_MiB')

    def test_tool_schema_accepts_community_source(self):
        from chatlocal.agent_tools import tool
        from chatlocal.mcp_chat_media import schemas
        from chatlocal.mcp_tools import argument_problems
        spec=next(x['parameters'] for x in schemas(tool,dict(chat=True,send=True,chat_images=True)) if x['name']=='list_chat_stickers')
        self.assertEqual(argument_problems({'session_id':self.sid,'source':'community'},spec),[])

if __name__=='__main__':unittest.main()
