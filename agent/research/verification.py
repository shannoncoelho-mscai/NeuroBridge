"""Answer verification: deterministic grounding checks + LLM verifier.

The deterministic layer is the authority for hard facts. An answer FAILS if it contains a
URL, phone number, e-mail, price, or named organisation/provider that does not appear in the
retrieved evidence, cites a source id that does not exist, or (when evidence exists) cites
nothing. The LLM verifier (ported from notebook cell 108) adds judgement on goal completion,
uncertainty and actionability, but it can only make a verdict stricter, never looser.
"""
import json
import re

from agent.research.jsonutil import extract_json
from agent.safety.policy import check_output

URL_RE = re.compile(r"https?://[^\s\)\]>\"'<]+")
PHONE_RE = re.compile(r"(?<![\w/])(?:\+?\d[\d\s\-]{8,}\d)(?![\w/])")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PRICE_RE = re.compile(r"(?:₹|Rs\.?|INR|\$|USD)\s?\d[\d,]*(?:\.\d+)?", re.IGNORECASE)
CITATION_RE = re.compile(r"\[S(\d+)\]")
# Title-case phrases of 2-6 words, e.g. "Mind Care Clinic", "Goa Medical College"
ENTITY_RE = re.compile(r"\b(?:[A-Z][a-zA-Z&'\.-]+|of|and|for|the)(?:\s+(?:[A-Z][a-zA-Z&'\.-]+|of|and|for|the)){1,5}\b")

ENTITY_STOP_START = {"the", "of", "and", "for", "this", "these", "that", "if", "when", "you",
                     "your", "we", "it", "for", "a", "an", "in", "on", "please", "note",
                     "sources", "source", "summary", "next", "steps", "important", "what",
                     "how", "why", "key", "step", "option", "options", "here", "unverified",
                     "confirmed", "missing", "information"}
# Names the assistant may always mention (safety resources, product name).
ALWAYS_ALLOWED = {"neurobridge", "tele manas", "tele-manas", "emergency response support system"}
ALLOWED_DIGITS = {"112", "14416", "18008914416"}
# Phrases containing these words name organisations/providers and need an exact match.
ORG_WORDS = {"clinic", "clinics", "centre", "center", "hospital", "hospitals", "foundation",
             "institute", "association", "society", "trust", "college", "university", "dr",
             "ltd", "pvt", "llp", "inc", "group", "council", "academy", "school", "ngo",
             "polyclinic", "nursing", "home", "mission", "organisation", "organization"}
CAMEL_RE = re.compile(r"\b[a-zA-Z]*[a-z][A-Z][a-zA-Z]*\b")


def _strip_headings(text):
    lines = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        stripped = re.sub(r"^\s*(?:[-*]\s*)?\*\*[^*]{0,60}\*\*:?", "", stripped)
        lines.append(stripped)
    return "\n".join(lines)


def _norm_url(u):
    return u.rstrip(".,;:!?)").rstrip("/").lower()


def _norm_digits(s):
    return re.sub(r"\D", "", s)


def candidate_entities(text):
    found = []
    for m in ENTITY_RE.finditer(text or ""):
        phrase = m.group(0).strip()
        words = phrase.split()
        while words and words[0].lower() in ENTITY_STOP_START:
            words = words[1:]
        while words and words[-1].lower() in {"of", "and", "for", "the"}:
            words = words[:-1]
        if len(words) < 2:
            continue
        if sum(1 for w in words if w[:1].isupper()) < 2:
            continue
        found.append(" ".join(words))
    return list(dict.fromkeys(found))


