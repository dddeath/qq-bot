import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ProfileTransportTest(unittest.TestCase):
    def test_exported_profile_filters_discovery_and_blocks_unlisted_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            upstream=root/'upstream.py'
            upstream.write_text('import json,sys\nfor line in sys.stdin:\n r=json.loads(line)\n if "id" not in r:continue\n result={"tools":[{"name":"read","inputSchema":{"type":"object"}},{"name":"write","inputSchema":{"type":"object"}}]} if r["method"]=="tools/list" else {"content":[{"type":"text","text":"ok"}]}\n print(json.dumps({"jsonrpc":"2.0","id":r["id"],"result":result}),flush=True)\n')
            cfg=root/'tools.json';cfg.write_text(json.dumps({'servers':{'test':{'command':sys.executable,'args':[str(upstream)],'tools':['read']}}}))
            requests=[{'jsonrpc':'2.0','id':1,'method':'tools/list'}, {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'write','arguments':{}}}, {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'read','arguments':{}}}]
            proxy=Path(__file__).resolve().parents[1]/'tool_proxy.py'
            p=subprocess.run([sys.executable,str(proxy),'--config',str(cfg),'--server','test'],input='\n'.join(map(json.dumps,requests))+'\n',capture_output=True,text=True,timeout=10)
            self.assertEqual(p.returncode,0,p.stderr)
            responses=[json.loads(x) for x in p.stdout.splitlines()]
            self.assertEqual([x['name'] for x in responses[0]['result']['tools']],['read'])
            self.assertIn('error',responses[1])
            self.assertEqual(responses[2]['result']['content'][0]['text'],'ok')
