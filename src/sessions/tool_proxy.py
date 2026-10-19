"""Line-oriented stdio MCP filter for a frozen, scoped tool profile."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.parse import urlparse
from host_wait import project_host_response


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def http_proxy(config, *, host_wait=False):
    """Bridge Tulpa HTTP MCP; optionally project host-owned waiting instructions."""
    url=config['url'];parsed=urlparse(url)
    if parsed.scheme!='http' or parsed.hostname not in ('localhost','127.0.0.1','::1') or parsed.username or parsed.password:
        raise ValueError('Tulpa endpoint must be loopback HTTP')
    headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream',**config.get('http_headers',{})}
    if config.get('token_file'):
        headers['Authorization']='Bearer '+Path(config['token_file']).read_text(encoding='utf-8').strip()
    elif config.get('bearer_token_env_var'):
        headers['Authorization']='Bearer '+os.environ[config['bearer_token_env_var']]
    opener=build_opener(ProxyHandler({}),NoRedirect())
    allowed=set(config['tools'])
    for line in sys.stdin:
        request=json.loads(line);method=request.get('method')
        if method not in ('initialize','ping','notifications/initialized','tools/list','tools/call') or (method=='tools/call' and request.get('params',{}).get('name') not in allowed):
            response={'jsonrpc':'2.0','id':request.get('id'),'error':{'code':-32601,'message':'Tool or method not enabled in this profile'}}
        else:
            try:
                with opener.open(Request(url,data=line.encode('utf-8'),headers=headers),timeout=245) as reply:
                    data=reply.read()
                if 'id' not in request:continue
                response=json.loads(data)
                if response.get('id')!=request['id']:raise ValueError('response mismatch')
                if method=='tools/list' and 'result' in response:
                    response['result']['tools']=[t for t in response['result'].get('tools',[]) if t['name'] in allowed]
                if method=='initialize' and 'result' in response:response['result']['capabilities']={'tools':{}}
            except Exception:
                # A write may already have reached QQ. Never replay it here.
                response={'jsonrpc':'2.0','id':request.get('id'),'error':{'code':-32000,'message':'Tulpa transport result unknown; no automatic retry'}}
        if host_wait:
            response = project_host_response(response, request)
        if 'id' in request:print(json.dumps(response,ensure_ascii=False),flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    parser.add_argument('--server',required=True)
    parser.add_argument('--host-wait', action='store_true')
    args=parser.parse_args()
    with open(args.config,encoding='utf-8') as f:config=json.load(f)['servers'][args.server]
    if config.get('url'):
        http_proxy(config, host_wait=args.host_wait)
        return
    allowed=set(config['tools'])
    child=subprocess.Popen([config['command'],*config.get('args',[])],env=dict(os.environ,**config.get('env',{})),
                           stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=sys.stderr,text=True,encoding='utf-8',bufsize=1)
    try:
        for line in sys.stdin:
            request=json.loads(line)
            method=request.get('method')
            if method not in ('initialize','ping','notifications/initialized','tools/list','tools/call') or (method=='tools/call' and request.get('params',{}).get('name') not in allowed):
                if 'id' in request:print(json.dumps({'jsonrpc':'2.0','id':request['id'],'error':{'code':-32601,'message':'Tool or method not enabled in this profile'}}),flush=True)
                continue
            child.stdin.write(line);child.stdin.flush()
            if 'id' not in request:continue
            while True:
                response_line=child.stdout.readline()
                if not response_line:raise RuntimeError('upstream MCP closed before response')
                response=json.loads(response_line)
                if response.get('id')!=request['id']:
                    # No sampling, elicitation or new upstream capabilities are delegated.
                    if 'method' in response and 'id' in response:
                        child.stdin.write(json.dumps({'jsonrpc':'2.0','id':response['id'],'error':{'code':-32601,'message':'Client callback not supported'}})+'\n');child.stdin.flush()
                    continue
                if method=='tools/list' and 'result' in response:
                    response['result']['tools']=[t for t in response['result'].get('tools',[]) if t['name'] in allowed]
                if method=='initialize' and 'result' in response:response['result']['capabilities']={'tools':{}}
                print(json.dumps(response,ensure_ascii=False),flush=True)
                break
    finally:
        child.stdin.close()
        try:child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.terminate()
            try:child.wait(timeout=3)
            except subprocess.TimeoutExpired:child.kill();child.wait()


if __name__=='__main__':main()
