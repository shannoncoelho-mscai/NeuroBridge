"""Calm, firm emergency guidance with verified first-aid steps.

Steps are FIXED TEXT (never LLM-generated) so they cannot be truncated, hallucinated or
softened. Content checked on 2026-11-20 against:
  choking (adult/child)  NHS 111 Wales "Choking"; NEAS NHS; St John Ambulance; MedlinePlus
  choking (baby <1)      NHS "How to stop a child from choking"; St John Ambulance; NEAS NHS
  CPR (hands-only)       NHS "CPR - First aid"; Resuscitation Council UK 2025 adult BLS
  seizure                CDC "First Aid for Seizures"; Epilepsy Foundation
  stroke                 NHS "Act FAST"; British Red Cross
  poisoning / overdose   NHS "Poisoning"; British Red Cross
  head injury            NHS "Head injury and concussion"
Review this file with a qualified first-aid trainer before real deployment.
The emergency number is India's 112 (Ministry of Home Affairs ERSS).
"""
import re

EMERGENCY = "112"
TELE_MANAS = "14416 (or 1-800-891-4416)"

CALM_OPEN = "I'm here with you. Take one slow breath — you're doing the right thing by acting now."


def _guide(title, stance, steps, avoid=None, after=None, sources=()):
    return {"title": title, "stance": stance, "steps": steps, "avoid": avoid or [],
            "after": after, "sources": list(sources)}


