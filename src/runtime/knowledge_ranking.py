"""Frozen lexical and graph ranking primitives; no host or replay dependencies."""
import collections
import math
import re
from knowledge_retrieval_policy import RAW_LIMIT, RRF_CONSTANT

STOP = set('的 了 是 在 与 和 或 等 这 那 一个 这个 可以 进行 用于 查找 相关 内容 资料 时'.split())


def tokenize(text):
    import jieba
    text = text.casefold()
    words = [w.strip() for w in jieba.cut(text, HMM=False)
             if re.fullmatch(r'[\w\u4e00-\u9fff]+', w) and w not in STOP]
    for part in re.findall(r'[\u4e00-\u9fff]+', text):
        words.extend(part[i:i+2] for i in range(len(part)-1) if part[i:i+2] not in STOP)
    return words


def rank(scores, limit=RAW_LIMIT):
    return sorted(((k, float(v)) for k, v in scores.items() if v > 0),
                  key=lambda x: (-x[1], x[0]))[:limit]


def fuse(*channels, constant=RRF_CONSTANT, limit=RAW_LIMIT):
    scores = collections.defaultdict(float)
    for weight, rows in channels:
        for i, (key, _) in enumerate(rows):
            scores[key] += weight / (constant+i+1)
    return rank(scores, limit)


def normal(scores):
    top = max(scores.values(), default=0)
    return {k: v/top for k, v in scores.items()} if top else {}


class BM25:
    def __init__(self, rows):
        self.rows = {k: collections.Counter(v) for k, v in rows.items()}
        self.length = {k: sum(c.values()) for k, c in self.rows.items()}
        self.avg = sum(self.length.values()) / max(1, len(rows))
        self.df = collections.Counter(t for c in self.rows.values() for t in c)

    def scores(self, terms):
        out = {}
        n = len(self.rows)
        for key, counts in self.rows.items():
            total = 0
            for term in set(terms):
                f = counts.get(term, 0)
                if f:
                    total += math.log(1+(n-self.df[term]+.5)/(self.df[term]+.5))*f*2.2 / (
                        f+1.2*(.25+.75*self.length[key]/max(1, self.avg)))
            if total:
                out[key] = total
        return out


def compile_edges(links, threshold):
    grouped = collections.defaultdict(dict)
    for a, b, val, label in links:
        if a == b or val < threshold or val <= 0:
            continue
        terms = grouped[a, b]
        terms[label] = max(terms.get(label, 0.), min(1., float(val)))
    adj = collections.defaultdict(list)
    for (a, b), terms in sorted(grouped.items()):
        affinity = 1-math.prod(1-x for x in terms.values())
        adj[a].append((b, affinity, sorted(terms.items())))
    return dict(adj)


def diffuse(base, seeds, links, alpha, threshold, forward, hops):
    if not 0 <= alpha <= 1 or not 0 <= threshold <= 1 or forward < 0 or type(hops) is not int or not 0 <= hops <= 3:
        raise ValueError('invalid_diffusion_parameters')
    scores = {k: base[k] for k in seeds}
    best, records = {}, {}
    front = [(k, k, base[k], (k,), ()) for k in seeds]
    if alpha <= 0 or hops == 0:
        return scores, []
    adj = links if isinstance(links, dict) else compile_edges(links, threshold)
    for depth in range(1, hops+1):
        pending = {}
        for root, u, mass, path, steps in front:
            if depth > 1 and scores[u] <= forward:
                continue
            enabled = [item for item in adj.get(u, ()) if item[0] not in path]
            den = max(1., sum(v for _, v, _ in enabled))
            for v, w, labels in enabled:
                val = alpha*mass*w/den
                key = root, v
                if val <= best.get(key, 0.) or val <= pending.get(key, (0.,))[0]:
                    continue
                step = u, v, labels, w, den, mass, val
                pending[key] = val, path+(v,), steps+(step,)
        front = []
        for key, (val, path, steps) in sorted(pending.items()):
            root, v = key
            extra = val-best.get(key, 0.)
            best[key] = val
            scores[v] = scores.get(v, base[v])+extra
            front.append((root, v, extra, path, steps))
            records[key] = dict(root=root, target=v, path=path, hops=len(path)-1, support=val, steps=steps)
        if not front:
            break
    return scores, list(records.values())
