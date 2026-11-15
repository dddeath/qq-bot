"""Merge parent identities without changing independently ranked source lanes."""
from itertools import zip_longest
from knowledge_retrieval_policy import FINAL_LIMIT, RRF_CONSTANT


def merge_candidates(lanes, policy):
    names = ['keywords', 'need']+(['clue'] if policy.clue_weight > 0 else [])
    used = {n:list(dict.fromkeys(lanes.get(n, [])))[:policy.per_channel] for n in names}
    ranks = {n:{k:i+1 for i,k in enumerate(ids)} for n,ids in used.items()}
    rows = []
    for key in sorted(set().union(*map(set, used.values()))):
        raw = {n:1/(RRF_CONSTANT+ranks[n][key]) if key in ranks[n] else 0 for n in names}
        contributions = dict(raw)
        if 'clue' in contributions:
            contributions['clue'] *= policy.clue_weight
        graph = contributions['keywords']+contributions['need']
        rows.append(dict(entry_id=key, score=graph+contributions.get('clue',0),
                         graph_contribution=graph, ranks={n:ranks[n].get(key) for n in names},
                         contributions=contributions, raw_contributions=raw))
    rows.sort(key=lambda r:(-r['score'],r['entry_id']))
    ids = [r['entry_id'] for r in rows]
    if policy.merge_strategy == 'round_robin':
        ids = list(dict.fromkeys(k for row in zip_longest(*(used[n] for n in names)) for k in row if k))
        byid = {r['entry_id']:r for r in rows}
        rows = [dict(byid[k],score=None,graph_contribution=None) for k in ids]
    for i,row in enumerate(rows):
        row.update(rank=i+1,selected=i<FINAL_LIMIT)
    return dict(policy=dict(strategy=policy.merge_strategy,input_limit=policy.per_channel,
                            final_limit=FINAL_LIMIT,include_clue=policy.clue_weight>0,constant=RRF_CONSTANT,
                            clue_weight=policy.clue_weight),
                final=ids[:FINAL_LIMIT],ordered=ids,lanes=used,ranking=rows)
