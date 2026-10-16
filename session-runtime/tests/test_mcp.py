import unittest,tempfile,json,subprocess,sys
from pathlib import Path
class McpTest(unittest.TestCase):
 def test_management_mcp_accepts_learning_without_qq_and_nested_profile_bodies(self):
  with tempfile.TemporaryDirectory() as tmp:
   cfg=Path(tmp)/'config.json';cfg.write_text(json.dumps({'database':str(Path(tmp)/'db'),'evidence':str(Path(tmp)/'evidence'),'harnesses':{}}))
   calls=[('configuration_put',{'kind':'tool_profile','id':'shared','body':{'servers':{}}}),('session_create',{'harness':'codex','model':'astra','effort':'medium','purpose':'learning'}),('configuration_list',{})]
   requests=[{'jsonrpc':'2.0','id':i,'method':'tools/call','params':{'name':n,'arguments':a}} for i,(n,a) in enumerate(calls,1)]
   p=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'mcp_server.py'),'--config',str(cfg)],input='\n'.join(map(json.dumps,requests))+'\n',text=True,capture_output=True)
   responses=[json.loads(x) for x in p.stdout.splitlines()]
   self.assertEqual(p.returncode,0,p.stderr)
   self.assertEqual(json.loads(responses[1]['result']['content'][0]['text'])['purpose'],'learning')
   self.assertEqual(json.loads(responses[2]['result']['content'][0]['text'])[0]['id'],'shared')
 def test_mcp_exposes_one_session_type_for_both_harnesses(self):
  with tempfile.TemporaryDirectory() as tmp:
   cfg=Path(tmp)/'config.json';cfg.write_text(json.dumps({'database':str(Path(tmp)/'db'),'evidence':str(Path(tmp)/'evidence'),'harnesses':{}}))
   requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05'}},{'jsonrpc':'2.0','id':2,'method':'tools/list'},{'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'session_create','arguments':{'harness':'codex','account_id':'a','group_id':'g','model':'m','effort':'low','native_session_id':'existing'}}},{'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'session_list','arguments':{}}}]
   p=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'mcp_server.py'),'--config',str(cfg)],input='\n'.join(map(json.dumps,requests))+'\n',text=True,capture_output=True)
   self.assertEqual(p.returncode,0,p.stderr);responses=[json.loads(x) for x in p.stdout.splitlines()]
   names=[x['name'] for x in responses[1]['result']['tools']];self.assertIn('session_send',names)
   sessions=json.loads(responses[3]['result']['content'][0]['text']);self.assertEqual(sessions[0]['native_session_id'],'existing');self.assertEqual(sessions[0]['harness'],'codex')
