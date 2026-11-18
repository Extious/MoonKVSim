"""One physical KV chunk per admission decision; CPU metadata reference only.

The earlier prefix-bundle planner stays available in simple_slacklandlord.py.
This entry point never adds missing ancestors or a second new chunk implicitly.
"""
from fractions import Fraction as Q

from simple_slacklandlord import LazyValue, Plan


def decide_chunk(model, current, capacity, chunk, *, pinned=0, available=None, values=None):
    """Admit x only if its modeled WCT benefit pays for legal leaf reclamation.

    The caller records Agent references/current rounds before calling, retains
    LazyValue across events, and serializes physical release/copy/commit. A
    reduced quota must be reclaimed separately before admitting a new chunk.
    """
    m = model
    if capacity < 0 or not m.legal(current) or not m.legal(pinned) or pinned & ~current:
        raise ValueError('invalid capacity, committed set or pinned prefix')
    if chunk not in m.index:
        raise ValueError('unknown physical chunk')
    available = m.all_mask if available is None else available
    if available < 0 or available & ~m.all_mask:
        raise ValueError('unknown source chunk')
    if values is None:
        values = LazyValue(m)
    elif values.model is not m:
        values.update(m)
    i = m.index[chunk]
    bit = 1 << i
    if current & bit:
        return Plan('REUSE', current)
    if m.size(current) > capacity:
        return Plan('WAIT_FOR_RECLAIM', current)
    if not available & bit:
        return Plan('WAIT_FOR_SOURCE', current)
    if m.ancestors[i] & current != m.ancestors[i]:
        return Plan('WAIT_FOR_PREFIX', current)
    protected = m.ancestors[i] | bit | pinned
    if m.size(protected) > capacity:
        return Plan('BYPASS', current)

    children = [0] * len(m.chunks)
    for j, parent in enumerate(m.parents):
        if parent >= 0:
            children[parent] |= 1 << j
    draft = current | bit
    baseline = values(current)
    gain = values(draft) - baseline
    if gain <= 0:
        return Plan('BYPASS', current)
    rent = Q(0)
    victims = []
    while m.size(draft) > capacity:
        value = values(draft)
        choices = []
        for j, c in enumerate(m.chunks):
            if (draft >> j & 1 and not protected >> j & 1
                    and not children[j] & draft):
                loss = value - values(draft ^ (1 << j))
                choices.append((loss / c.size, c.key, j, loss))
        if not choices:
            return Plan('BYPASS', current)
        _, key, j, loss = min(choices)
        draft ^= 1 << j
        victims.append(key)
        rent += loss
    credit = gain - rent
    if credit <= 0:
        return Plan('BYPASS', current)
    return Plan('REPLACE' if victims else 'ADMIT', draft, gain, rent, credit, tuple(victims))
