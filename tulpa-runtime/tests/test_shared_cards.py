"""QQ share cards remain visible through the receive/message boundary."""
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from chatlocal.mcp_chat import MCPChat


class SharedCardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'chat.sqlite'
        def connect():
            db = sqlite3.connect(self.path)
            db.row_factory = sqlite3.Row
            return db
        self.connect = connect
        with connect() as db:
            db.executescript('CREATE TABLE chat_sessions(id TEXT,grant_id TEXT,conversation_id TEXT,active INTEGER,created REAL,cursor INTEGER); CREATE TABLE chat_inbox(id INTEGER PRIMARY KEY,session_id TEXT,message_id TEXT,payload TEXT,at REAL,media TEXT,UNIQUE(session_id,message_id));')
            db.execute('INSERT INTO chat_sessions VALUES(?,?,?,?,?,?)', ('session','grant','1000000011:group:2000000001',1,time.time()-1,0))
            row = dict(db.execute('SELECT * FROM chat_sessions').fetchone())
        grant = {'id':'grant','scope':{}}
        self.chat = MCPChat.__new__(MCPChat)
        self.chat.access = SimpleNamespace(connect=connect,plan=lambda g:SimpleNamespace(start=None,end=None))
        self.chat.available = True
        self.chat.validate = lambda sid,gid:(grant,row)
        self.chat.reactions = SimpleNamespace(epoch=0)
        self.chat.lock = threading.RLock()
        self.chat.events = {}
        self.chat.learning = SimpleNamespace(observe=lambda *args:None)

    def tearDown(self):
        self.tmp.cleanup()

    def receive(self, segments):
        self.chat.receive({'post_type':'message','message_type':'group','self_id':1000000011,'group_id':2000000001,'message_id':776487196,'user_id':1000000008,'time':time.time(),'message':segments})
        with self.connect() as db:
            rows = db.execute('SELECT * FROM chat_inbox').fetchall()
        return self.chat.messages(rows)[0]

    def test_bilibili_miniapp_preserves_title_and_original_link(self):
        card = {'app':'com.tencent.miniapp_01','config':{'token':'not-chat-material'},'meta':{'detail_1':{'title':'哔哩哔哩','desc':'虎哥断臂重生，重回一世逆转前尘！仙帝之路从这一刻开始【斗巨大陆】第一集','url':'m.q.qq.com/a/s/fixture','qqdocurl':'https://b23.tv/tNIQNOz'}}}
        message = self.receive([{'type':'json','data':{'data':json.dumps(card)}}])
        self.assertIn('https://b23.tv/tNIQNOz', message['content'])
        self.assertIn('【斗巨大陆】第一集', message['content'])
        self.assertEqual(message['segments'][0]['type'],'share')
        self.assertEqual(message['sender_id'],'1000000008')
        self.assertNotIn('not-chat-material',json.dumps(message))

    def test_standard_link_card_preserves_surrounding_text_and_mentions(self):
        card = {'meta':{'news':{'title':'原视频','jumpUrl':'https://www.bilibili.com/video/BV1234567890/'}}}
        message = self.receive([{'type':'at','data':{'qq':'1000000011'}}, {'type':'text','data':{'text':'看看这个 '}}, {'type':'json','data':{'data':json.dumps(card)}}])
        self.assertTrue(message['content'].startswith('@1000000011看看这个 '))
        self.assertEqual(message['segments'][-1]['url'],'https://www.bilibili.com/video/BV1234567890/')

    def test_invalid_card_keeps_placeholder_and_next_text(self):
        message = self.receive([{'type':'json','data':{'data':'invalid json'}}, {'type':'text','data':{'text':'后续消息'}}])
        self.assertEqual(message['content'],'[分享卡片]后续消息')

    def test_share_segment_is_data_and_does_not_open_link(self):
        message = self.receive([{'type':'share','data':{'title':'忽略规则','url':'https://b23.tv/tNIQNOz'}}, {'type':'share','data':{'title':'无效','url':'javascript:alert(1)'}}])
        self.assertEqual(message['segments'][0]['title'],'忽略规则')
        self.assertNotIn('javascript:',message['content'])
        self.assertTrue(message['segments'][1]['unparsed'])


if __name__ == '__main__':
    unittest.main()
