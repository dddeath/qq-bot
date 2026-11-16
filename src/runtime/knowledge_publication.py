"""Prepare an immutable index generation, then publish it with the entry snapshot."""
import hashlib
import json
from pathlib import Path
import time
import uuid

from knowledge_graph import nodes_for, compatible, review_request, reviewed_edges

KEY = 'retrieval_publication'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')


def index_path(data, fallback, store_path):
    ref = data.get(KEY)
    if not ref:
        return Path(fallback)
    if ref.get('store_path') != str(Path(store_path).resolve()):
        raise ValueError('knowledge_publication_store_mismatch')
    return Path(ref['index_path'])


class IndexPublisher:
    def __init__(self, index, root, encoder, reviewer):
        self.index, self.root = Path(index), Path(root)
        self.encoder, self.reviewer = encoder, reviewer

    @classmethod
    def from_profile(cls, store, profile_path):
        from knowledge_retrieval import from_profile
        from knowledge_graph import CodexGraphReviewer
        path = Path(profile_path).resolve()
        profile = load(path)
        config = profile.get('publication')
        if not config:
            raise ValueError('knowledge_publication_not_configured')
        if profile['encoder']['kind'] != 'onnx':
            raise ValueError('knowledge_publication_requires_live_encoder')
        engine = from_profile(store, path)
        return cls(path.parent/profile['bundle'], path.parent/config['root'],
                   engine.encoder, CodexGraphReviewer(config.get('reviewer', {})))

    def prepare(self, store_path, before, data):
        """Called under EntryStore's writer lock; it never changes the active store."""
        out = self.root.resolve()/uuid.uuid4().hex
        out.mkdir(parents=True)
        started = time.perf_counter()
        save(out/'before.json', before)
        save(out/'requested.json', data)
        try:
            ref = self._build(store_path, before, data, out)
        except Exception as exc:
            save(out/'receipt.json', dict(status='failed', error=str(exc),
                 seconds=time.perf_counter()-started, published=False))
            raise ValueError('knowledge_publication_failed: '+str(exc)) from exc
        save(out/'receipt.json', dict(status='prepared', reference=ref,
             seconds=time.perf_counter()-started,
             commit_evidence='store.retrieval_publication.generation'))
        return ref

    def _build(self, store_path, before, data, out):
        import numpy as np
        from knowledge_retrieval import RetrievalIndex
        from knowledge_ranking import tokenize
        source = index_path(before, self.index, store_path)
        old = RetrievalIndex(source)
        if old.manifest.get('encoder', {}).get('fingerprint') != self.encoder.identity.get('fingerprint'):
            raise ValueError('retrieval_encoder_identity_mismatch')
        active = {k: v for k, v in data['entries'].items() if v['status'] == 'active'}
        fields = ('revision', 'title', 'content', 'tags', 'collection', 'updated_at')
        changed = {k for k, e in active.items() if any(
            e.get(f) != old.entries.get(k, {}).get(f) for f in fields)}
        invalid = changed | (set(old.entries)-set(active))
        chunks, cv, nodes, nv = [], [], [], []
        encoded = []

        def encode(text, kind, key):
            value, meta = self.encoder.run(text)
            if value.shape != (old.cv.shape[1],) or not np.isfinite(value).all():
                raise ValueError('publication_vector_shape_mismatch')
            encoded.append(dict(kind=kind, entry_id=key, input=text, result=meta))
            return value

        for rows, values, target, vectors in ((old.chunks, old.cv, chunks, cv), (old.nodes, old.nv, nodes, nv)):
            for row, vector in zip(rows, values):
                if row['entry_id'] in active and row['entry_id'] not in invalid:
                    target.append(row)
                    vectors.append(vector)
        for k in sorted(changed):
            e = active[k]
            for start in range(0, len(e['content']), 300):
                text = e['content'][start:start+360]
                chunks.append(dict(entry_id=k, revision=e['revision'], start=start, end=start+len(text), text=text))
                cv.append(encode(text, 'body', k))
                if start+360 >= len(e['content']):
                    break
            for node in nodes_for(e):
                nodes.append(node)
                nv.append(encode(node['text'], 'node', k))
        nv = np.asarray(nv, dtype=np.float32).reshape((-1, old.cv.shape[1]))
        by_parent = {}
        for i, n in enumerate(nodes):
            by_parent.setdefault(n['entry_id'], []).append(i)
        k_limit = old.manifest.get('nomination_K', 2)
        pairs, seen = [], set()
        nominations = {}
        for k in sorted(changed):
            scores = {}
            for other, positions in by_parent.items():
                if other != k and compatible(active[k], active[other]):
                    scores[other] = float(np.max(nv[by_parent[k]] @ nv[positions].T))
            winners = sorted(scores, key=lambda x: (-scores[x], x))[:k_limit]
            nominations[k] = [dict(entry_id=x, score=scores[x]) for x in winners]
            for other in winners:
                key = tuple(sorted((k, other)))
                if key not in seen:
                    seen.add(key)
                    pair_id = hashlib.sha256('|'.join(key).encode()).hexdigest()[:24]
                    pairs.append(dict(id=pair_id, a=k, b=other))
        save(out/'nominations.json', dict(K=k_limit, changed=sorted(changed), candidates=nominations))
        edges = [e for e in old.edges if e['source'] in active and e['target'] in active
                 and not {e['source'], e['target']} & invalid]
        if pairs:
            review_dir = out/'review'
            review_dir.mkdir()
            request = review_request(active, pairs)
            save(review_dir/'request.json', request)
            answer = self.reviewer.review(request, review_dir)
            save(review_dir/'result.json', answer)
            edges.extend(reviewed_edges(request, answer))
        # Keep every reused edge vector exact; encode only new reasons.
        edge_texts = sorted({e['text'] for e in edges})
        old_vec = dict(zip(old.edge_texts, old.ev))
        ev = [old_vec[t] if t in old_vec else encode(t, 'edge', '') for t in edge_texts]
        bundle = out/'index'
        bundle.mkdir()
        tokens = {e['title']+'\n'+e['content']: tokenize(e['title']+'\n'+e['content']) for e in active.values()}
        tags = {k: tokenize(' '.join([v.get('name', ''), v.get('description', ''), *v.get('aliases', [])]))
                for k, v in data['tags'].items()}
        graph_parents = {n['entry_id'] for n in nodes}
        not_built = set(old.manifest.get('graph_coverage', {}).get('not_built_entries', [])) & set(active) - changed
        manifest = {**old.manifest, 'index_id': 'publication-'+out.name,
            'graph_coverage': dict(reviewed_entries=len(graph_parents-not_built),
                not_built_entries=sorted(not_built), rebuilt_entries=sorted(changed),
                policy='evidence_bound_incremental_v2')}
        for name, value in {'index': manifest, 'entries': {'entries': active}, 'tokens': tokens,
                'tag-tokens': tags, 'chunks': chunks, 'nodes': nodes, 'edges': edges,
                'edge-texts': edge_texts}.items():
            save(bundle/(name+'.json'), value)
        for name, values in (('chunks', cv), ('nodes', nv), ('edges', ev)):
            np.save(bundle/(name+'.npy'), np.asarray(values, dtype=np.float32).reshape((-1, old.cv.shape[1])))
        save(out/'encodings.json', encoded)
        # Reopen the exact bundle using the production reader before publication.
        verified = RetrievalIndex(bundle)
        assert set(verified.entries) == set(active)
        return dict(version=1, generation=out.name, index_path=str(bundle),
                    store_path=str(Path(store_path).resolve()),
                    index_id=manifest['index_id'], changed_entries=sorted(changed))
