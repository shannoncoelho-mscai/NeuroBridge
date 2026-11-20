"""Record- and dataset-level quality checks.

Severity: "error" excludes a record from training; "warn" keeps it but reports it.
Each check targets a defect actually observed in the NeuroBridge data (see
docs/LLM_AND_PLATFORM_AUDIT.md), not hypothetical ones.
"""
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root -> agent.*
from agent.safety.policy import check_output, classify_input  # noqa: E402

# Instructions-to-the-model that leaked into responses (observed in the 12k templated set).
LEAK_PATTERNS = [
    r"avoid assuming the user has the same needs",
    r"use clear sequencing, specific actions",
    r"\bas an ai (?:language )?model\b",
    r"\byou are neurobridge\b",
    r"\bsystem prompt\b",
    r"\bkeep the suggestions flexible\b",
    r"\bthe assistant should\b",
    r"\brespond (?:in|with) (?:a|an) [a-z]+ tone\b",
]
# Template splice: "...dealing with X, Try choosing" (lowercase clause, comma, capital verb).
SPLICE_RE = re.compile(r"\b(?:with|about|of|for) [a-z][^.?!\n]{2,80}, (?:Try|Separate|Choose|Write|Start|Use|"
                       r"Keep|Consider|If|Ask|Focus|Pick|Make|Break)\b")
CRISIS_SUPPORT_RE = re.compile(r"\b(?:112|14416|emergency|crisis|helpline|hotline|ambulance|"
                               r"doctor|trusted person|someone you trust|right away|immediately|urgent)\b",
                               re.IGNORECASE)
NUMBERED_ITEM_RE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+", re.MULTILINE)


def normalize_text(text):
    if text is None:
        return None
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def words(text):
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def shingles(text, n=3):
    w = words(text)
    return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def check_record(rec, cfg):
    p, r = rec.prompt, rec.response
    if not p or len(p) < cfg["min_prompt_chars"]:
        rec.flag("prompt_too_short", "error", f"{len(p or '')} chars")
    if rec.role != "eval_prompts":  # quarantine too: report why it is excluded
        if not r:
            rec.flag("missing_response", "error")
            return rec
        if len(r) < cfg["min_response_chars"]:
            rec.flag("response_too_short", "error", f"{len(r)} chars")
        if len(r) > cfg["max_response_chars"]:
            rec.flag("response_long", "warn", f"{len(r)} chars")
        for pat in LEAK_PATTERNS:
            if re.search(pat, r, re.IGNORECASE):
                rec.flag("leaked_instruction", "error", pat)
                break
        if SPLICE_RE.search(r):
            rec.flag("template_splice", "error", SPLICE_RE.search(r).group(0)[:60])
        if not re.search(r"[.!?)\]\"'”:]\s*$", r):
            rec.flag("possibly_truncated", "warn", r[-40:])
        items = len(NUMBERED_ITEM_RE.findall(r))
        if items > cfg["max_list_items"]:
            rec.flag("list_heavy", "warn", f"{items} list items")
        out = check_output(r)
        if out["flagged"]:
            rec.flag("unsafe_response", "error", "; ".join(out["reasons"]))
        inp = classify_input(p)
        if inp["halt_agent"] and not CRISIS_SUPPORT_RE.search(r):
            rec.flag("crisis_without_safety_route", "error", inp["category"])
    return rec


