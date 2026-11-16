"""One candidate pipeline for MCP and replay, bound to an existing EntryStore."""
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from knowledge_passages import preview, selected_passages, tok
from knowledge_query import QUERY_TEXT_MAX, supports_expression, validate_candidate_arguments
from knowledge_ranking import BM25, compile_edges, diffuse, fuse, normal, rank, tokenize
from knowledge_retrieval_policy import RetrievalPolicy, RAW_LIMIT, FINAL_LIMIT, RRF_CONSTANT
from knowledge_fusion import merge_candidates
from knowledge_literal import nominate

VERSION = 'local-retrieval-v1-20261105'
PARAMETERS = RetrievalPolicy().parameters()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


class FrozenQueryEncoder:
    """Real, previously encoded query vectors. Missing text remains a replay gap."""
    def __init__(self, path):
        self.values = load_json(path)
        identities = {json.dumps(v.get('meta', {}).get('encoder'), sort_keys=True)
                      for v in self.values.values()}
        if len(identities) > 1:
            raise ValueError('retrieval_encoder_identity_mismatch')
        self.identity = json.loads(next(iter(identities))) if identities else None

    def run(self, text, query=True):
        import numpy as np
        if not query or text not in self.values:
            raise ValueError('query_encoding_missing')
        item = self.values[text]
        return np.asarray(item['vec'], dtype=np.float32), dict(item['meta'], replay_reused=True)


class RetrievalIndex:
    """Immutable index data, without grants or model-created scope."""
    def __init__(self, root):
        import numpy as np
        root = Path(root)
        self.manifest = load_json(root/'index.json')
        if self.manifest['version'] != VERSION:
            raise ValueError('retrieval_index_version_mismatch')
        self.entries = load_json(root/'entries.json')['entries']
        self.tokens = load_json(root/'tokens.json')
        self.tags = load_json(root/'tag-tokens.json')
        self.chunks = load_json(root/'chunks.json')
        self.cv = np.load(root/'chunks.npy', allow_pickle=False)
        self.nodes = load_json(root/'nodes.json')
        self.nv = np.load(root/'nodes.npy', allow_pickle=False)
        self.edges = load_json(root/'edges.json')
        self.edge_texts = load_json(root/'edge-texts.json')
        self.ev = np.load(root/'edges.npy', allow_pickle=False)
        self.edge_positions = {text: i for i, text in enumerate(self.edge_texts)}
        for rows, values in ((self.chunks, self.cv), (self.nodes, self.nv), (self.edge_texts, self.ev)):
            if len(rows) != len(values) or values.ndim != 2 or values.shape[1] != self.cv.shape[1]:
                raise ValueError('retrieval_index_shape_mismatch')


