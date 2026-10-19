"""Read-only stdio MCP adapter for an independently installed hlsh-helper."""
import argparse
import base64
import tempfile
import json
import os
from pathlib import Path
import subprocess
import sys
import time

TOOL = {
    'name': 'predict_blackforest_nodes',
    'description': (
        '用户提供明日方舟黑流树海地图截图、询问隐藏节点可能类型时调用。'
        '先将截图保存到工具宿主可读取的本地文件，只传 image_path；工具按地图规模和模板自动识别1–5层。'
        '成功返回PNG图片块和JSON：图片为原图节点编号加右侧候选栏，image_path为生成图片绝对路径。'
        '需要群内发送时，将生成图片交给现有发图工具。'
        '解释结果时按节点编号对应 predictions；多种候选并列说明，候选没有概率排序。'
        '固定节点优先使用 resolved_type，visible_type仅表示截图上的图标，可因难度隐藏。'
        '识别未确定时说明未确定，并请用户提供完整清晰地图截图。工具范围为节点识别与候选推断。'
    ),
    'inputSchema': {'type': 'object', 'properties': {
        'image_path': {'type': 'string', 'description': '完整地图截图的本地绝对文件路径，文件须已存在于本工具宿主；URL和消息附件ID需先经图片工具保存为文件。'}},
        'required': ['image_path'], 'additionalProperties': False},
    'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False},
}


def predict(config, arguments):
    if not isinstance(arguments, dict) or set(arguments) != {'image_path'}:
        raise ValueError('missing_or_unknown_arguments')
    if not isinstance(arguments['image_path'], str) or not Path(arguments['image_path']).is_absolute():
        raise ValueError('image_path_must_be_absolute')
    start = time.monotonic()
    image = Path(arguments['image_path']).resolve()
    if not image.is_file():
        raise ValueError('image_not_found')
    repo = Path(config['repository']).resolve()
    command = [config['python'], str(Path(__file__).with_name('blackforest_engine.py')), '--repository', str(repo), '--image', str(image)]
    output = Path(config.get('output_directory', Path(tempfile.gettempdir()) / 'blackforest-results')).resolve()
    command += ['--output-directory', str(output)]
    if config.get('font_path'):
        command += ['--font-path', config['font_path']]
    timeout = config.get('timeout_seconds', 30)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 180:
        raise ValueError('timeout_seconds_must_be_positive_at_most_180')
    try:
        result = subprocess.run(command, cwd=repo, capture_output=True, encoding='utf-8',
                                env=dict(os.environ, PYTHONIOENCODING='utf-8'), timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError('recognition_timeout') from exc
    if result.returncode:
        raise RuntimeError('recognition_failed: ' + result.stderr[-2000:])
    value = json.loads(result.stdout)
    value['elapsed_seconds'] = round(time.monotonic()-start, 3)
    value['prediction_kind'] = 'candidate_set'
    return value


def serve(config):
    for line in sys.stdin:
        request = {}
        try:
            request = json.loads(line)
            if 'id' not in request:
                continue
            method = request.get('method')
            if method == 'initialize':
                result = {'protocolVersion': request['params']['protocolVersion'],
                          'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'blackforest-nodes', 'version': '1.0.0'}}
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = {'tools': [TOOL]}
            elif method == 'tools/call':
                params = request['params']
                if params.get('name') != TOOL['name']:
                    raise ValueError('unknown_tool')
                value = predict(config, params.get('arguments', {}))
                result = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}]}
                if value.get('image_path'):
                    result['content'].append({'type': 'image', 'mimeType': 'image/png',
                        'data': base64.b64encode(Path(value['image_path']).read_bytes()).decode('ascii')})
                if not value.get('success'):
                    result['isError'] = True
            else:
                raise ValueError('unsupported_method')
            response = {'jsonrpc': '2.0', 'id': request['id'], 'result': result}
        except Exception as exc:
            response = {'jsonrpc': '2.0', 'id': request.get('id'), 'result': {
                'isError': True, 'content': [{'type': 'text', 'text': str(exc)}]}}
        print(json.dumps(response, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    serve(config)


if __name__ == '__main__':
    main()