def deterministic_check(answer, ranked, goal_text=""):
    evidence = ranked.get("evidence", [])
    corpus = "\n".join(
        " ".join([e.get("title", ""), e.get("content", ""), e.get("page_content", ""),
                  e.get("url", "")]) for e in evidence
    )
    corpus_lower = corpus.lower()
    corpus_digits = _norm_digits(corpus)
    evidence_urls = {_norm_url(e.get("url", "")) for e in evidence if e.get("url")}
    goal_lower = (goal_text or "").lower()
    answer = answer or ""

    critical, unsupported, issues, warnings = [], [], [], []

    for url in URL_RE.findall(answer):
        if _norm_url(url) not in evidence_urls and _norm_url(url) not in corpus_lower:
            critical.append({"type": "unsupported_url", "value": url})
    for phone in PHONE_RE.findall(answer):
        digits = _norm_digits(phone)
        if len(digits) >= 9 and digits not in corpus_digits and digits not in ALLOWED_DIGITS:
            critical.append({"type": "unsupported_phone", "value": phone.strip()})
    for email in EMAIL_RE.findall(answer):
        if email.lower() not in corpus_lower:
            critical.append({"type": "unsupported_email", "value": email})
    for price in PRICE_RE.findall(answer):
        if _norm_digits(price) and _norm_digits(price) not in corpus_digits:
            critical.append({"type": "unsupported_price", "value": price})

    corpus_words = set(re.findall(r"[a-z0-9']+", corpus_lower))
    for entity in candidate_entities(_strip_headings(answer)):
        el = entity.lower()
        if el in corpus_lower or el in goal_lower or el in ALWAYS_ALLOWED:
            continue
        words = [w.strip(".") for w in re.findall(r"[a-z0-9'.]+", el)]
        if any(w in ORG_WORDS for w in words):
            unsupported.append({"type": "unsupported_entity", "value": entity})
        elif not all(w in corpus_words for w in words):
            warnings.append({"type": "unverified_phrase", "value": entity})
    for token in CAMEL_RE.findall(_strip_headings(answer)):
        if token.lower() not in corpus_lower and token.lower() not in goal_lower \
                and token.lower() != "neurobridge":
            unsupported.append({"type": "unsupported_entity", "value": token})

    cited = {int(n) for n in CITATION_RE.findall(answer)}
    invalid = sorted(n for n in cited if n < 1 or n > len(evidence))
    if invalid:
        critical.append({"type": "invalid_citation", "value": [f"S{n}" for n in invalid]})
    if evidence and not cited:
        issues.append("Answer does not cite any retrieved source.")
    if not evidence:
        issues.append("No evidence was retrieved.")

    safety = check_output(answer)
    if safety["flagged"]:
        issues.extend(f"Safety: {r}" for r in safety["reasons"])

    score = 100 - 35 * len(critical) - 15 * len(unsupported) - (20 if (evidence and not cited) else 0)
    score -= 40 if safety["flagged"] else 0
    score -= 50 if not evidence else 0
    score = max(0, min(100, score))
    passed = (not critical and not unsupported and bool(evidence) and bool(cited)
              and not safety["flagged"])
    return {
        "passed": passed,
        "score": score,
        "critical_issues": critical,
        "unsupported_claims": unsupported,
        "warnings": warnings,
        "issues": issues,
        "citations_used": sorted(f"S{n}" for n in cited if 1 <= n <= len(evidence)),
        "safety": safety,
        "method": "deterministic",
    }


LLM_VERIFY_PROMPT = """Evaluate this NeuroBridge response.

USER GOAL:
{goal}

AGENT RESPONSE:
{answer}

AVAILABLE EVIDENCE (cite ids like [S1]):
{evidence}

Evaluate evidence grounding, unsupported factual claims, uncertainty handling, goal
completion, safety (no diagnosis, no medication changes, no unsafe advice), actionability.

Return ONLY a JSON object:
{{"passed": false, "score": 0, "issues": [], "unsupported_claims": [], "safety_issues": [],
  "missing_information": [], "recommendations": [], "reason": ""}}

passed must be true only if score >= 80, no serious safety issues exist and critical
unsupported claims are absent. Do not invent evidence."""


def llm_verify(gateway, goal_text, answer, evidence_items):
    prompt = LLM_VERIFY_PROMPT.format(
        goal=goal_text, answer=answer,
        evidence=json.dumps(evidence_items, ensure_ascii=False, indent=1)[:12000])
    raw = None
    for attempt, (sys_prompt, tokens) in enumerate([
        ("You are a strict evidence-grounding and safety verifier. Return valid JSON only.", 1600),
        ("Return one compact, valid JSON object only. No markdown.", 900),
    ]):
        try:
            response = gateway.generate(
                messages=[{"role": "user", "content": prompt if attempt == 0 else
                           prompt + "\n\nIMPORTANT: Return a shorter valid JSON response."}],
                system_prompt=sys_prompt, temperature=0.0 if attempt else 0.1,
                max_tokens=tokens)
            raw = response.text
        except Exception as exc:
            return {"available": False, "error": f"{type(exc).__name__}: {exc}"}
        parsed = extract_json(raw)
        if isinstance(parsed, dict) and "passed" in parsed:
            parsed["available"] = True
            parsed["retry_used"] = attempt > 0
            return parsed
    return {"available": False, "error": "Verifier returned invalid JSON after retry",
            "raw_response": (raw or "")[:500]}


def verify_answer(gateway, goal_text, answer, ranked, evidence_items, use_llm=True):
    det = deterministic_check(answer, ranked, goal_text)
    llm = llm_verify(gateway, goal_text, answer, evidence_items) if (use_llm and gateway) \
        else {"available": False, "error": "LLM verifier disabled"}
    passed = det["passed"]
    score = det["score"]
    if llm.get("available"):
        passed = passed and bool(llm.get("passed")) and not llm.get("safety_issues")
        try:
            score = min(score, int(llm.get("score", 0)))
        except (TypeError, ValueError):
            pass
    return {"passed": passed, "score": score, "deterministic": det, "llm": llm}
