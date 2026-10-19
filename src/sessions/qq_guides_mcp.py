"""Read operation guides from the immutable session tool snapshot; no filesystem tool."""
import argparse
import json
from pathlib import Path
import sys


def handle(snapshot, request):
    capabilities = (snapshot.get('qq_tools') or {}).get('capabilities', {})
    method = request.get('method')
    result = {}
    if method == 'initialize':
        result = dict(protocolVersion=request['params']['protocolVersion'], capabilities={'tools': {}},
                      serverInfo={'name': 'qq-guides', 'version': '1'})
    elif method == 'tools/list':
        if not capabilities:
            return dict(jsonrpc='2.0', id=request.get('id'), result={'tools': []})
        result = {'tools': [{'name': 'read_qq_tool_guide',
            'description': '按需读取当前 Bot 和群已启用 QQ 能力的操作细则；使用当前会话固定配置版本。',
            'inputSchema': {'type': 'object', 'properties': {'capability': {'type': 'string', 'enum': list(capabilities)},
                            'section': {'type': 'string', 'description': '留空读取能力说明；子章节名称由能力说明返回。'}},
                            'required': ['capability'], 'additionalProperties': False},
            'annotations': {'readOnlyHint': True}}]}
    elif method == 'tools/call':
        params = request.get('params', {}); args = params.get('arguments', {})
        if params.get('name') != 'read_qq_tool_guide' or set(args)-{'capability','section'} or args.get('capability') not in capabilities:
            raise ValueError('QQ capability not enabled in this session')
        cap = capabilities[args['capability']]
        section=args.get('section','')
        if section and section not in cap.get('sections',{}):
            raise ValueError('unknown QQ guide section')
        guide=cap['sections'][section] if section else cap['guide']
        body = dict(capability=args['capability'], binding=snapshot['qq_tools']['binding'],
                    tool_profile_ref=snapshot['tool_profile_ref'], bot_ref=snapshot['bot_ref'],
                    tools=cap['tools'], parameters=cap['parameters'], guide_sha256=cap['guide_sha256'],
                    section=section, sections=list(cap.get('sections',{})), guide=guide)
        result = {'content': [{'type': 'text', 'text': json.dumps(body, ensure_ascii=False)}], 'structuredContent': body}
    elif method not in ('ping', 'notifications/initialized'):
        raise ValueError('unsupported method')
    return dict(jsonrpc='2.0', id=request.get('id'), result=result)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--snapshot', type=Path, required=True)
    snapshot = json.loads(parser.parse_args().snapshot.read_text(encoding='utf-8'))
    for line in sys.stdin:
        request = json.loads(line)
        try:
            response = handle(snapshot, request)
        except (ValueError, TypeError, KeyError) as exc:
            response = dict(jsonrpc='2.0', id=request.get('id'), error={'code': -32602, 'message': str(exc)})
        if 'id' in request:
            print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == '__main__': main()