def near_duplicate_clusters(records, threshold, field="prompt"):
    """Greedy single-link clustering on word-3-gram Jaccard (fine for <50k rows)."""
    sh = [shingles(getattr(r, field)) for r in records]
    parent = list(range(len(records)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    # Bucket by rare shingles to avoid O(n^2) on large sets.
    index = defaultdict(list)
    for i, s in enumerate(sh):
        for g in sorted(s)[:12]:  # deterministic (set order depends on PYTHONHASHSEED)
            index[g].append(i)
    checked = set()
    for bucket in index.values():
        if len(bucket) > 500:
            continue
        for a_i, a in enumerate(bucket):
            for b in bucket[a_i + 1:]:
                key = (a, b)
                if key in checked:
                    continue
                checked.add(key)
                if jaccard(sh[a], sh[b]) >= threshold:
                    parent[find(a)] = find(b)
    clusters = defaultdict(list)
    for i in range(len(records)):
        clusters[find(i)].append(i)
    return [c for c in clusters.values()]


def dataset_checks(records, cfg, report):
    """Exact/near duplicates, templating, repetitive openings. Mutates flags."""
    by_prompt = defaultdict(list)
    for r in records:
        by_prompt[" ".join(words(r.prompt))].append(r)
    exact = 0
    for group in by_prompt.values():
        for dup in group[1:]:
            dup.flag("exact_duplicate_prompt", "error", group[0].id)
            exact += 1
    report["exact_duplicate_prompts"] = exact

    clusters = near_duplicate_clusters(records, cfg["near_dup_threshold"])
    multi = 0
    for n, idxs in enumerate(clusters):
        cid = f"C{n:05d}"
        for i in idxs:
            records[i].cluster_id = cid
        if len(idxs) > 1:
            multi += 1
            for i in idxs[1:]:
                if not any(f["code"] == "exact_duplicate_prompt" for f in records[i].flags):
                    records[i].flag("near_duplicate_prompt", "warn", records[idxs[0]].id)
    report["near_duplicate_clusters"] = multi

    with_resp = [r for r in records if r.response]
    if with_resp:
        lines = Counter(l.strip() for r in with_resp for l in r.response.split("\n") if l.strip())
        report["distinct_response_lines_per_record"] = round(len(lines) / len(with_resp), 3)
        openings = Counter(" ".join(words(r.response)[:4]) for r in with_resp)
        common = [(o, c) for o, c in openings.most_common(10) if c >= cfg["max_shared_openings"]]
        report["repetitive_openings"] = common
        for r in with_resp:
            o = " ".join(words(r.response)[:4])
            if any(o == c[0] for c in common):
                r.flag("repetitive_opening", "warn", o)
    return report


def templated_source_check(records, cfg, accepted=None):
    """A source whose responses are built from very few distinct lines is a template dump.

    Measured over unique prompts (exact duplicates are removed separately). Sources listed in
    `accepted` (explicit opt-in with a reason in the config) are flagged as warnings instead.
    """
    accepted = accepted or {}
    by_set = defaultdict(list)
    seen = set()
    for r in records:
        key = (r.source_set, " ".join(words(r.prompt)))
        if r.response and key not in seen:
            seen.add(key)
            by_set[r.source_set].append(r)
    verdicts = {}
    for name, rows in by_set.items():
        occurrences = [l.strip() for r in rows for l in r.response.split("\n") if l.strip()]
        lines = set(occurrences)
        ratio = len(lines) / max(1, len(rows))
        reuse = len(occurrences) / max(1, len(lines))   # how often each distinct line is reused
        templated = len(rows) >= 50 and (reuse >= cfg.get("template_line_reuse", 5)
                                         or ratio < cfg["template_line_ratio"])
        verdicts[name] = {"records": len(rows), "distinct_lines": len(lines),
                          "lines_per_record": round(ratio, 3), "line_reuse": round(reuse, 1),
                          "templated": templated,
                          "accepted_by_config": bool(templated and name in accepted)}
        if templated:
            sev = "warn" if name in accepted else "error"
            for r in records:
                if r.source_set == name:
                    r.flag("templated_source", sev, f"{len(lines)} distinct lines / {len(rows)} unique prompts")
    return verdicts


# ---------------------------------------------------------------- explicit repairs
SPLICE_FIX_RE = re.compile(r"(\b(?:with|about|of|for) [a-z][^.?!\n]{2,80}), (Try|Separate|Choose|Write|Start|Use|"
                           r"Keep|Consider|If|Ask|Focus|Pick|Make|Break)\b")


def repair_response(text, repairs):
    """Apply named, deterministic repairs. Returns (text, [applied repair names])."""
    applied = []
    if text is None:
        return text, applied
    if "strip_leaked_instruction_lines" in repairs:
        lines = text.split("\n")
        kept = [l for l in lines if not any(re.search(p, l, re.IGNORECASE) for p in LEAK_PATTERNS)]
        if len(kept) != len(lines):
            applied.append("strip_leaked_instruction_lines")
            text = "\n".join(kept)
    if "fix_template_splice" in repairs:
        new = SPLICE_FIX_RE.sub(lambda m: f"{m.group(1)}, {m.group(2).lower()}", text)
        if new != text:
            applied.append("fix_template_splice")
            text = new
    if applied:
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, applied
