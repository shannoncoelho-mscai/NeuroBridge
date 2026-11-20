"""NeuroBridge safety policy (deterministic, runs before and after every LLM call).

NeuroBridge is a caregiver-support assistant, not a doctor:
- no diagnosis, no medication starts/stops/dose changes, no dosing instructions;
- no autonomous emergency decisions: on emergency signals the agent stops all task
  execution and gives fixed guidance to contact emergency services (112 in India) — it
  never calls anyone or takes action itself;
- consequential external actions always require human approval (enforced in the
  tool registry / bridge, see agent/tools/builtin.py).

Keyword matching is a safety net, not a classifier: it errs on the side of caution and
will produce false positives. Helpline numbers verified 2026-11-20 against mohfw.gov.in
(Tele-MANAS 14416 / 1-800-891-4416) and mha.gov.in (ERSS 112).
"""
import re

EMERGENCY_NUMBER_INDIA = "112"
TELE_MANAS = "14416 (or 1-800-891-4416)"

_EMERGENCY = [
    r"not breathing", r"can'?t breathe", r"cannot breathe", r"stopped breathing",
    r"\bunconscious\b", r"\bunresponsive\b", r"won'?t wake up", r"not waking up",
    r"(?:seizure|fit|convulsion)s?.{0,25}(?:won'?t|will not|doesn'?t|does not|not|isn'?t|is not) stop",
    r"(?:seizure|fit|convulsion)s?.{0,40}(?:5|five|ten|10) minutes",
    r"fitting for", r"turning blue", r"lips (?:are )?blue",
    r"severe bleeding", r"bleeding heavily", r"\boverdosed\b", r"swallowed (?:pills|tablets|poison|bleach)",
    r"\b(?:has|having|severe) chest pain", r"anaphyla",
    r"बेहोश", r"सांस नहीं", r"दौरा नहीं रुक",
]
_SELF_HARM = [
    r"kill (?:myself|himself|herself|themselves)", r"suicid", r"end (?:my|his|her) life",
    r"want to die", r"self[- ]?harm", r"hurt(?:ing)? (?:myself|himself|herself)",
    r"cutting (?:myself|himself|herself)", r"no reason to live", r"आत्महत्या", r"मरना चाहत",
]
_HARM_TO_OTHERS = [r"hurt (?:my|the) (?:child|son|daughter|baby)", r"hit (?:my|the) child hard",
                   r"shake the baby"]
_MEDICATION_CHANGE = [
    r"(?:stop|quit|discontinue|skip|halve|double|increase|decrease|reduce|lower|raise|change|adjust|switch)\w*\s+(?:[\w'’]+\s+){0,4}(?:medicat|medicine|dose|dosage|tablet|pill|meds|ritalin|risperidone|melatonin|methylphenidate|aripiprazole|valproate|levetiracetam)",
    r"how (?:much|many) (?:[\w'’]+\s+){0,3}(?:should|can|do) (?:i|we) give",
    r"what dose", r"right dose", r"dosage for",
]
_DIAGNOSIS = [
    r"does (?:my|he|she|the) (?:[\w'’]+\s+){0,3}(?:have|has) (?:autism|adhd|asd|epilepsy|dyslexia|bipolar|depression|anxiety)",
    r"is (?:my|he|she) (?:\w+\s+){0,2}(?:autistic|adhd|bipolar|epileptic)",
    r"diagnos(?:e|is) (?:my|him|her)", r"what (?:condition|disorder) does",
]


def _match(patterns, text):
    return [p for p in patterns if re.search(p, text, re.IGNORECASE)]


def emergency_guidance(kind="medical", text=""):
    """Calm, firm guidance. Medical emergencies get verified first-aid steps (first_aid.py)."""
    from agent.safety import first_aid
    if kind == "self_harm":
        return first_aid.SELF_HARM_RESPONSE
    if kind == "harm_to_others":
        return first_aid.HARM_TO_OTHERS_RESPONSE
    if kind == "command_hallucination":
        return first_aid.COMMAND_HALLUCINATION_RESPONSE
    key = first_aid.detect_emergency(text)
    if key:
        return first_aid.render(key)
    return (first_aid.CALM_OPEN + "\n\n"
            f"**This may be a medical emergency. Please call {EMERGENCY_NUMBER_INDIA} now**, or go to the nearest "
            "emergency department.\n\nWhile you wait: stay with the person, keep them safe from injury, and follow the "
            "emergency operator's instructions. If they become unresponsive and are not breathing normally, start CPR "
            "(push hard and fast in the centre of the chest).\n\nI'm an assistant, not a doctor or an emergency "
            "service. I have paused everything else and won't take any action on your behalf — but I'm here with you.")


