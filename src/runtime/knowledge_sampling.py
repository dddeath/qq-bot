"""Host-side retrieval probability; the model supplies only subjective inclination."""
import math
import secrets

VERSION = 'knowledge-sampling-v1'


def unit_value(value, name):
    if type(value) not in (int, float) or not 0 <= value <= 1 or not math.isfinite(value):
        raise ValueError('invalid_' + name)
    return value


def evaluate(subjective, base, limit, draw):
    """Evaluate an observed draw; also used for paired counterfactual replay."""
    s = unit_value(subjective, 'subjective_inclination')
    b = unit_value(base, 'gain_inclination')
    a = unit_value(limit, 'gain_adjustment_limit')
    if s in (0, 1):
        probability, adjustment, draw = s, None, None
        branch = 'no_gain' if s == 0 else 'clear_gain'
        retrieve = bool(s)
    else:
        unit_value(draw, 'sampling_draw')
        if draw == 1:
            raise ValueError('invalid_sampling_draw')
        adjustment = a * (2*s - 1)
        probability = max(0, min(1, b + adjustment))
        branch, retrieve = 'sampled', draw < probability
    return dict(protocol_version=VERSION, subjective_inclination=s,
                gain_inclination=b, gain_adjustment_limit=a,
                adjustment=adjustment, probability=probability, draw=draw,
                branch=branch, retrieve=retrieve)


def sample(subjective, configuration):
    unit_value(subjective, 'subjective_inclination')
    draw = None if subjective in (0, 1) else secrets.SystemRandom().random()
    return evaluate(subjective, configuration['gain_inclination'],
                    configuration['gain_adjustment_limit'], draw)
