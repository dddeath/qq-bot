"""Bot editing contract shared by management tools and console adapters.

No runtime defaults are inserted here. Omitted fields keep their stored value;
existing extension fields survive an edit, while new edits follow this schema.
"""
import copy
import math
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from knowledge_application import POLICY_SCHEMA


def obj(properties):
    return {'type': 'object', 'properties': properties, 'additionalProperties': False}


BOOL = {'type': 'boolean'}
TEXT = {'type': 'string', 'minLength': 1}
POSITIVE = {'type': 'number', 'exclusiveMinimum': 0}
COUNT = {'type': 'integer', 'minimum': 1}
REF = dict(obj({'kind': {'type': 'string', 'enum': ['tool_profile']},
                'id': TEXT, 'version': COUNT}), required=['kind', 'id', 'version'])
BOT_EDIT = obj({
    'knowledge_application': copy.deepcopy(POLICY_SCHEMA),
    'activation': obj({
        'enabled': BOOL, 'threshold': POSITIVE,
        'active_idle_timeout_seconds': POSITIVE, 'buffer_ttl_seconds': POSITIVE,
        'weights': obj({key: {'type': 'number', 'minimum': 0}
                        for key in ('human', 'video_share', 'bot')}),
        'bot_ids': {'type': 'array', 'items': TEXT},
        'immediate': obj({'mention_self': BOOL, 'reply_to_self': BOOL}),
    }),
    'batching': obj({'max_messages': COUNT, 'max_wait_seconds': POSITIVE}),
    'screening': obj({'enabled': BOOL, 'model': TEXT, 'effort': TEXT, 'fast': BOOL}),
    'main_context': obj({'target_window': COUNT, 'fast': BOOL}),
    'persona_ref': TEXT, 'tool_profile': REF, 'qq_context': {'type': 'string'},
})


def schema():
    changes = copy.deepcopy(BOT_EDIT)
    changes['properties']['tool_profile'].pop('required')
    return {'schema_version': 1, 'kind': 'bot', 'changes': changes,
            'edit_semantics': 'recursive_merge',
            'save_effect': 'new_version_only', 'binding_effect': 'pending_application'}


def errors(value, spec, path='', *, partial=False, reject_unknown=True):
    """Validate the subset of JSON Schema exposed by this contract."""
    result = []
    def error(code):
        result.append({'path': path, 'code': code, 'message': code.replace('_', ' ')})
    expected = spec.get('type')
    matches = {'object': isinstance(value, dict), 'array': isinstance(value, list),
               'string': isinstance(value, str), 'boolean': type(value) is bool,
               'integer': type(value) is int,
               'number': type(value) in (int, float)}.get(expected, True)
    if not matches:
        error('invalid_type')
        return result
    if expected in ('number', 'integer'):
        try:
            finite = math.isfinite(value)
        except OverflowError:
            error('number_out_of_range')
            return result
        if not finite:
            error('non_finite_number')
            return result
        if 'minimum' in spec and value < spec['minimum']:
            error('below_minimum')
        if 'maximum' in spec and value > spec['maximum']:
            error('above_maximum')
        if 'exclusiveMinimum' in spec and value <= spec['exclusiveMinimum']:
            error('below_exclusive_minimum')
    if expected == 'string' and len(value.strip()) < spec.get('minLength', 0):
        error('empty_string')
    if 'enum' in spec and value not in spec['enum']:
        error('invalid_value')
    if isinstance(value, dict):
        fields = spec.get('properties', {})
        if not partial:
            for key in set(spec.get('required', [])) - set(value):
                result.append({'path': '.'.join(filter(None, (path, key))),
                               'code': 'required', 'message': 'required field'})
        for key, item in value.items():
            child = '.'.join(filter(None, (path, key)))
            if key in fields:
                result.extend(errors(item, fields[key], child, partial=partial,
                                     reject_unknown=reject_unknown))
            elif reject_unknown and spec.get('additionalProperties') is False:
                result.append({'path': child, 'code': 'field_not_editable',
                               'message': 'field not editable'})
    if isinstance(value, list) and 'items' in spec:
        for i, item in enumerate(value):
            result.extend(errors(item, spec['items'], f'{path}.{i}', partial=partial,
                                 reject_unknown=reject_unknown))
    return result


def merge(body, changes):
    result = copy.deepcopy(body)
    for key, value in changes.items():
        result[key] = merge(result.get(key, {}), value) if (
            isinstance(value, dict) and isinstance(result.get(key, {}), dict)
        ) else copy.deepcopy(value)
    return result


def diff(before, after, path=''):
    rows = []
    for key in sorted(set(before) | set(after)):
        a, b = before.get(key), after.get(key)
        child = '.'.join(filter(None, (path, key)))
        if isinstance(a, dict) and isinstance(b, dict):
            rows.extend(diff(a, b, child))
        elif key not in before or key not in after or a != b:
            rows.append({'path': child, 'before': a, 'after': b})
    return rows