# Psychosis / DID: not emergencies by themselves. The model must not affirm or argue with
# delusions, must not treat alters as fictional or "fix" them, and should gently connect the
# person with their care team. Command hallucinations to harm are treated as emergencies.
_PSYCHOSIS = [r"\bvoices?\b.*\b(tell|telling|told|command)", r"\b(?:hear|hearing|heard) voices\b", r"\bschizophren",
              r"\bpsychosis\b|\bpsychotic\b", r"\b(watching|following|spying on|reading) (me|my thoughts)\b",
              r"\bcameras? in (my|the) walls?\b", r"\bsecret messages?\b.*\b(tv|radio|news)\b",
              r"\b(implant|chip) in my\b", r"\bparanoi"]
_DID = [r"\bdissociative identity\b", r"\bDID\b", r"\b(alters?|headmates?|system members?)\b",
        r"\bswitch(ed|ing)? (to|into) (another|a different) (part|alter|identity)\b", r"\blost time\b",
        r"\bdissociat"]
_COMMAND_HARM = [r"\bvoices?\b.{0,40}\b(tell|telling|told|want)\w*\b.{0,30}\b(kill|hurt|harm|attack|jump)\b"]

PSYCHOSIS_NOTE = (
    "The person may be describing psychosis or unusual beliefs. Be calm, warm and non-judgemental. Do NOT confirm "
    "or argue with the belief; acknowledge how frightening or exhausting it feels. Do not give instructions that act "
    "on the belief (e.g. how to block signals). Gently encourage contacting their doctor, psychiatrist or care team "
    "soon, and a trusted person. If they mention any risk to themselves or others, firmly advise calling 112.")
DID_NOTE = (
    "The person may be describing dissociation or DID. Treat all parts/alters respectfully and as real experiences; "
    "do not try to 'diagnose', integrate or get rid of parts. Offer grounding (5-4-3-2-1 senses, naming the date and "
    "place, feet on the floor), internal-communication ideas such as a shared journal, and encourage working with a "
    "trauma-informed therapist. Do not diagnose.")
MEDICAL_STANCE_NOTE = (
    "If anything the person describes could need medical attention, take a clear, calm stand: say plainly that they "
    "should get medical help, and if symptoms are severe or sudden they must call 112 now. Be soft in tone but do not "
    "hedge on this.")


def classify_input(text):
    """Return {category, flags, override_response, policy_note, halt_agent}."""
    text = text or ""
    flags = {
        "emergency": _match(_EMERGENCY, text),
        "self_harm": _match(_SELF_HARM, text),
        "harm_to_others": _match(_HARM_TO_OTHERS, text),
        "medication_change": _match(_MEDICATION_CHANGE, text),
        "diagnosis_request": _match(_DIAGNOSIS, text),
    }
    flags["command_hallucination_harm"] = _match(_COMMAND_HARM, text)
    flags["psychosis"] = _match(_PSYCHOSIS, text)
    flags["dissociation"] = _match(_DID, text)
    if flags["command_hallucination_harm"]:
        return {"category": "psychosis_crisis", "flags": flags, "halt_agent": True,
                "override_response": emergency_guidance("command_hallucination"), "policy_note": None}
    if flags["self_harm"]:
        return {"category": "self_harm", "flags": flags, "halt_agent": True,
                "override_response": emergency_guidance("self_harm"), "policy_note": None}
    if flags["harm_to_others"]:
        return {"category": "harm_to_others", "flags": flags, "halt_agent": True,
                "override_response": emergency_guidance("harm_to_others"), "policy_note": None}
    from agent.safety.first_aid import detect_emergency
    if flags["emergency"] or detect_emergency(text):
        return {"category": "emergency", "flags": flags, "halt_agent": True,
                "override_response": emergency_guidance("medical", text), "policy_note": None}

    notes = []
    if flags["medication_change"]:
        notes.append(
            "The user is asking about starting, stopping or changing a medication or dose. "
            "Do NOT give doses or recommend any change. Explain that medication decisions must "
            "be made with the prescribing doctor or a pharmacist, suggest what to ask them, and "
            "say to seek urgent care if there are severe side effects.")
    if flags["diagnosis_request"]:
        notes.append(
            "The user is asking whether someone has a condition. Do NOT diagnose or say the "
            "person has or does not have it. You may describe in general terms what the "
            "condition is and recommend assessment by a qualified professional.")
    if flags["psychosis"]:
        notes.append(PSYCHOSIS_NOTE)
    if flags["dissociation"]:
        notes.append(DID_NOTE)
    if notes:
        notes.append(MEDICAL_STANCE_NOTE)
    category = "medication_change" if flags["medication_change"] else \
        "diagnosis_request" if flags["diagnosis_request"] else \
        "psychosis_support" if flags["psychosis"] else \
        "dissociation_support" if flags["dissociation"] else "normal"
    return {"category": category, "flags": flags, "halt_agent": False,
            "override_response": None, "policy_note": " ".join(notes) or None}


