"""Host-bound retrieval policy; labels and runtime model choices never alter it."""
from dataclasses import dataclass, asdict
import math

RAW_LIMIT = 20
FINAL_LIMIT = 6
PASSAGES_PER_PARENT = 3
PAGE_CHARACTERS = 280
RRF_CONSTANT = 5


@dataclass(frozen=True)
class RetrievalPolicy:
    nomination_K: int = 2
    seed_parents: int = 20
    alpha: float = .2
    edge_match: float = .447
    continuation: float = .58
    hops: int = 3
    per_channel: int = 6
    merge_strategy: str = 'round_robin'
    clue_weight: float = 1.

    @classmethod
    def load(cls, value=None):
        value = {} if value is None else value
        if not isinstance(value, dict) or set(value)-set(cls.__dataclass_fields__):
            raise ValueError('invalid_retrieval_policy_fields')
        result = cls(**value)
        for name in ('nomination_K', 'seed_parents', 'per_channel', 'hops'):
            number = getattr(result, name)
            if type(number) is not int or number < (0 if name == 'hops' else 1):
                raise ValueError('invalid_retrieval_policy:'+name)
        if result.hops > 3 or result.per_channel not in (6,20):
            raise ValueError('invalid_retrieval_policy_budget')
        for name in ('alpha', 'edge_match', 'continuation', 'clue_weight'):
            number = getattr(result, name)
            if type(number) not in (int,float) or not math.isfinite(number) or not 0 <= number <= (1.5 if name == 'clue_weight' else 1):
                raise ValueError('invalid_retrieval_policy:'+name)
        if result.merge_strategy not in ('round_robin','rrf'):
            raise ValueError('unknown_fusion_strategy')
        if result.merge_strategy == 'round_robin' and result.clue_weight != 1:
            raise ValueError('round_robin_has_no_score_weight')
        return result

    def parameters(self):
        return dict(raw_limit=RAW_LIMIT, final_limit=FINAL_LIMIT, passages_per_parent=PASSAGES_PER_PARENT,
                    page_characters=PAGE_CHARACTERS, rrf_constant=RRF_CONSTANT, **asdict(self))
