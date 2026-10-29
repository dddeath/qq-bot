"""Prepare reviewed incremental snapshots; publish a single hash-checked file."""
import hashlib
import json
import os
import uuid
from collections import Counter
from pathlib import Path

from knowledge_entries import EntryStore, now
from knowledge_tag_import import TagImporter


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def prepare_update(base_snapshot, mappings, entries, policy, annotations, output, *, reviewed_tags=None):
    """Preserve IDs and local edits. Missing sources remain pending, not deleted."""
    raw = Path(base_snapshot).read_bytes()
    base = json.loads(raw)
    mappings = base.get('import_mappings', mappings)
    old = {m['old_id']: dict(m) for m in mappings}
    if len(old) != len(mappings):
        raise ValueError('duplicate_mapping')
    importer = TagImporter(policy, annotations) if reviewed_tags is None else None
    seen = set()
    prepared = []
    for e in entries:
        if e['entry_id'] in seen:
            raise ValueError('duplicate_source_entry')
        seen.add(e['entry_id'])
        if not e['title'].strip() or not e['text'].strip():
            raise ValueError('empty_source_entry')
        collection = TagImporter.collection(e)
        try:
            previous = old.get(e['entry_id'], {})
            reviewed = any(v.get('field') == 'reviewed_annotation'
                           for m in previous.get('decisions', []) for v in m['evidence'])
            if reviewed_tags is not None:
                annotation=annotations.get(e['entry_id'], {})
                if (not annotation.get('reason') or not annotation.get('tags')
                        or not set(annotation['tags'])<=reviewed_tags.keys()):
                    raise ValueError('invalid_annotation')
                expected=digest(e['text'].encode())
                if annotation.get('content_sha256')!=expected:
                    raise ValueError('annotation_source_changed')
                matches=[dict(tag_id=t, evidence=[dict(field='reviewed_annotation',
                         reason=annotation['reason'],content_sha256=expected)]) for t in annotation['tags']]
            elif reviewed and e['entry_id'] not in annotations:
                if digest(e['text'].encode()) != previous['content_sha256']:
                    raise ValueError('annotation_source_changed')
                matches = previous['decisions']
            else:
                matches = importer.classify(e)
            error = None
        except ValueError as exc:
            if str(exc) != 'annotation_source_changed':
                raise
            matches, error = [], str(exc)
        prepared.append((e, collection, matches, error))
    out = Path(output)
    out.mkdir(parents=True, exist_ok=False)
    (out / 'base.json').write_bytes(raw)
    (out / 'snapshot.json').write_bytes(raw)
    collections = {e['collection'] for e in base['entries'].values()} | {c for _, c, _, _ in prepared}
    store = EntryStore(out / 'snapshot.json', collections)
    definitions = reviewed_tags if reviewed_tags is not None else {t['id']: t for t in policy['tags']}
    changes = []
    registered = set()
    for e, collection, matches, error in prepared:
        identity = e['entry_id']
        tags = [t['tag_id'] for t in matches]
        previous = old.get(identity)
        current = base['entries'].get(previous['new_id']) if previous else None
        if error:
            changes.append(dict(source_id=identity, action='conflict', reason=error))
            continue
        if previous and (current is None or current['collection'] != collection
                         or previous['collection'] != collection):
            changes.append(dict(source_id=identity, action='conflict', reason='mapping_scope_changed'))
            continue
        if current and (current['revision'] != previous.get('entry_revision', 1)
                        or current['status'] != 'active'
                        or digest(current['content'].encode()) != previous['content_sha256']
                        or current['title'] != previous['title'] or current['tags'] != previous['tags']):
            changes.append(dict(source_id=identity, action='conflict', reason='locally_maintained_entry'))
            continue
        for tag_id in tags:
            if tag_id in registered:
                continue
            if reviewed_tags is not None and tag_id in base['tags']:
                registered.add(tag_id)
                continue
            tag = definitions[tag_id]
            store.put_tag(tag_id, tag['name'], tag['category'], tag['aliases'], tag['description'])
            registered.add(tag_id)
        if current:
            if (current['title'], current['content'], current['tags']) == (e['title'], e['text'], tags):
                result = dict(id=current['id'], revision=current['revision'])
                action = 'unchanged'
            else:
                result = store.update(current['id'], current['revision'],
                                      dict(title=e['title'], content=e['text'], tags=tags),
                                      [], 'source_snapshot_update')
                action = 'updated'
        else:
            result = store.create(collection, e['title'], e['text'], tags, ['catalog-snapshot:' + identity])
            action = 'created'
        old[identity] = dict(old_id=identity, new_id=result['id'], entry_revision=result['revision'],
                             collection=collection, title=e['title'], source_version=e.get('version'),
                             source_updated=e.get('updated'), content_sha256=digest(e['text'].encode()),
                             tags=tags, decisions=matches)
        changes.append(dict(source_id=identity, entry_id=result['id'], action=action,
                            revision=result['revision'], tags=tags))
    for identity in old.keys() - seen:
        changes.append(dict(source_id=identity, action='source_missing', reason='retained_pending_review'))
    data = json.loads((out / 'snapshot.json').read_text(encoding='utf-8'))
    data['import_mappings'] = list(old.values())
    write_json(out / 'snapshot.json', data)
    write_json(out / 'entries.input.json', entries)
    write_json(out / 'policy.input.json', policy)
    write_json(out / 'annotations.input.json', annotations)
    receipt = dict(protocol_version=1, status='prepared', prepared_at=now(), base_sha256=digest(raw),
                   candidate_sha256=digest((out / 'snapshot.json').read_bytes()),
                   counts=dict(Counter(c['action'] for c in changes)), changes=changes,
                   untagged=sum(not e['tags'] for e in data['entries'].values() if e['status'] == 'active'))
    write_json(out / 'manifest.json', receipt)
    return receipt


