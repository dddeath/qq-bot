"""Bounded group/topic state. No network, QQ sender, or live chat integration."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Limits:
    max_messages: int = 200
    max_age_seconds: float = 1800
    max_total_chars: int = 24000

    def __post_init__(self):
        if min(self.max_messages, self.max_age_seconds, self.max_total_chars) <= 0:
            raise ValueError('limits must be positive')


def bounded(messages, limits, now):
    kept = [m for m in messages if now - m['at'] <= limits.max_age_seconds]
    while len(kept) > limits.max_messages or sum(len(m['text']) for m in kept) > limits.max_total_chars:
        kept.pop(0)
    return kept
