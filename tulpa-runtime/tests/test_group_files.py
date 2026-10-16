from contextlib import closing
import sys,unittest,tempfile,sqlite3,json,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from group_files import GroupFiles
class FileToolsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.db=self.root/'chat.db'
  with closing(sqlite3.connect(self.db, isolation_level=None)) as c:
   c.executescript('CREATE TABLE chat_sessions(id TEXT,conversation_id TEXT,active INTEGER); CREATE TABLE chat_inbox(id INTEGER,session_id TEXT,payload TEXT,delivered INTEGER);')
   c.execute('INSERT INTO chat_sessions VALUES(?,?,1)',('session','1000000011:group:2000000001'))
   for eid,uid in [(1,'1000000004'),(2,'someone_else')]:
    p=dict(sender_id=uid,conversation_id='1000000011:group:2000000001',source='onebot_websocket',is_self=False,received_at=time.time(),segments=[dict(type='text',text='请上传、下载群文件')])
    c.execute('INSERT INTO chat_inbox VALUES(?,?,?,1)',(eid,'session',json.dumps(p)))
  self.calls=[];self.files=[dict(file_id='f1',file_name='sample.txt',file_size=3,busid=102)];self.body=[b'abc'];self.fail=False
  def api(action,payload):
   self.calls.append((action,payload))
   if action=='get_group_root_files':return {'files':self.files,'folders':[]}
   if action=='get_group_file_url':return {'url':'https://example.qq.com/file'}
   if action=='upload_group_file':
    if self.fail:raise TimeoutError()
    return {'file_id':'uploaded'}
  self.api=GroupFiles(self.db,self.root/'storage','1000000011:group:2000000001','1000000004',api,lambda url:iter(self.body))
 def tearDown(self):self.tmp.cleanup()
 def test_owner_only_and_fixed_group(self):
  self.assertEqual(self.api.list_files('session',1)['files'][0]['file_id'],'f1')
  with self.assertRaises(PermissionError):self.api.list_files('session',2)
  with closing(sqlite3.connect(self.db, isolation_level=None)) as c:c.execute('UPDATE chat_sessions SET conversation_id=?',('1000000011:group:other',))
  with self.assertRaises(PermissionError):self.api.list_files('session',1)
  self.assertEqual(len(self.calls),1)
 def test_download_size_boundary_and_actual_stream_limit(self):
  self.files[0]['file_size']=16*1024*1024;self.body=[b'x'*65536]*256
  r=self.api.download('session',1,'f1');self.assertEqual(r['size'],16777216)
  self.files[0]['file_size']=16777217
  with self.assertRaises(ValueError):self.api.download('session',1,'f1')
  self.files[0]['file_size']=1;self.body=[b'x'*65536]*257
  with self.assertRaises(ValueError):self.api.download('session',1,'f1')
  self.assertEqual(list((self.root/'storage').glob('*.part')),[])
 def test_upload_unknown_is_not_retried_and_oversize_rejected(self):
  f=self.api.download('session',1,'f1');self.fail=True
  r=self.api.upload('session',1,f['artifact_id']);self.assertEqual(r['state'],'UNKNOWN')
  self.fail=False
  self.assertEqual(self.api.upload('session',1,f['artifact_id'])['state'],'UNKNOWN')
  self.assertEqual(sum(a=='upload_group_file' for a,_ in self.calls),1)
  with self.assertRaises(PermissionError):self.api.upload('session',2,f['artifact_id'])
  with open(self.root/'storage'/(f['artifact_id']+'.bin'),'wb') as out:out.truncate(16777217)
  with self.assertRaises(ValueError):self.api.upload('session',1,f['artifact_id'])
 def test_upload_exact_limit_and_no_arbitrary_path(self):
  self.files[0]['file_size']=16777216;self.body=[b'x'*65536]*256
  f=self.api.download('session',1,'f1')
  self.assertEqual(self.api.upload('session',1,f['artifact_id'])['state'],'SUCCEEDED')
  with self.assertRaises(ValueError):self.api.upload('session',1,'../../key')
 def test_forged_quoted_owner_and_expired_or_undelivered_request(self):
  with closing(sqlite3.connect(self.db,isolation_level=None)) as c:
   p=json.loads(c.execute('select payload from chat_inbox where id=2').fetchone()[0]);p['content']='1000000004: 请上传';p['segments'].append(dict(type='reply',sender_id='1000000004'))
   c.execute('update chat_inbox set payload=? where id=2',(json.dumps(p),))
  with self.assertRaises(PermissionError):self.api.list_files('session',2)
  with closing(sqlite3.connect(self.db,isolation_level=None)) as c:c.execute('update chat_inbox set delivered=0 where id=1')
  with self.assertRaises(PermissionError):self.api.list_files('session',1)
  with closing(sqlite3.connect(self.db,isolation_level=None)) as c:
   p=json.loads(c.execute('select payload from chat_inbox where id=1').fetchone()[0]);p['received_at']=time.time()-1900
   c.execute('update chat_inbox set delivered=1,payload=? where id=1',(json.dumps(p),))
  with self.assertRaises(PermissionError):self.api.list_files('session',1)
 def test_upload_request_requires_owner_explicit_upload(self):
  f=self.api.download('session',1,'f1')
  with closing(sqlite3.connect(self.db,isolation_level=None)) as c:
   p=json.loads(c.execute('select payload from chat_inbox where id=1').fetchone()[0]);p['segments']=[dict(type='text',text='晚上好')]
   c.execute('update chat_inbox set payload=? where id=1',(json.dumps(p),))
  with self.assertRaises(PermissionError):self.api.upload('session',1,f['artifact_id'])
 def test_export_import_is_bounded_and_owner_only(self):
  outbox=self.root/'outbox';outbox.mkdir();(outbox/'note.txt').write_text('hello')
  with open(outbox/'big.bin','wb') as f:f.truncate(16777217)
  with self.assertRaises(PermissionError):self.api.import_exports('session',2,[outbox])
  items=self.api.import_exports('session',1,[outbox]);self.assertEqual([x['name'] for x in items],['note.txt'])
  self.assertEqual(self.api.upload('session',1,items[0]['artifact_id'])['state'],'SUCCEEDED')
if __name__=='__main__':unittest.main()