GUIDES = {
    "choking_baby": _guide(
        "A baby (under 1) who is choking",
        f"If the baby cannot cry, cough or breathe, this is an emergency. Shout for help and have someone call {EMERGENCY} now — put the phone on speaker.",
        ["Sit down and lay the baby face down along your thigh or forearm, head lower than the bottom, supporting the head and jaw.",
         "Give up to 5 firm back blows between the shoulder blades with the heel of your hand. Check the mouth after each one.",
         "If it hasn't cleared, turn the baby face up on your thigh and give up to 5 chest thrusts: two fingers in the middle of the chest, just below the nipple line, pushing down sharply.",
         f"Keep repeating 5 back blows and 5 chest thrusts until the object comes out or help arrives. If you haven't called {EMERGENCY} yet, call now.",
         "If the baby becomes unresponsive and isn't breathing normally, start baby CPR and follow the call handler's instructions."],
        avoid=["Do not give abdominal thrusts to a baby under 1.",
               "Do not put your fingers blindly into the mouth to search for the object."],
        sources=["NHS: How to stop a child from choking", "St John Ambulance: Choking baby"]),
    "choking": _guide(
        "Someone who is choking (adult or child over 1)",
        f"If they cannot speak, cough or breathe, act now and get someone to call {EMERGENCY}.",
        ["If they can cough, encourage them to keep coughing hard and spit the object out.",
         "If they can't cough or breathe: stand behind them, slightly to one side, support their chest and lean them forward.",
         "Give up to 5 sharp back blows between the shoulder blades with the heel of your hand. Check after each one.",
         "If it hasn't cleared, give up to 5 abdominal thrusts: stand behind them, put a clenched fist just above the belly button, hold it with your other hand and pull sharply inwards and upwards.",
         f"If it still hasn't cleared, call {EMERGENCY} now and tell them the person is choking. Keep alternating 5 back blows and 5 abdominal thrusts until help arrives.",
         "If they become unresponsive and stop breathing normally, lower them to the floor and start CPR (push hard and fast in the centre of the chest)."],
        avoid=["Do not give abdominal thrusts to babies under 1 or to someone who is heavily pregnant (use chest thrusts instead).",
               "Do not put your fingers in their mouth to search — you may push the object further."],
        after="Anyone who has had abdominal thrusts should be checked by a doctor afterwards.",
        sources=["NHS 111 Wales: Choking", "NEAS NHS: Choking", "St John Ambulance"]),
    "cpr": _guide(
        "Someone who is unresponsive and not breathing normally",
        f"Call {EMERGENCY} right now and put the phone on speaker. Send someone to find a defibrillator (AED) if there is one nearby.",
        ["Check: tap their shoulders and shout. Look for normal breathing for up to 10 seconds. Gasping is not normal breathing.",
         "Kneel beside them. Put the heel of one hand in the centre of the chest, the other hand on top, fingers interlocked, arms straight, shoulders over your hands.",
         "Push down hard and fast — about 5–6 cm deep, 100–120 times a minute (about 2 per second) — and let the chest come all the way back up each time.",
         "Keep going without stopping until help arrives, the person starts breathing normally, or you are too exhausted. Swap with someone every 2 minutes if you can.",
         "If an AED arrives, switch it on and follow its spoken instructions; keep pausing as little as possible."],
        avoid=["If you are not trained in rescue breaths, do hands-only CPR — it is far better than doing nothing."],
        sources=["NHS: CPR - First aid", "Resuscitation Council UK 2025 Adult Basic Life Support"]),
    "seizure": _guide(
        "Someone having a seizure",
        f"Stay calm and stay with them. Call {EMERGENCY} if the seizure lasts more than 5 minutes, another seizure follows, it's their first seizure, they are injured, pregnant, in water, or they don't wake up or breathe normally afterwards.",
        ["Note the time the seizure started.",
         "Gently guide them to the floor if needed and move hard or sharp things away. Cushion their head with something soft.",
         "Loosen anything tight around the neck and remove glasses.",
         "Once the jerking stops, turn them gently onto their side (recovery position) so they can breathe.",
         "Stay with them, talk quietly and reassure them as they come round. They may be confused or sleepy."],
        avoid=["Do not hold them down or try to stop the movements.",
               "Do not put anything in their mouth.",
               "Do not give food, water or medicine until they are fully alert."],
        sources=["CDC: First Aid for Seizures", "Epilepsy Foundation"]),
    "stroke": _guide(
        "Possible stroke",
        f"This needs emergency care immediately. Call {EMERGENCY} now — every minute matters, even if the signs seem to pass.",
        ["Use FAST: Face — has one side drooped? Arms — can they lift both and keep them up? Speech — is it slurred or confused? Time — call now if you see any one of these.",
         "Note the time the symptoms started and tell the call handler.",
         "Keep them comfortable and safe, sitting or lying with head and shoulders slightly raised; reassure them.",
         "If they become unresponsive but are breathing, put them on their side. If they stop breathing normally, start CPR."],
        avoid=["Do not give food, drink or medicines — swallowing may be affected.",
               "Do not wait to see if it gets better, and do not drive them yourself if an ambulance is available."],
        sources=["NHS: Act FAST", "British Red Cross: Stroke"]),
    "bleeding": _guide(
        "Severe bleeding",
        f"Call {EMERGENCY} now if the bleeding is heavy or won't stop.",
        ["Press firmly and directly on the wound with a clean cloth, towel or your hand, and keep pressing.",
         "If blood soaks through, add more cloth on top and keep pressing — don't lift it to check.",
         "If possible, have them lie down and keep them warm.",
         "Keep pressure on until help arrives."],
        avoid=["Do not remove an object stuck in a wound — press around it instead."],
        sources=["British Red Cross: Severe bleeding", "NHS first aid"]),
    "poisoning": _guide(
        "Possible poisoning or overdose",
        f"Get emergency help now: call {EMERGENCY}, especially if they are drowsy, confused, having trouble breathing, or have a seizure.",
        ["Try to find out what was taken, how much and when; keep the packet or container to show the paramedics.",
         "If they are unconscious but breathing, put them on their side (recovery position) and keep checking their breathing.",
         "If they are awake, keep talking to them and stay with them.",
         "If they stop breathing normally, start CPR."],
        avoid=["Do not try to make them sick.", "Do not give anything to eat or drink unless the emergency service tells you to."],
        sources=["NHS: Poisoning", "British Red Cross: Poisoning"]),
    "head_injury": _guide(
        "A head injury",
        f"Call {EMERGENCY} now if they were knocked out and haven't woken, are very sleepy or confused, have a seizure, have trouble speaking, walking or seeing, are bleeding from the ears or nose, or have a dent or wound with something in it.",
        ["Keep them still and calm; if they are awake, sit them down somewhere safe.",
         "Hold a cold pack or cloth gently on any swelling, and press on any bleeding with a clean cloth.",
         "Stay with them and watch for vomiting, worsening headache, confusion or drowsiness — any of these means go to the emergency department or call 112.",
         "If they become unresponsive but are breathing, turn them onto their side; if they stop breathing normally, start CPR."],
        avoid=["Do not let them drive.", "Do not leave them alone for the next 24 hours if they have any symptoms."],
        sources=["NHS: Head injury and concussion"]),
}

