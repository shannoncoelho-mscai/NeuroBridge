"""Leakage-safe, domain-spread, deterministic splitting.

* Near-duplicate clusters are assigned as a unit, so paraphrases of one scenario never land
  in two splits.
* Split sizes are global targets (e.g. 15% of all records). Clusters for the non-first
  splits are drawn round-robin across domains, so small domains (3 examples each, as in the
  NeuroBridge seed set) are spread across splits instead of rounding to zero.
* Seeded and order-independent (sorted by id before shuffling).
"""
import random
from collections import defaultdict


def split_records(records, ratios=(0.85, 0.15), names=("train", "validation"), seed=42):
    assert abs(sum(ratios) - 1) < 1e-9 and len(ratios) == len(names)
    clusters = defaultdict(list)
    for r in sorted(records, key=lambda r: r.id):
        clusters[r.cluster_id or r.id].append(r)
    by_domain = defaultdict(list)
    for cid in sorted(clusters):
        members = clusters[cid]
        by_domain[members[0].domain or "unknown"].append(members)
    rng = random.Random(seed)
    domains = sorted(by_domain)
    rng.shuffle(domains)
    for d in domains:
        rng.shuffle(by_domain[d])
    # round-robin interleave: one cluster per domain per pass
    interleaved, depth = [], 0
    while any(depth < len(by_domain[d]) for d in domains):
        for d in domains:
            if depth < len(by_domain[d]):
                interleaved.append(by_domain[d][depth])
        depth += 1

    total = len(records)
    targets = [round(total * r) for r in ratios]
    counts = [0] * len(names)
    for group in interleaved:
        # fill later splits first (they are small), first split takes the remainder
        k = 0
        for i in range(1, len(names)):
            if counts[i] + len(group) <= targets[i] or counts[i] == 0 and targets[i] > 0:
                k = i
                break
        for r in group:
            r.split = names[k]
        counts[k] += len(group)
    return {n: [r for r in records if r.split == n] for n in names}
