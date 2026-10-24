"""Versioned entry/Tag contract over an isolated collection snapshot.

This boundary does not migrate or write the existing Markdown or learning DB.
Collection grants come from the host, never model arguments.
"""
import copy
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class EntryStore:
    def __init__(self, path, collections):
        self.path = Path(path)
        self.collections = frozenset(collections)

    def _load(self):
        if not self.path.exists():
            return dict(protocol_version=1, tags={}, entries={}, history={})
        return json.loads(self.path.read_text(encoding='utf-8'))

    def _write(self, action):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_suffix('.lock')
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise ValueError('store_busy') from None
        tmp = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            os.close(fd)
            data = self._load()
            result = action(data)
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(tmp, self.path)
            return result
        finally:
            tmp.unlink(missing_ok=True)
            lock.unlink(missing_ok=True)

    def _entry(self, data, entry_id):
        e = data['entries'].get(entry_id)
        if not e or e['collection'] not in self.collections:
            raise ValueError('unknown_entry')
        return e

    @staticmethod
    def _revision(e, revision):
        if e['revision'] != revision:
            raise ValueError('revision_conflict')

    @staticmethod
    def _strings(items):
        if not isinstance(items, list) or any(not isinstance(x, str) or not x.strip() for x in items):
            raise ValueError('invalid_string_list')
        return list(dict.fromkeys(items))

    def _tags(self, data, tags):
        tags = self._strings(tags)
        if any(t not in data['tags'] for t in tags):
            raise ValueError('unknown_tag')
        return tags

    def put_tag(self, tag_id, name, category, aliases, description):
        if category not in ('领域', '主题', '对象', '需求'):
            raise ValueError('invalid_tag_category')
        if not tag_id.strip() or not name.strip():
            raise ValueError('empty_tag')
        tag = dict(id=tag_id, name=name, category=category,
                   aliases=self._strings(aliases), description=description)
        def apply(data):
            if tag_id in data['tags'] and data['tags'][tag_id] != tag:
                raise ValueError('tag_exists')
            data['tags'][tag_id] = tag
            return tag
        return self._write(apply)

    def create(self, collection, title, content, tags, sources):
        if collection not in self.collections:
            raise ValueError('collection_denied')
        if not title.strip() or not content.strip():
            raise ValueError('empty_content')
        def apply(data):
            stamp = now()
            e = dict(id=uuid.uuid4().hex, title=title, content=content,
                     tags=self._tags(data, tags), sources=self._strings(sources),
                     created_at=stamp, updated_at=stamp, revision=1,
                     status='active', collection=collection)
            data['entries'][e['id']] = e
            data['history'][e['id']] = [dict(entry=copy.deepcopy(e), reason='created')]
            return dict(id=e['id'], revision=1, status='active')
        return self._write(apply)

    def _save_revision(self, data, e, reason):
        e['revision'] += 1
        e['updated_at'] = now()
        data['history'][e['id']].append(dict(entry=copy.deepcopy(e), reason=reason))
        return dict(id=e['id'], revision=e['revision'], status=e['status'])

    def update(self, entry_id, base_revision, changes, add_sources, reason):
        if not reason.strip() or set(changes) - {'title', 'content', 'tags', 'sources'}:
            raise ValueError('invalid_changes')
        def apply(data):
            e = self._entry(data, entry_id)
            self._revision(e, base_revision)
            if e['status'] != 'active':
                raise ValueError('entry_inactive')
            for field, value in changes.items():
                if field in ('title', 'content'):
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError('empty_content')
                elif field == 'tags':
                    value = self._tags(data, value)
                else:
                    value = self._strings(value)
                e[field] = value
            e['sources'] = list(dict.fromkeys(e['sources'] + self._strings(add_sources)))
            return self._save_revision(data, e, reason)
        return self._write(apply)

    def withdraw(self, entry_id, base_revision, reason):
        def apply(data):
            e = self._entry(data, entry_id)
            self._revision(e, base_revision)
            if not reason.strip() or e['status'] != 'active':
                raise ValueError('invalid_withdrawal')
            e['status'] = 'withdrawn'
            return self._save_revision(data, e, reason)
        return self._write(apply)

    def merge(self, entry_id, base_revision, target_id, target_revision, reason):
        def apply(data):
            e, target = self._entry(data, entry_id), self._entry(data, target_id)
            self._revision(e, base_revision)
            self._revision(target, target_revision)
            if (entry_id == target_id or e['collection'] != target['collection']
                    or e['status'] != 'active' or target['status'] != 'active' or not reason.strip()):
                raise ValueError('invalid_merge')
            target['sources'] = list(dict.fromkeys(target['sources'] + e['sources']))
            target['tags'] = list(dict.fromkeys(target['tags'] + e['tags']))
            target_result = self._save_revision(data, target, reason)
            e.update(status='merged', merged_into=target_id)
            result = self._save_revision(data, e, reason)
            return dict(source=result, target=target_result)
        return self._write(apply)

    def search_tags(self, query, limit=6):
        data = self._load()
        entries = [e for e in data['entries'].values()
                   if e['collection'] in self.collections and e['status'] == 'active']
        counts = {}
        for e in entries:
            for tag in e['tags']:
                counts[tag] = counts.get(tag, 0) + 1
        terms = re.findall(r'\S+', query.casefold())
        items = []
        for tag in data['tags'].values():
            if tag['id'] not in counts:
                continue
            names = [tag['name'], *tag['aliases']]
            hay = ' '.join([*names, tag['description']]).casefold()
            score = sum(1 for t in terms if t in hay)
            score += sum(3 for name in names if name.casefold() in query.casefold())
            if score:
                items.append(dict(tag, entry_count=counts[tag['id']], score=score))
        items.sort(key=lambda x: (-x['score'], x['id']))
        return dict(items=items[:max(1, min(limit, 20))], total=len(items))

    def index(self):
        data = self._load()
        entries = [e for e in data['entries'].values()
                   if e['collection'] in self.collections and e['status'] == 'active']
        used = {t for e in entries for t in e['tags']}
        categories = {}
        for t in used:
            category = data['tags'][t]['category']
            categories[category] = categories.get(category, 0) + 1
        return dict(protocol_version=1, entries=len(entries), tags=len(used),
                    tag_categories=categories, untagged_entries=sum(not e['tags'] for e in entries))

    def find(self, all_tags, any_tags, limit=6, query=''):
        data = self._load()
        self._tags(data, all_tags)
        self._tags(data, any_tags)
        items = []
        for e in data['entries'].values():
            if e['collection'] not in self.collections or e['status'] != 'active':
                continue
            if not set(all_tags) <= set(e['tags']) or (any_tags and not set(any_tags) & set(e['tags'])):
                continue
            if query and query.casefold() not in (e['title'] + '\n' + e['content']).casefold():
                continue
            items.append(dict(id=e['id'], title=e['title'], summary=e['content'][:80],
                              tags=e['tags'], revision=e['revision']))
        items.sort(key=lambda x: (x['title'], x['id']))
        return dict(items=items[:max(1, min(limit, 20))], total=len(items))

    def read(self, entry_id, revision, offset=0, limit=1200):
        e = self._entry(self._load(), entry_id)
        self._revision(e, revision)
        if e['status'] != 'active':
            return dict(id=e['id'], revision=e['revision'], status=e['status'],
                        merged_into=e.get('merged_into'))
        if offset < 0 or offset > len(e['content']) or limit < 1:
            raise ValueError('invalid_page')
        end = min(len(e['content']), offset + min(limit, 2400))
        return dict(id=e['id'], title=e['title'], revision=e['revision'], tags=e['tags'],
                    content=e['content'][offset:end],
                    next_offset=end if end < len(e['content']) else None)

    def history(self, entry_id, revision):
        data = self._load()
        self._entry(data, entry_id)
        for item in data['history'][entry_id]:
            if item['entry']['revision'] == revision:
                return item
        raise ValueError('unknown_revision')