class KnowledgeRetrieval:
    def __init__(self, store, index, encoder, *, cutoff=None, policy=None):
        self.store, self.index, self.encoder = store, index, encoder
        self.base_index = index
        self.policy = RetrievalPolicy.load(policy)
        indexed_k = index.manifest.get('nomination_K')
        if indexed_k is not None and indexed_k != self.policy.nomination_K:
            raise ValueError('retrieval_graph_policy_mismatch')
        if indexed_k is None and self.policy.nomination_K != 2:
            raise ValueError('retrieval_graph_policy_not_recorded')
        self.cutoff = datetime.fromisoformat(cutoff) if cutoff else None
        if self.cutoff and self.cutoff.tzinfo is None:
            raise ValueError('retrieval_cutoff_requires_timezone')
        self.vectors = {}
        self.literal_records = {}

    def vector(self, text):
        if text not in self.vectors:
            value = self.encoder.run(text, query=True)
            if value[0].shape != (self.index.cv.shape[1],):
                raise ValueError('retrieval_query_dimension_mismatch')
            self.vectors[text] = value
        return self.vectors[text]

    def view(self):
        data = self.store._load()
        ref = data.get('retrieval_publication')
        if not ref and self.index is not self.base_index:
            self.index = self.base_index
            self.literal_records.clear()
        if ref:
            from knowledge_publication import index_path
            selected_path = index_path(data, '', self.store.path)
        if ref and ref['index_id'] != self.index.manifest['index_id']:
            index = RetrievalIndex(selected_path)
            if index.manifest['index_id'] != ref['index_id']:
                raise ValueError('knowledge_publication_index_mismatch')
            if index.manifest.get('encoder', {}).get('fingerprint') != self.encoder.identity.get('fingerprint'):
                raise ValueError('retrieval_encoder_identity_mismatch')
            if index.manifest.get('nomination_K', 2) != self.policy.nomination_K:
                raise ValueError('retrieval_graph_policy_mismatch')
            self.index = index
            self.literal_records.clear()
        current = self.store.retrieval_view(data)
        cutoff = self.cutoff or datetime.now(timezone.utc)
        entries, visible = {}, {}
        excluded = dict(index_missing=0, index_revision_changed=0, newer_than_cutoff=0)
        # Recheck the live store each time: an index cannot restore revoked entries.
        for key, item in current.items():
            if item['collection'] not in self.store.collections or item['status'] != 'active':
                continue
            indexed = self.index.entries.get(key)
            if indexed is None:
                excluded['index_missing'] += 1
                continue
            if any(indexed.get(f) != item.get(f) for f in ('revision', 'title', 'content', 'tags', 'collection', 'updated_at')):
                excluded['index_revision_changed'] += 1
                continue
            try:
                updated_at = datetime.fromisoformat(item.get('updated_at'))
                if updated_at.tzinfo is None:
                    raise ValueError('updated_at_requires_timezone')
            except (TypeError, ValueError):
                excluded['invalid_updated_at'] = excluded.get('invalid_updated_at', 0) + 1
                continue
            entries[key] = item
            if updated_at > cutoff:
                excluded['newer_than_cutoff'] += 1
            else:
                visible[key] = item
        return entries, visible, dict(cutoff=cutoff.isoformat(), visible=len(visible), excluded=excluded)

    def documents(self, text, entries, eligible=None):
        start = time.perf_counter()
        index = self.index
        terms = index.tokens.get(text)
        if terms is None:
            terms = tokenize(text)
        bm = BM25({k: index.tokens[e['title']+'\n'+e['content']] for k, e in entries.items()})
        tb = BM25(index.tags)
        tag_scores = normal(dict(rank(tb.scores(terms), 3)))
        bs = bm.scores(terms)
        ds, ns = normal(bs), normal(dict(fuse((1, rank(bs)), constant=RRF_CONSTANT)))
        scores = {k: ds.get(k, 0)+.1*ns.get(k, 0)+.25*max((tag_scores.get(t, 0) for t in e['tags']), default=0)
                  for k, e in entries.items()}
        cr = rank({k: v for k, v in scores.items() if eligible is None or k in eligible}, RAW_LIMIT)
        lexical = time.perf_counter()-start
        t = time.perf_counter()
        vector, meta = self.vector(text)
        encoded = time.perf_counter()-t
        best, winning = {}, {}
        values = index.cv @ vector
        for i, child in enumerate(index.chunks):
            key = child['entry_id']
            if key in entries:
                score = float(values[i])
                if key not in best or score > best[key]:
                    best[key], winning[key] = score, child
        vr = rank({k: v for k, v in best.items() if eligible is None or k in eligible}, RAW_LIMIT)
        matches = [dict(entry_id=key, revision=entries[key]['revision'],
                        offset=winning[key]['start'], limit=winning[key]['end']-winning[key]['start'],
                        score=score) for key, score in vr]
        return dict(query=text, C=cr, V=vr, D=fuse((1, cr), (1, vr), constant=RRF_CONSTANT),
                    vector_matches=matches,
                    graph_executed=False, encoder=meta,
                    timing=dict(lexical=lexical, encoding=encoded, total=time.perf_counter()-start))

    def graph(self, text, entries, eligible=None):
        import numpy as np
        start = time.perf_counter()
        vector, meta = self.vector(text)
        values = self.index.nv @ vector
        base = {}
        for i, node in enumerate(self.index.nodes):
            key = node['entry_id']
            if key in entries:
                base[key] = max(base.get(key, -2.), float(values[i]))
        policy = self.policy
        seeds = sorted(base, key=lambda k: (-base[k], k))[:policy.seed_parents]
        affinity = self.index.ev @ vector
        links = [(e['source'], e['target'], float(affinity[self.index.edge_positions[e['text']]]), e['text'])
                 for e in self.index.edges if e['source'] in base and e['target'] in base]
        scores, paths = diffuse(base, seeds, compile_edges(links, policy.edge_match),
                                policy.alpha, policy.edge_match, policy.continuation, policy.hops)
        # Facts may seed or bridge diffusion; eligibility only limits nominations.
        output = sorted((k for k in scores if eligible is None or k in eligible),
                        key=lambda k: (-scores[k], k))[:RAW_LIMIT]
        return dict(query=text, direct=seeds, ranked=[(k, scores[k]) for k in output],
                    paths=paths, graph_executed=True, encoder=meta,
                    timing=dict(total=time.perf_counter()-start))

    def literal_candidates(self, query, entries, eligible):
        """Nominate declared identities with source-local evidence."""
        return nominate(query, entries, eligible, FINAL_LIMIT, self.literal_records)

    def search(self, purpose, query, keywords='', need=''):
        validate_candidate_arguments(purpose, query, keywords, need)
        started = time.perf_counter()
        entries, visible, coverage = self.view()
        eligible = {k for k, item in visible.items()
                    if not (item['title'].endswith('索引') or item['title'] in ('群聊知识库', '群成员记忆'))
                    and (purpose == 'information' or supports_expression(item, self.store.documents))}
        doc = self.documents(query, visible, eligible)
        channels = {'documents': doc}
        fusion = None
        literal_ids = set()
        if purpose == 'information':
            literal_ids, literal_matches, literal_evidence = self.literal_candidates(query, visible, eligible)
            regular = [k for k, _ in doc['D']]
            priority = sorted(literal_ids, key=lambda key: (regular.index(key) if key in regular else RAW_LIMIT, key))
            ids = (priority + [key for key in regular if key not in literal_ids])[:FINAL_LIMIT]
            channels['literal'] = dict(matches=literal_matches, nominated=priority, evidence=literal_evidence)
            terms = [tok(query)]
        else:
            channels.update({name: self.graph(text, visible, eligible) for name, text in (('keywords', keywords), ('need', need))})
            clue = [k for k, _ in doc['D']]
            lanes = {name:[k for k, _ in channels[name]['ranked']] for name in ('keywords', 'need')}
            fusion = merge_candidates(dict(lanes, clue=clue), self.policy)
            ids = fusion['final']
            terms = [tok(text) for text in (query, keywords, need)]
        candidates = []
        vector_matches = {m['entry_id']: m for m in doc['vector_matches']}
        for key in ids:
            entry = visible[key]
            pages = [dict(entry_id=key, revision=entry['revision'], offset=offset, limit=limit,
                        heading=heading, preview=preview(text, terms, source=entry['content'], offset=offset), selected_by=method)
                     for (offset, limit, heading, text), method in
                     selected_passages(entry, terms, vector_matches.get(key),
                                       literal_evidence=literal_evidence.get(key, ())
                                       if key in literal_ids else ())]
            candidates.append(dict(entry_id=key, revision=entry['revision'], title=entry['title'], passages=pages))
        return dict(protocol_version=VERSION, index_id=self.index.manifest['index_id'], purpose=purpose,
                    encoder=self.index.manifest.get('encoder'),
                    query=query, keywords=keywords, need=need, parameters=self.policy.parameters(), fusion=fusion,
                    view=coverage, channels=channels, candidates=candidates,
                    seconds=time.perf_counter()-started)

    def retrieve(self, purpose, query, keywords='', need=''):
        return self.menu(self.search(purpose, query, keywords, need))

    @staticmethod
    def menu(result):
        """Only actionable references enter the model's material budget."""
        from reading_result import model_material
        return model_material({key: result[key] for key in
                ('protocol_version', 'index_id', 'purpose', 'view', 'candidates')})


