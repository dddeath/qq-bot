"""Read the existing structured or text MCP evidence without changing the envelope."""
import json
from copy import deepcopy

RETRIEVAL_META = 'qq-bot/retrieval'


def fit_candidates(material, maximum, measure):
    """Trim only complete trailing candidates, retaining exact source handles."""
    result = deepcopy(material)
    if measure(result) <= maximum:
        return result
    total = result.get('candidate_coverage', {}).get('total', len(result['candidates']))
    result['candidate_coverage'] = dict(total=total, returned=len(result['candidates']), complete=False)
    while result['candidates'] and measure(result) > maximum:
        result['candidates'].pop()
        result['candidate_coverage']['returned'] = len(result['candidates'])
    return result if measure(result) <= maximum else None


def model_material(body):
    body = deepcopy(body)
    if not isinstance(body, dict) or not str(body.get('protocol_version', '')).startswith('local-retrieval-') or 'candidates' not in body:
        return body
    body.pop('index_id', None)
    for candidate in body['candidates']:
        for passage in candidate.get('passages', []):
            passage.pop('selected_by', None)
    return body


def model_response(response):
    """Keep executor diagnostics in evidence, outside the model's disclosure."""
    projected = deepcopy(response)
    result = projected.get('result')
    metadata = result.get('_meta') if isinstance(result, dict) else None
    if isinstance(metadata, dict):
        metadata.pop(RETRIEVAL_META, None)
        if not metadata:
            projected['result'].pop('_meta', None)
    if isinstance(result, dict):
        for key in ('structuredContent', 'structured_content'):
            if key in result:
                result[key] = model_material(result[key])
        for block in result.get('content', []):
            if block.get('type') != 'text':
                continue
            try:
                body = json.loads(block['text'])
            except (ValueError, TypeError):
                continue
            if isinstance(body, dict) and str(body.get('protocol_version', '')).startswith('local-retrieval-') and 'candidates' in body:
                block['text'] = json.dumps(model_material(body), ensure_ascii=False)
    return projected


def body_of(item):
    result = item.get('result') or {}
    for key in ('structuredContent', 'structured_content'):
        if isinstance(result.get(key), dict):
            return result[key]
    for block in result.get('content', []):
        if block.get('type') == 'text':
            try:
                value = json.loads(block['text'])
                if isinstance(value, dict):
                    return value
            except ValueError:
                pass
    return {}
