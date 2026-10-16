import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class TulpaTransportTest(unittest.TestCase):
    def test_http_tulpa_preserves_images_and_filters_tools(self):
        received=[]
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append((self.headers.get('Authorization'),request))
                result={'tools':[{'name':'read_chat_image'},{'name':'other'}]} if request['method']=='tools/list' else {'content':[{'type':'image','mimeType':'image/png','data':'aW1hZ2U='}], 'isError':False}
                body=json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
        server=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);token=root/'token';token.write_text('local-test-token')
                config=root/'profile.json';config.write_text(json.dumps({'servers':{'tulpa':{'url':f'http://127.0.0.1:{server.server_port}/mcp','token_file':str(token),'tools':['read_chat_image']}}}))
                requests=[{'jsonrpc':'2.0','id':1,'method':'tools/list'}, {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'read_chat_image','arguments':{'session_id':'pwie-session','event_id':8,'index':0}}}, {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'other','arguments':{}}}]
                p=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'tool_proxy.py'),'--config',str(config),'--server','tulpa'],input='\n'.join(map(json.dumps,requests))+'\n',text=True,capture_output=True,timeout=10)
                self.assertEqual(p.returncode,0,p.stderr)
                replies=[json.loads(line) for line in p.stdout.splitlines()]
                self.assertEqual(replies[0]['result']['tools'],[{'name':'read_chat_image'}])
                self.assertEqual(replies[1]['result'],{'content':[{'type':'image','mimeType':'image/png','data':'aW1hZ2U='}], 'isError':False})
                self.assertIn('error',replies[2]);self.assertEqual(len(received),2)
                self.assertEqual(received[1][0],'Bearer local-test-token')
                self.assertEqual(received[1][1]['params']['arguments']['session_id'],'pwie-session')
        finally:server.shutdown();server.server_close();thread.join()
