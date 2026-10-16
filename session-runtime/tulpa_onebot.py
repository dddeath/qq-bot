"""Recipient-scoped OneBot transport for an independent Tulpa instance."""
import argparse
import hmac
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class BoundOneBot:
    def __init__(self, account, group, transport, *, send_before=None, clock=time.time):
        self.account=str(account);self.group=str(group);self.transport=transport
        self.send_before=send_before;self.clock=clock

    def call(self, action, payload):
        writing=not action.startswith('get_') and action not in ('nc_get_user_status','fetch_custom_face_detail')
        if writing and self.send_before is not None and self.clock()>=self.send_before:
            raise ValueError('test window expired')
        if 'group_id' in payload and str(payload['group_id'])!=self.group:
            raise ValueError('group binding mismatch')
        if action=='send_group_msg' and str(payload.get('group_id'))!=self.group:
            raise ValueError('group binding required')
        if action=='set_group_card' and str(payload.get('user_id'))!=self.account:
            raise ValueError('profile belongs to another account')
        login=self.transport('get_login_info',{})
        if login.get('status')!='ok' or login.get('retcode')!=0 or str((login.get('data') or {}).get('user_id'))!=self.account:
            raise ValueError('QQ account binding mismatch')
        if action=='get_login_info':return login
        if writing and self.send_before is not None and self.clock()>=self.send_before:
            raise ValueError('test window expired')
        return self.transport(action,payload)


def http_server(api, token, *, port):
    if not token:raise ValueError('OneBot token required')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token):
                self.send_error(401);return
            status=200
            try:
                payload=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
                if not isinstance(payload,dict):raise ValueError('object required')
                result=api.call(self.path.strip('/'),payload)
            except ValueError:
                result={'status':'failed','retcode':1403,'wording':'binding_or_request_rejected','data':None}
            except Exception:
                status=502
                result={'status':'failed','retcode':1500,'wording':'transport_result_unknown','data':None}
            raw=json.dumps(result,ensure_ascii=False).encode('utf-8')
            self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)


if __name__=='__main__':
    from qq_worker import call
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args()
    config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    api=BoundOneBot(config['account_id'],config['group_id'],lambda action,payload:call(config['qq'],action,payload),send_before=config.get('stop_at_epoch'))
    server=http_server(api,config['qq']['token'],port=config['port'])
    try:server.serve_forever()
    finally:server.server_close()
