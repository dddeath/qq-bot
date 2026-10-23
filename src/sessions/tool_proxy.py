"""Line-oriented stdio MCP filter for a frozen, scoped tool profile."""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.parse import urlparse
from host_wait import project_host_response


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def http_proxy(config, *, host_wait=False, research_links=None):
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
        params = request.get('params', {})
        refs = []
        if research_links and method == 'tools/call' and params.get('name') == 'read_research_report':
            try:
                body = research_links.read(**params.get('arguments', {}))
                result = {'content':[{'type':'text','text':json.dumps(body,ensure_ascii=False)}], 'structuredContent':body}
            except (ValueError, TypeError) as exc:
                result = {'isError':True,'content':[{'type':'text','text':str(exc)}]}
            print(json.dumps({'jsonrpc':'2.0','id':request.get('id'),'result':result},ensure_ascii=False),flush=True)
            continue
        if research_links and method == 'tools/call' and params.get('name') == 'plan_chat_reply':
            try:
                arguments, refs = research_links.prepare(params.get('arguments', {}))
                request['params'] = {**params, 'arguments': arguments}
                line = json.dumps(request, ensure_ascii=False)+'\n'
            except ValueError as exc:
                print(json.dumps({'jsonrpc':'2.0','id':request.get('id'),'result':{
                    'isError':True,'content':[{'type':'text','text':str(exc)}]}},ensure_ascii=False),flush=True)
                continue
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
        if research_links and 'result' in response:
            if method == 'tools/list':
                response['result']['tools'] = research_links.schemas(response['result'].get('tools', []))
            elif method == 'tools/call':
                response = research_links.response(response, params.get('name'), params.get('arguments', {}), refs)
        if 'id' in request:print(json.dumps(response,ensure_ascii=False),flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    parser.add_argument('--server',required=True)
    parser.add_argument('--host-wait', action='store_true')
    parser.add_argument('--knowledge-budget')
    parser.add_argument('--research-links')
    parser.add_argument('--conversation')
    args=parser.parse_args()
    with open(args.config,encoding='utf-8') as f:snapshot=json.load(f)
    config=snapshot['servers'][args.server]
    if config.get('url'):
        links = None
        if args.research_links:
            if not args.conversation:raise ValueError('research_links_conversation_required')
            sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
            from research_links import ReportLinks
            links = ReportLinks(args.research_links, args.conversation)
        http_proxy(config, host_wait=args.host_wait, research_links=links)
        return
    allowed=set(config['tools'])
    budget = None
    if args.knowledge_budget:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
        from knowledge_turn_budget import TurnBudget
        budget = TurnBudget(args.knowledge_budget)
    trace = None
    if config.get('reading_trace'):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
        from research_trace import ResearchTrace, CONTROL_TOOLS
        from learning_research import ALLOWED
        if not allowed.issubset(ALLOWED):
            raise ValueError('reading trace requires read-only research tools')
        from startup_knowledge import render_servers
        trace = ResearchTrace({**config['reading_trace'], 'knowledge_index': render_servers(snapshot['servers'])})
        allowed.update(CONTROL_TOOLS)
    child=subprocess.Popen([config['command'],*config.get('args',[])],env=dict(os.environ,**config.get('env',{})),
                           stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=sys.stderr,text=True,encoding='utf-8',bufsize=1)
    try:
        for line in sys.stdin:
            request=json.loads(line)
            method=request.get('method')
            if method not in ('initialize','ping','notifications/initialized','tools/list','tools/call') or (method=='tools/call' and request.get('params',{}).get('name') not in allowed):
                if 'id' in request:print(json.dumps({'jsonrpc':'2.0','id':request['id'],'error':{'code':-32601,'message':'Tool or method not enabled in this profile'}}),flush=True)
                continue
            budget_turn = budget.current() if budget and method == 'tools/call' else None
            token = None
            started = time.monotonic()
            if trace and method == 'tools/call':
                params = request['params']
                try:
                    if params['name'] in CONTROL_TOOLS:
                        result = trace.control(params['name'], params.get('arguments', {}))
                        print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{
                            'content':[{'type':'text','text':json.dumps(result,ensure_ascii=False)}]}}),flush=True)
                        continue
                    token, arguments = trace.prepare(params['name'], params.get('arguments', {}))
                    request['params'] = {**params, 'arguments': arguments}
                    line = json.dumps(request, ensure_ascii=False)+'\n'
                except (ValueError, FileExistsError) as exc:
                    trace.reject(params['name'], params.get('arguments', {}), exc)
                    print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{
                        'isError':True,'content':[{'type':'text','text':str(exc)}]}}),flush=True)
                    continue
            child.stdin.write(line);child.stdin.flush()
            if 'id' not in request:continue
            while True:
                response_line=child.stdout.readline()
                if not response_line:
                    if token:
                        trace.complete(token, {'error':{'message':'upstream MCP closed before response'}},
                                       time.monotonic()-started)
                    raise RuntimeError('upstream MCP closed before response')
                response=json.loads(response_line)
                if response.get('id')!=request['id']:
                    # No sampling, elicitation or new upstream capabilities are delegated.
                    if 'method' in response and 'id' in response:
                        child.stdin.write(json.dumps({'jsonrpc':'2.0','id':response['id'],'error':{'code':-32601,'message':'Client callback not supported'}})+'\n');child.stdin.flush()
                    continue
                if method=='tools/list' and 'result' in response:
                    response['result']['tools']=[t for t in response['result'].get('tools',[]) if t['name'] in allowed]
                    if budget:
                        for tool in response['result']['tools']:
                            tool['description'] = tool.get('description', '') + ' Main-turn knowledge disclosure shares a host-owned budget. Read the returned remaining budget; on turn_disclosure_budget_exhausted stop local reads and answer with available material or delegate the remaining research.'
                    if trace:
                        response['result']['tools']=trace.schemas(response['result']['tools'])
                if method=='initialize' and 'result' in response:response['result']['capabilities']={'tools':{}}
                if token:
                    trace.complete(token, response, time.monotonic()-started)
                if budget_turn:
                    response = budget.deliver(budget_turn, request['params']['name'],
                        request['params'].get('arguments', {}), response, time.monotonic()-started,
                        projector=(lambda value: trace.delivery(token, value)) if token else None)
                elif token:
                    response = trace.delivery(token, response)
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