# Present-tense / in-the-moment cues only, so planning questions ("choking hazards for
# toddlers", "food poisoning tips", "he had a seizure last month") do not trigger a halt.
DETECT = [
    ("choking_baby", r"\b(baby|infant|newborn)\b.{0,40}\b(is choking|choking on|choking right now|can'?t breathe|isn'?t breathing|not breathing)"
                     r"|\b(is choking|choking on)\b.{0,40}\b(baby|infant|newborn)\b"),
    ("choking", r"\b(is|are|'s|keeps|started|start) choking\b(?! (?:hazard|risk))|\bchoking (right )?now\b|\bchoking on\b"
                r"|something (is )?stuck in (his|her|their|my) throat|\bcan'?t (breathe|cough).{0,30}\b(stuck|food|swallowed)"),
    ("cpr", r"\b(not breathing|stopped breathing|isn'?t breathing|no pulse|unresponsive|unconscious|won'?t wake up|collapsed)\b"),
    ("seizure", r"\b(is|'s|are) (having|in) an? (seizure|fit)\b|\bhaving an? (seizure|fit) (right )?now\b"
                r"|\b(is|are) (seizing|convulsing|fitting)\b|\bseizure (won'?t|isn'?t|is not|hasn'?t) stop"
                r"|\b(seizure|fit).{0,30}\b(5|five|ten|10) minutes\b"),
    ("stroke", r"\bface (is )?droop|\bslurred speech|\bspeech is slurred|\bcan'?t (lift|raise|move) (his|her|their) (right |left )?arm"
               r"|\b(is|'s) having a stroke\b"),
    ("bleeding", r"\b(bleeding heavily|severe bleeding|won'?t stop bleeding|lots of blood|blood everywhere|bleeding badly)\b"),
    ("poisoning", r"\b(overdosed|has overdosed|took an overdose|took too many|swallowed (?:pills|tablets|poison|bleach|chemicals|medicine|batter(y|ies))"
                  r"|drank (?:bleach|poison|chemicals|cleaning))\b"),
    ("head_injury", r"\b(just )?(hit|banged) (his|her|their|my) head\b|\bfell and hit\b"),
]


def detect_emergency(text):
    t = (text or "").lower()
    for key, pattern in DETECT:
        if re.search(pattern, t):
            return key
    return None


def render(key):
    g = GUIDES[key]
    lines = [CALM_OPEN, "", f"**{g['stance']}**", "", f"**What to do — {g['title'].lower()}:**"]
    lines += [f"{i}. {s}" for i, s in enumerate(g["steps"], 1)]
    if g["avoid"]:
        lines += ["", "**Please don't:**"] + [f"- {a}" for a in g["avoid"]]
    if g["after"]:
        lines += ["", g["after"]]
    lines += ["", "Follow the emergency call handler's instructions — they can guide you step by step. "
              "I'm an assistant, not an emergency service, and I have paused everything else. "
              "You can tell me what is happening and I'll stay with you.",
              "", "_Guidance based on: " + "; ".join(g["sources"]) + "._"]
    return "\n".join(lines)


SELF_HARM_RESPONSE = (
    "I'm really glad you told me. What you're feeling matters, and you don't have to carry it alone.\n\n"
    f"**Right now, please reach out for help: if you might act on these thoughts or are in danger, call {EMERGENCY}. "
    f"You can also call Tele-MANAS on {TELE_MANAS} — it's free, confidential and open 24 hours, in many languages.**\n\n"
    "If you can, contact someone you trust — a friend, family member or neighbour — and let them know you need them "
    "with you. If there is anything nearby you could use to hurt yourself, could you move it away or to another room?\n\n"
    "I'm an assistant, not a crisis service, so I can't call anyone for you — but I'm here, and we can keep talking "
    "while you reach out. Are you safe right now?"
)

COMMAND_HALLUCINATION_RESPONSE = (
    "Thank you for telling me — that sounds really frightening, and you did the right thing by saying it out loud.\n\n"
    f"**Please get help right now: if you feel you might act on what the voices are saying, or anyone could be hurt, call {EMERGENCY}.** "
    "If you can, move away from anything you could use to harm someone, and go somewhere with a person you trust.\n\n"
    "You don't have to do what the voices say. Please contact your doctor, psychiatrist or care team today and tell them "
    f"the voices are telling you to harm someone — they will want to help quickly. Tele-MANAS ({TELE_MANAS}) is also free and "
    "open 24 hours.\n\nI'm an assistant, not an emergency service, but I'm here while you reach out. Is someone with you right now?"
)

HARM_TO_OTHERS_RESPONSE = (
    "Thank you for being honest — it takes courage to say this, and it shows you care about keeping everyone safe.\n\n"
    f"**If anyone is in immediate danger, please call {EMERGENCY} now.** If you feel close to losing control, "
    "step away to another room and give yourself space to breathe, if it is safe to leave the other person for a moment.\n\n"
    f"Caregiving under this much strain is very hard. Tele-MANAS ({TELE_MANAS}) can talk with you right now, and a doctor "
    "or local support service can help arrange respite so you get a break. Would it help to think together about who "
    "could take over for a few hours today?"
)
