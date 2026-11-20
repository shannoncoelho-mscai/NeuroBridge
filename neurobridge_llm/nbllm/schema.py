"""Canonical record schema and source loading.

Every source file is mapped to one canonical record shape so that later steps
(validation, dedupe, split, formatting) never care which notebook produced it.
"""
import gzip
import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

ROLES = {"train_candidate", "eval_prompts", "review_only", "quarantine"}


@dataclass
class Record:
    id: str
    source_set: str
    source_file: str
    role: str
    prompt: str
    response: Optional[str] = None
    domain: Optional[str] = None
    variation: Optional[str] = None
    synthetic: bool = True
    human_reviewed: bool = False
    author: str = "unknown"          # assistant | model:<name> | human | template | unknown
    revised: bool = False
    repairs: list = field(default_factory=list)
    original_response: Optional[str] = None
    flags: list = field(default_factory=list)   # [{"code","severity","detail"}]
    classified_domain: Optional[str] = None
    cluster_id: Optional[str] = None
    split: Optional[str] = None

    def to_dict(self):
        return asdict(self)

    def flag(self, code, severity, detail=""):
        self.flags.append({"code": code, "severity": severity, "detail": detail})

    @property
    def excluded(self):
        return any(f["severity"] == "error" for f in self.flags)


def read_jsonl(path):
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield n, json.loads(line), None
            except json.JSONDecodeError as exc:
                yield n, None, f"invalid JSON: {exc}"


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _first(d, keys):
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return None


def load_source(spec, base_dir):
    """spec: {path|glob, set, role, author, id_prefix?} -> (records, load_errors)."""
    base_dir = Path(base_dir)
    if spec["role"] not in ROLES:
        raise ValueError(f"Unknown role {spec['role']}")
    paths = sorted(base_dir.glob(spec["glob"])) if "glob" in spec else [base_dir / spec["path"]]
    records, errors = [], []
    for path in paths:
        rel = str(path.relative_to(base_dir))
        for n, row, err in read_jsonl(path):
            if err:
                errors.append({"file": rel, "line": n, "error": err})
                continue
            prompt = _first(row, ["prompt", "instruction", "user", "question"])
            response = _first(row, ["response", "chosen", "assistant", "answer"])
            rid = (f"{spec.get('id_prefix', spec['set'])}_{n:05d}" if spec.get("ids") == "line"
                   else row.get("scenario_id") or row.get("id") or f"{spec.get('id_prefix', spec['set'])}_{path.stem}_{n}")
            if prompt is None:
                errors.append({"file": rel, "line": n, "error": "missing prompt/instruction"})
                continue
            records.append(Record(
                id=str(rid), source_set=spec["set"], source_file=rel, role=spec["role"],
                prompt=prompt, response=response,
                domain=row.get(spec.get("domain_field", "domain")) or row.get("domain") or row.get("category")
                or (spec.get("domain_from_file") and path.stem) or None,
                variation=row.get("variation"),
                synthetic=bool(row.get("synthetic", True)),
                # Only trust human_reviewed if it is explicitly true in the source.
                human_reviewed=row.get("human_reviewed") is True,
                author=spec.get("author", "unknown"),
                revised=bool(row.get("revised", False) or row.get("original_response")),
                original_response=row.get("original_response"),
            ))
    return records, errors
