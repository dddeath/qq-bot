"""Observe model-facing text boundaries without rewriting user/source content."""
import hashlib
import json
import re

VERSION = 'model-input-audit-v2'
INTERNAL_KEYS = {'_debug', 'debug_context', 'debug_notes', 'gold_materials',
                 'gold_labels', 'expected_reply', 'blind_arm', 'relevance_labels'}
MARKER = re.compile(r'\[DEBUG-[^\]\r\n]+\]|DEBUG_ONLY:|EVAL_ONLY:')


def audit_input(value, *, surface, origin='runtime'):
    findings = []
    digest = hashlib.sha256()
    text_characters = 0
    skipped_images = 0

    def note(path, rule):
        findings.append({'path': path, 'rule': rule})

    def walk(item, path='$'):
        nonlocal text_characters, skipped_images
        if isinstance(item, dict):
            if item.get('type') in ('image', 'image_url', 'input_image', 'audio'):
                skipped_images += 1
                return
            if 'qq-bot/retrieval' in item:
                note(path, 'internal_retrieval_metadata')
            if 'index_id' in item and 'channels' in item:
                note(path, 'internal_retrieval_channels')
            if 'index_id' in item and str(item.get('protocol_version', '')).startswith('local-retrieval-'):
                note(path+'.index_id', 'internal_index_label')
            if 'selected_by' in item and all(key in item for key in ('entry_id', 'offset', 'limit')):
                note(path+'.selected_by', 'internal_passage_selector')
            for key, val in item.items():
                if key in INTERNAL_KEYS:
                    note(path+'.'+key, 'internal_or_evaluation_field')
                digest.update(str(key).encode('utf8'))
                walk(val, path+'.'+str(key))
        elif isinstance(item, (list, tuple)):
            for i, val in enumerate(item):
                walk(val, path+f'[{i}]')
        elif isinstance(item, str):
            digest.update(item.encode('utf8'));text_characters += len(item)
            if MARKER.search(item):
                note(path, 'explicit_debug_marker')
            if item.lstrip().startswith(('{', '[')):
                try: parsed = json.loads(item)
                except (ValueError, RecursionError): return
                if isinstance(parsed, (dict, list)):
                    # Inspect encoded tool bodies; do not double count their text.
                    count = text_characters
                    walk(parsed, path+'<json>')
                    text_characters = count
    # Digest records the inspected representation, not a claim about provider wire bytes.
    walk(value)
    return dict(version=VERSION, surface=surface, origin=origin,
                clean=not findings, findings=findings,
                inspected_sha256=digest.hexdigest(), text_characters=text_characters,
                skipped_nontext_blocks=skipped_images, provider_wire_verified=False)


def write_audit(folder, value, *, surface):
    from pathlib import Path
    result = audit_input(value, surface=surface)
    (Path(folder) / 'input-audit.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    return result
