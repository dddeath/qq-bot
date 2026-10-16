"""Direct-only stdio waiting tool backed by the existing Tulpa configuration."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
import tomllib
from urllib.request import Request, build_opener, ProxyHandler
from chat_wait import NativeCompletions, wait_for_event


class Gateway:
    def __init__(self, rpc, wake):
        self.rpc, self.wake = rpc, wake

    def handle(self, request):
        method = request.get('method')
        if method in ('initialize', 'ping', 'notifications/initialized', 'tools/list'):
            response = self.rpc(request)
            if method == 'tools/list' and 'result' in response:
                tools = response['result'].get('tools', [])
                response['result']['tools'] = [t for t in tools if t['name'] == 'wait_chat_messages']
                for tool in response['result']['tools']:
                    tool['description'] = '直接等待群消息、后台结果或控制事件。空 idle 在程序内续等；直接调用本工具，不使用 exec/wait 轮询。'
                    tool['inputSchema']['properties']['timeout_seconds'] = {'type':'number','minimum':1,'maximum':3600,'default':3600,'description':'本次整体等待上限；空等待由程序续等。'}
            return response
        if method != 'tools/call' or request.get('params', {}).get('name') != 'wait_chat_messages':
            return {'jsonrpc':'2.0','id':request.get('id'),'error':{'code':-32601,'message':'Only wait_chat_messages is exposed'}}
        arguments = dict(request['params'].get('arguments', {}))
        maximum = arguments.pop('timeout_seconds', 3600)
        if isinstance(maximum, bool) or not isinstance(maximum, (int, float)) or not 1 <= maximum <= 3600:
            return {'jsonrpc':'2.0','id':request.get('id'),'error':{'code':-32602,'message':'timeout_seconds must be in [1,3600]'}}
        last = {}
        def upstream(args):
            call = copy.deepcopy(request)
            call['params']['arguments'] = args
            wire = self.rpc(call)
            data = wire.get('result', {})
            body = data.get('structuredContent', data.get('structured_content'))
            if body is None:
                for block in data.get('content', []):
                    if block.get('type') == 'text':
                        try:
                            candidate = json.loads(block['text'])
                            if isinstance(candidate, dict):
                                body = candidate
                                break
                        except ValueError:
                            pass
            if not isinstance(body, dict) or wire.get('error') or data.get('isError'):
                body = {'event':'upstream_error'}
            last.update(wire=wire, body=body)
            return body
        result = wait_for_event(upstream, arguments, self.wake, max_wait_seconds=maximum)
        if result is last.get('body'):
            return last['wire']
        return {'jsonrpc':'2.0','id':request.get('id'),'result':{'content':[{'type':'text','text':json.dumps(result,ensure_ascii=False)}]}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--thread', required=True)
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))))
    args = parser.parse_args()
    config = tomllib.loads((args.codex_home/'config.toml').read_text(encoding='utf-8'))['mcp_servers']['tulpa']
    # Use the same endpoint and credentials as the existing Tulpa tool; no extra credential files.
    headers = {'Content-Type':'application/json','Accept':'application/json, text/event-stream', **config.get('http_headers', {})}
    if config.get('bearer_token_env_var'):
        headers['Authorization'] = 'Bearer '+os.environ[config['bearer_token_env_var']]
    opener = build_opener(ProxyHandler({}))
    def rpc(request):
        with opener.open(Request(config['url'],data=json.dumps(request).encode(),headers=headers),timeout=245) as response:
            raw = response.read()
        if 'id' not in request:
            return None
        result = json.loads(raw)
        if result.get('id') != request['id']:
            raise ValueError('upstream response id mismatch')
        return result
    gateway = Gateway(rpc, NativeCompletions(args.codex_home/'sessions', args.thread))
    for line in sys.stdin:
        request = json.loads(line)
        try:
            response = gateway.handle(request)
        except Exception as exc:
            response = {'jsonrpc':'2.0','id':request.get('id'),'error':{'code':-32000,'message':'Wait failed without retry: '+type(exc).__name__}}
        if 'id' in request:
            print(json.dumps(response,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
