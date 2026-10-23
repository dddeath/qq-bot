"""Scoped, read-only catalog of formal knowledge and clean published learning."""
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from local_knowledge import Knowledge

USAGES = {'expression', 'reference', 'profile', 'unclassified'}
DEFAULT_POLICY = {'max_candidates': 6, 'summary_chars': 80,
                  'max_fragments': 2, 'read_estimated_tokens': 1200}


def _version(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _body(text):
    return re.sub(r'\A---\s*\n.*?\n---\s*\n', '', text, count=1, flags=re.S).strip()


def _sections(text):
    sections, lines, fence = [], [], None
    for line in text.splitlines(keepends=True):
        marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
        if fence is None and re.match(r'^#{1,6}\s+', line) and lines:
            sections.append(''.join(lines))
            lines = []
        lines.append(line)
    if lines:
        sections.append(''.join(lines))
    return sections


def _estimate(text):
    # Disclosure accounting proxy, not tokenizer or billed token measurement.
    return (len(text.encode('utf-8')) + 1) // 2


class KnowledgeCatalog:
    """Account/group bindings are supplied by the host, never by search arguments."""

    def __init__(self, root, account, group, learning_root=None, policy=None):
        self.root = Path(root).resolve()
        self.account, self.group = str(account), str(group)
        self.learning_root = Path(learning_root).resolve() if learning_root else None
        self.policy = dict(DEFAULT_POLICY, **(policy or {}))
        if set(self.policy) != set(DEFAULT_POLICY) or any(
                type(x) is not int or x < 1 for x in self.policy.values()):
            raise ValueError('invalid_disclosure_policy')

    def _entries(self):
        manifest = self.root / 'catalog.json'
        metadata = json.loads(manifest.read_text(encoding='utf-8-sig'))['documents'] if manifest.is_file() else {}
        entries = {}
        status = {'formal': 'available' if self.root.is_dir() else 'missing',
                  'published_learning': 'not_configured'}
        for path, page in Knowledge(self.root, self.account, self.group).pages.items():
            meta = metadata.get(path, {})
            profile = path.startswith(f'group-memory/{self.account}/{self.group}/')
            if profile and not (self.root / path).resolve().is_relative_to(
                    self.root / 'group-memory' / self.account / self.group):
                continue
            usage = ['profile'] if profile else meta.get('usage', ['unclassified'])
            if not isinstance(usage, list) or not usage or any(x not in USAGES for x in usage):
                raise ValueError('invalid_catalog_usage:' + path)
            body = _body(page['text'])
            if not body:
                continue
            header = re.match(r'\A---\s*\n(.*?)\n---', page['text'], re.S)
            tags = re.search(r'^tags:\s*\[(.*?)\]\s*$', header.group(1), re.M) if header else None
            aliases = meta.get('aliases', [x.strip().strip('\"\'') for x in tags.group(1).split(',')] if tags else [])
            key = 'formal:' + path
            entries[key] = dict(entry_id=key, version=_version(page['text']),
                source='profile' if profile else 'formal', usage=usage,
                domain='group-memory' if profile else path.split('/')[0] if '/' in path else 'general',
                title=page['title'] or path, aliases=aliases, updated=page['updated'], path=path,
                scope={'account': self.account, 'group': self.group} if profile else None,
                text=body)
        if self.learning_root and self.account.isdigit() and self.group.isdigit():
            path = self.learning_root / 'groups' / self.account / self.group / 'learning.sqlite3'
            if not path.is_file():
                status['published_learning'] = 'missing'
            elif path.resolve() != self.learning_root / 'groups' / self.account / self.group / 'learning.sqlite3':
                status['published_learning'] = 'scope_mismatch'
            else:
                with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
                    rows = db.execute('SELECT kind,id,body FROM published ORDER BY kind,id').fetchall()
                status['published_learning'] = 'available'
                for kind, identity, raw in rows:
                    if kind not in ('expressions', 'meanings'):
                        continue
                    value = json.loads(raw)
                    fields = ('situation', 'surface_form', 'style') if kind == 'expressions' else (
                        'term', 'meaning', 'usage', 'conditions', 'kind')
                    clean = {k: value[k] for k in fields if isinstance(value.get(k), str)}
                    body = '\n'.join(f'{k}: {v}' for k, v in clean.items())
                    usage = ['expression'] if kind == 'expressions' else (
                        ['reference'] if clean.get('kind') == 'fact' else ['expression', 'reference'])
                    key = f'learning:{self.account}:{self.group}:{kind}:{identity}'
                    entries[key] = dict(entry_id=key, version=_version(body), source='published_learning',
                        usage=usage, domain='group-learning', title=clean.get('term', clean.get('surface_form', str(identity))),
                        aliases=[], updated=None, scope={'account': self.account, 'group': self.group}, text=body)
        elif self.learning_root:
            status['published_learning'] = 'scope_unbound'
        return entries, status

    def search(self, query, usage='', domain='', limit=6):
        if usage and usage not in USAGES:
            raise ValueError('unknown_knowledge_usage')
        if type(limit) is not int or limit < 1:
            raise ValueError('invalid_candidate_limit')
        entries, status = self._entries()
        terms = re.findall(r'[a-z0-9_-]+|[\u4e00-\u9fff]+', query.casefold())
        grams = {t[i:i+2] for t in terms if re.search(r'[\u4e00-\u9fff]', t) for i in range(len(t)-1)}
        results = []
        for row in entries.values():
            if usage and usage not in row['usage'] or domain and domain != row['domain']:
                continue
            text = row['text'].casefold()
            title = (row['title'] + ' ' + ' '.join(row['aliases'])).casefold()
            score = sum(8*(t in title)+3*(t in text) for t in terms) + sum(g in text for g in grams)
            if not score and query.strip():
                continue
            pos = min((text.find(t) for t in terms if t in text), default=0)
            summary = row['text'][max(0, pos-20):][:self.policy['summary_chars']]
            sections = _sections(row['text'])
            section = max(range(len(sections)), key=lambda i: sum(
                3*(t in sections[i].casefold()) for t in terms) + sum(g in sections[i].casefold() for g in grams))
            results.append({k: v for k, v in row.items() if k != 'text'} | {
                'score': score, 'summary': summary,
                'read': {'entry_id': row['entry_id'], 'version': row['version'], 'section': section, 'offset': 0}})
        results.sort(key=lambda x: (-x['score'], x['entry_id']))
        return {'results': results[:min(limit, self.policy['max_candidates'])],
                'matched': len(results), 'sources': status}

    def index(self):
        entries, status = self._entries()
        counts = {}
        for row in entries.values():
            for usage in row['usage']:
                key = row['domain'] + ':' + usage
                counts[key] = counts.get(key, 0) + 1
        return {'entries': len(entries), 'categories': counts, 'sources': status}

    def read(self, entry_id, version, section=0, offset=0):
        entries, status = self._entries()
        row = entries.get(entry_id)
        if row is None:
            return {'found': False, 'error': 'unknown_entry', 'sources': status}
        if row['version'] != version:
            return {'found': False, 'error': 'version_changed', 'version': row['version']}
        sections = _sections(row['text'])
        if (type(section) is not int or type(offset) is not int or section < 0
                or section >= len(sections) or offset < 0 or offset >= len(sections[section])):
            raise ValueError('invalid_read_cursor')
        maximum = self.policy['read_estimated_tokens']
        used, fragments = 0, []
        while section < len(sections) and len(fragments) < self.policy['max_fragments']:
            text = sections[section][offset:]
            lo, hi = 0, len(text)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if _estimate(text[:mid]) <= maximum-used:
                    lo = mid
                else:
                    hi = mid-1
            if lo == 0:
                if not fragments:
                    raise ValueError('read_budget_too_small_for_character')
                break
            value = text[:lo]
            fragments.append({'section': section, 'offset': offset, 'text': value})
            used += _estimate(value)
            offset += lo
            if offset == len(sections[section]):
                section, offset = section+1, 0
            else:
                break
        continuation = dict(entry_id=entry_id, version=version, section=section, offset=offset) if section < len(sections) else None
        return {'found': True, 'entry_id': entry_id, 'version': version,
                'source': row['source'], 'usage': row['usage'], 'fragments': fragments,
                'next': continuation, 'complete': continuation is None,
                'budget': {'unit': 'estimated_tokens', 'method': 'ceil_utf8_bytes_div_2_per_fragment',
                           'scope': 'fragment_text_only', 'used': used, 'limit': maximum}}
