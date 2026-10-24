"""Create reviewable, isolated entry candidates from a catalog audit snapshot.

Tag definitions are curated input, never extracted indiscriminately from prose.
No production write-back or model calls take place here.
"""
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

from knowledge_entries import EntryStore


def normalized(value):
    return ''.join(unicodedata.normalize('NFKC', value).casefold().split())


class TagImporter:
    def __init__(self, policy, annotations=None):
        self.tags = policy['tags']
        self.annotations = annotations or {}
        ids, names = set(), {}
        for tag in self.tags:
            if tag['id'] in ids:
                raise ValueError('duplicate_tag_id')
            ids.add(tag['id'])
            if tag['category'] not in ('领域', '主题', '对象', '需求'):
                raise ValueError('invalid_category')
            for name in [tag['name'], *tag['aliases']]:
                key = (tag['category'], normalized(name))
                if not key[1]:
                    raise ValueError('empty_tag_name')
                if key in names and names[key] != tag['id']:
                    raise ValueError('duplicate_tag_alias:' + name)
                names[key] = tag['id']
            for rule in tag['rules']:
                if rule['field'] not in ('title', 'domain', 'meaning', 'usage', 'conditions', 'situation'):
                    raise ValueError('invalid_rule_field')
                re.compile(rule['pattern'])
        for annotation in self.annotations.values():
            if not annotation.get('reason') or not set(annotation['tags']) <= ids:
                raise ValueError('invalid_annotation')

    @staticmethod
    def collection(e):
        scope = e.get('scope') or {}
        if e['source'] == 'profile':
            if not scope.get('account') or not scope.get('group'):
                raise ValueError('profile_scope_missing')
            return f"profile:{scope['account']}:{scope['group']}"
        if e['source'] == 'published_learning':
            if not scope.get('account') or not scope.get('group'):
                raise ValueError('learning_scope_missing')
            return f"learning:{scope['account']}:{scope['group']}"
        if e['source'] != 'formal':
            raise ValueError('unknown_source')
        return 'formal'

    def classify(self, e):
        if e['entry_id'] in self.annotations:
            a = self.annotations[e['entry_id']]
            expected = hashlib.sha256(e['text'].encode()).hexdigest()
            if a.get('content_sha256') != expected:
                raise ValueError('annotation_source_changed')
            return [dict(tag_id=t, evidence=[dict(field='reviewed_annotation',
                         reason=a['reason'], content_sha256=expected)]) for t in a['tags']]
        fields = dict(title=e['title'], domain=e.get('domain', ''))
        # Learning fields are explicit; do not search formal prose for incidental entities.
        if e['source'] == 'published_learning':
            for key in ('meaning', 'usage', 'conditions', 'situation'):
                match = re.search(r'^' + key + r': (.*)$', e['text'], re.M)
                fields[key] = match.group(1) if match else ''
        matches = []
        for tag in self.tags:
            evidence = []
            for rule in tag['rules']:
                if rule.get('sources') and e['source'] not in rule['sources']:
                    continue
                hit = re.search(rule['pattern'], fields.get(rule['field'], ''), re.I)
                if hit:
                    evidence.append(dict(field=rule['field'], matched=hit.group(), pattern=rule['pattern']))
            if evidence:
                matches.append(dict(tag_id=tag['id'], evidence=evidence))
        return matches

    def run(self, entries, destination):
        destination = Path(destination)
        if destination.exists():
            raise ValueError('destination_exists')
        seen = set()
        prepared = []
        for e in entries:
            if e['entry_id'] in seen:
                raise ValueError('duplicate_source_entry')
            seen.add(e['entry_id'])
            if not e['title'].strip() or not e['text'].strip():
                raise ValueError('empty_source_entry')
            prepared.append((e, self.collection(e), self.classify(e)))
        store = EntryStore(destination, sorted({c for _, c, _ in prepared}))
        used = {m['tag_id'] for _, _, matches in prepared for m in matches}
        for t in self.tags:
            if t['id'] in used:
                store.put_tag(t['id'], t['name'], t['category'], t['aliases'], t['description'])
        mappings = []
        for e, collection, matches in prepared:
            result = store.create(collection, e['title'], e['text'],
                                  [m['tag_id'] for m in matches], ['catalog-snapshot:' + e['entry_id']])
            mappings.append(dict(old_id=e['entry_id'], new_id=result['id'], collection=collection,
                                 title=e['title'], source_version=e.get('version'),
                                 source_updated=e.get('updated'),
                                 content_sha256=hashlib.sha256(e['text'].encode()).hexdigest(),
                                 tags=[m['tag_id'] for m in matches], decisions=matches))
        counts = Counter(t for row in mappings for t in row['tags'])
        defs = [dict(id=t['id'], name=t['name'], category=t['category'], aliases=t['aliases'],
                     count=counts[t['id']]) for t in self.tags if t['id'] in used]
        quality = dict(
            total_entries=len(mappings), total_tags=len(defs),
            categories=dict(Counter(t['category'] for t in defs)),
            collections=dict(Counter(m['collection'] for m in mappings)),
            untagged=[dict(id=m['old_id'], title=m['title']) for m in mappings if not m['tags']],
            singleton_tags=[t for t in defs if t['count'] == 1],
            broad_tags=[t for t in defs if t['count'] > len(entries) * .25],
            dense_entries=[dict(id=m['old_id'], title=m['title'], tags=m['tags'])
                           for m in mappings if len(m['tags']) > 8],
            tag_definitions=defs,
            unmaterialized_tags=[t['id'] for t in self.tags if t['id'] not in used])
        return dict(store=store, mappings=mappings, quality=quality)


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--entries', required=True)
    p.add_argument('--policy', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--annotations')
    args = p.parse_args()
    out = Path(args.output)
    if out.exists():
        raise ValueError('output_exists')
    policy = json.loads(Path(args.policy).read_text(encoding='utf-8-sig'))
    entries = json.loads(Path(args.entries).read_text(encoding='utf-8-sig'))
    annotations = json.loads(Path(args.annotations).read_text(encoding='utf-8-sig')) if args.annotations else None
    result = TagImporter(policy, annotations).run(entries, out / 'snapshot.json')
    out.mkdir(parents=True, exist_ok=True)
    for name in ('mappings', 'quality'):
        (out / (name + '.json')).write_text(json.dumps(result[name], ensure_ascii=False, indent=2), encoding='utf-8')
    for name, path in [('entries', args.entries), ('policy', args.policy)]:
        (out / (name + '.input.json')).write_bytes(Path(path).read_bytes())
    if args.annotations:
        (out / 'annotations.input.json').write_bytes(Path(args.annotations).read_bytes())
    print(json.dumps(result['quality']['categories'], ensure_ascii=False))


if __name__ == '__main__':
    main()