def from_profile(store, path):
    path = Path(path)
    profile = load_json(path)
    if profile['version'] != VERSION:
        raise ValueError('retrieval_profile_version_mismatch')
    root = path.parent/profile['bundle']
    config = profile['encoder']
    if config['kind'] == 'frozen_queries':
        encoder = FrozenQueryEncoder(root/config['path'])
    elif config['kind'] == 'onnx':
        from knowledge_embedding import Encoder
        encoder = Encoder(path.parent/config['root'], 'embedding')
    else:
        raise ValueError('unknown_knowledge_encoder')
    index = RetrievalIndex(root)
    expected = index.manifest.get('encoder', {})
    actual = getattr(encoder, 'identity', None) or {}
    if expected.get('fingerprint'):
        if expected['fingerprint'] != actual.get('fingerprint'):
            raise ValueError('retrieval_encoder_identity_mismatch')
    elif config['kind'] == 'onnx':
        if any(expected.get(k) != actual.get(k) for k in ('repository', 'revision', 'normalization')):
            raise ValueError('retrieval_encoder_identity_mismatch')
    if actual.get('dimensions') and actual['dimensions'] != index.cv.shape[1]:
        raise ValueError('retrieval_index_dimension_mismatch')
    return KnowledgeRetrieval(store, index, encoder, cutoff=profile.get('cutoff'), policy=profile.get('policy'))