_OUTPUT_DOSING = [
    r"\b(?:give|take|administer|use)\s+(?:him|her|them|your child|the child)?\s*\d+(?:\.\d+)?\s*(?:mg|ml|mcg|tablets?|pills?|drops?)\b",
    r"\b(?:increase|decrease|reduce|double|halve|stop|discontinue)\s+(?:the|his|her|their|your child'?s)\s+(?:dose|dosage|medication|medicine)\b(?![^.]*\b(?:doctor|prescriber|pharmacist|clinician)\b)",
    r"\byou (?:should|can) stop (?:giving|taking)\b(?![^.]*\b(?:doctor|prescriber|pharmacist|clinician)\b)",
]
_OUTPUT_DIAGNOSIS = [
    r"\b(?:your|the) (?:child|son|daughter|loved one|mother|father|parent) (?:clearly |definitely |probably |likely )?(?:has|is suffering from) (?:autism|adhd|asd|epilepsy|dyslexia|bipolar|depression|anxiety disorder|dementia|alzheimer)",
    r"\bthis is (?:definitely |clearly |probably )?(?:autism|adhd|epilepsy|bipolar disorder|dementia)\b",
    r"\bi (?:can )?diagnose\b",
]


def check_output(text):
    reasons = []
    if _match(_OUTPUT_DOSING, text or ""):
        reasons.append("contains dosing or medication-change instructions")
    if _match(_OUTPUT_DIAGNOSIS, text or ""):
        reasons.append("contains a diagnosis statement")
    return {"flagged": bool(reasons), "reasons": reasons}


SAFE_FALLBACK = (
    "I can't give a diagnosis or advice on starting, stopping or changing medication. "
    "Please speak with the treating doctor or a pharmacist about this. If symptoms are severe "
    f"or sudden, call {EMERGENCY_NUMBER_INDIA} or go to the nearest emergency department. "
    "I can help you prepare questions for the doctor or find general, reliable information."
)


def enforce_output(text, regenerate=None):
    """Check text; optionally regenerate once; otherwise return a safe fallback."""
    result = check_output(text)
    if not result["flagged"]:
        return text, {"flagged": False, "action": "none"}
    if regenerate is not None:
        try:
            retry = regenerate(
                "Your previous draft broke NeuroBridge safety rules ("
                + "; ".join(result["reasons"]) + "). Rewrite it without any diagnosis, doses "
                "or medication-change instructions; direct those questions to the doctor.")
            if retry and not check_output(retry)["flagged"]:
                return retry, {"flagged": True, "action": "regenerated", "reasons": result["reasons"]}
        except Exception:
            pass
    return SAFE_FALLBACK, {"flagged": True, "action": "replaced_with_safe_fallback",
                           "reasons": result["reasons"]}


def check_tool_permission(tool_spec, granted_permissions):
    missing = set(tool_spec.required_permissions) - set(granted_permissions or [])
    return {"allowed": not missing, "missing": sorted(missing),
            "approval_required": tool_spec.approval_required}