def _replace_checked(target, expected, replacement, commit):
    target = Path(target)
    lock = target.with_suffix('.lock')
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError('store_busy') from None
    tmp = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        os.close(fd)
        if digest(target.read_bytes()) != expected:
            raise ValueError('active_snapshot_changed')
        tmp.write_bytes(replacement)
        os.replace(tmp, target)
        commit()
    finally:
        tmp.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def publish_candidate(candidate, target, approved_sha256):
    """Host operation after review; not exposed to role-facing MCP tools."""
    candidate, target = Path(candidate), Path(target).resolve()
    manifest = json.loads((candidate / 'manifest.json').read_text(encoding='utf-8'))
    raw = (candidate / 'snapshot.json').read_bytes()
    if digest(raw) != approved_sha256 or approved_sha256 != manifest['candidate_sha256']:
        raise ValueError('candidate_hash_mismatch')
    if manifest['counts'].get('conflict'):
        raise ValueError('unresolved_conflicts')
    if digest((candidate / 'base.json').read_bytes()) != manifest['base_sha256']:
        raise ValueError('baseline_hash_mismatch')
    if target == (candidate / 'snapshot.json').resolve() or target == (candidate / 'base.json').resolve():
        raise ValueError('target_is_evidence')
    receipt_path = candidate / 'publish.json'
    receipt = dict(status='published', target=str(target), before_sha256=manifest['base_sha256'],
                   after_sha256=approved_sha256)
    if receipt_path.exists():
        previous = json.loads(receipt_path.read_text(encoding='utf-8'))
        if any(previous.get(k) != v for k, v in receipt.items()) or digest(target.read_bytes()) != approved_sha256:
            raise ValueError('publication_changed')
        return previous
    receipt['published_at'] = now()
    _replace_checked(target, manifest['base_sha256'], raw, lambda: write_json(receipt_path, receipt))
    return receipt


def rollback_candidate(candidate):
    candidate = Path(candidate)
    receipt = json.loads((candidate / 'publish.json').read_text(encoding='utf-8'))
    raw = (candidate / 'base.json').read_bytes()
    if digest(raw) != receipt['before_sha256']:
        raise ValueError('baseline_hash_mismatch')
    result = dict(status='rolled_back', target=receipt['target'], restored_sha256=digest(raw), rolled_back_at=now())
    _replace_checked(receipt['target'], receipt['after_sha256'], raw,
                     lambda: write_json(candidate / 'rollback.json', result))
    return result


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--base', required=True)
    prepare.add_argument('--mappings')
    sources = prepare.add_mutually_exclusive_group(required=True)
    sources.add_argument('--entries')
    sources.add_argument('--knowledge-root')
    prepare.add_argument('--account', default='')
    prepare.add_argument('--group', default='')
    prepare.add_argument('--learning-root')
    prepare.add_argument('--policy', required=True)
    prepare.add_argument('--annotations')
    prepare.add_argument('--output', required=True)
    publish = sub.add_parser('publish')
    publish.add_argument('--candidate', required=True)
    publish.add_argument('--target', required=True)
    publish.add_argument('--approved-sha256', required=True)
    rollback = sub.add_parser('rollback')
    rollback.add_argument('--candidate', required=True)
    args = p.parse_args()
    def read(path):
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if args.action == 'prepare':
        status = None
        if args.entries:
            entries = read(args.entries)
        else:
            from knowledge_catalog import KnowledgeCatalog
            snapshot = KnowledgeCatalog(args.knowledge_root, args.account, args.group,
                                        args.learning_root).export_snapshot()
            entries, status = snapshot['entries'], snapshot['sources']
        mappings = read(args.mappings) if args.mappings else read(args.base).get('import_mappings')
        if mappings is None:
            raise ValueError('import_mappings_required')
        result = prepare_update(args.base, mappings, entries, read(args.policy),
                                read(args.annotations) if args.annotations else {}, args.output)
        write_json(Path(args.output) / 'source-status.json', status)
    elif args.action == 'publish':
        result = publish_candidate(args.candidate, args.target, args.approved_sha256)
    else:
        result = rollback_candidate(args.candidate)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
