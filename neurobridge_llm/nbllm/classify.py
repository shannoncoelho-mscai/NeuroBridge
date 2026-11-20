"""Transparent keyword-based scenario classifier.

Purpose: (1) assign a domain to unlabeled prompts, (2) flag label/content mismatches for
human review, (3) report domain coverage. It is a heuristic, not a model; mismatches are
warnings, never automatic relabels.
"""
import re

TAXONOMY = {
    "sensory_support": ["noise", "loud", "bright", "light", "sensory", "crowd", "texture", "smell", "overstimulat"],
    "task_initiation": ["start", "procrastinat", "can't begin", "cannot start", "stuck", "task", "to-do", "motivation"],
    "boundary_setting": ["boundar", "say no", "saying no", "limits", "push back", "overstep"],
    "anxiety_support": ["anxious", "anxiety", "panic", "worried", "worry", "nervous", "dread"],
    "emotional_support": ["sad", "lonely", "alone", "cry", "hopeless", "upset", "hurt", "feel awful", "guilt"],
    "mood_reflection": ["mood", "journal", "reflect", "pattern", "energy level", "notice how i feel"],
    "sleep_support": ["sleep", "insomnia", "bedtime", "wake up", "tired at night", "nap"],
    "routine_support": ["routine", "morning", "evening", "schedule", "daily plan", "transition"],
    "caregiver_support": ["caregiver", "caring for", "care for", "my mother", "my father", "my husband",
                          "my wife", "my son", "my daughter", "person i support", "person i care"],
    "appointment_preparation": ["appointment", "doctor", "clinic", "visit", "consultation", "questions to ask"],
    "accommodation_support": ["accommodation", "workplace", "manager", "school", "adjustment", "reasonable"],
    "support_navigation": ["service", "support group", "resource", "benefit", "helpline", "where can i find", "respite"],
    "safety_changes_in_condition": ["suddenly", "fell", "fall", "confused", "not breathing", "chest pain",
                                    "seizure", "unconscious", "emergency", "bleeding"],
    "financial_resource_constraints": ["money", "afford", "cost", "expensive", "insurance", "budget"],
    "family_coordination": ["sibling", "brother", "sister", "family", "relatives", "share the care"],
}


def classify(text):
    t = (text or "").lower()
    scores = {}
    for domain, kws in TAXONOMY.items():
        s = sum(1 for kw in kws if kw in t)
        if s:
            scores[domain] = s
    if not scores:
        return None, 0.0, {}
    best = max(scores, key=lambda d: (scores[d], d))
    total = sum(scores.values())
    return best, round(scores[best] / total, 2), scores


def check_label(rec):
    label, best, conf, scores = rec.domain, *classify(rec.prompt)
    rec.classified_domain = best
    if label and best and label in TAXONOMY and label not in scores and conf >= 0.6:
        rec.flag("domain_mismatch", "warn", f"label={label} classifier={best} ({conf})")
    return rec
