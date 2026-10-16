"""Loopback-only bridge; expose to the local browser worker through SSH."""
import argparse
import asyncio
import json
import secrets
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from bridge import Bridge
from transport import send_next


def make_server(config, qq=None):
    def bridge():
        return Bridge(config['database'], account=config['account'], group=config['group'])
    def call_qq(action, body):
        req=urllib.request.Request(config['qq_http'].rstrip('/')+'/'+action,
            data=json.dumps(body).encode(), headers={'Content-Type':'application/json',
            'Authorization':'Bearer '+config['qq_token']})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    qq = qq or call_qq
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            if not secrets.compare_digest(self.headers.get('Authorization',''), 'Bearer '+config['bridge_token']):
                self.send_error(401);return
            size=int(self.headers.get('Content-Length','0'))
            if size>262144:
                self.send_error(413);return
            b=bridge()
            try:
                data=json.loads(self.rfile.read(size) or b'{}');now=time.time()
                b.expire(now,config.get('timeout_seconds',300))
                if self.path=='/claim':
                    result=b.claim_browser(now)
                elif self.path=='/submitted':
                    b.submitted(data['id'],now);result=b.get(data['id'])
                elif self.path=='/observe':
                    b.observe(data['id'],request_seen=data['request_seen'],text=data['text'],complete=data['complete'],now=now)
                    result=b.get(data['id'])
                elif self.path=='/send':
                    result=send_next(b,qq)
                elif self.path=='/unknown':
                    b.unknown(data['id'],data['reason'],now);result=b.get(data['id'])
                elif self.path=='/status':
                    result={'account':config['account'],'group':config['group'],
                        'jobs':[json.loads(x[0]) for x in b.db.execute('SELECT body FROM jobs ORDER BY rowid DESC LIMIT 20')]}
                else:
                    self.send_error(404);return
                body=json.dumps(result,ensure_ascii=False).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            except Exception as e:
                self.send_error(400,type(e).__name__)
            finally:
                b.close()
    return HTTPServer(('127.0.0.1',config.get('port',13112)),Handler)


async def receive(config):
    from websockets.asyncio.client import connect
    while True:
        try:
            async with connect(config['qq_ws'],additional_headers={'Authorization':'Bearer '+config['qq_token']}) as ws:
                print(json.dumps({'at':time.time(),'stage':'qq_connected'}),flush=True)
                async for raw in ws:
                    e=json.loads(raw)
                    # Never replay a server backlog into a newly started probe.
                    if e.get('time',0)<config['started_at']:
                        continue
                    b=Bridge(config['database'],account=config['account'],group=config['group'])
                    try:
                        job=b.accept(e,time.time())
                        if job:print(json.dumps({'at':time.time(),'stage':'accepted','id':job['id']}),flush=True)
                    finally:b.close()
        except Exception as e:
            print(json.dumps({'at':time.time(),'stage':'receiver_disconnected','error':type(e).__name__}),flush=True)
            await asyncio.sleep(5)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);args=p.parse_args()
    c=json.loads(Path(args.config).read_text());c['started_at']=int(time.time())
    Path(c['database']).parent.mkdir(parents=True,exist_ok=True)
    b=Bridge(c['database'],account=c['account'],group=c['group']);b.close()
    server=make_server(c)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:asyncio.run(receive(c))
    finally:server.shutdown()
