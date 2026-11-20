"""Automatic checks for community content. They HOLD content for a human moderator;
they never silently delete. Wording here is deliberately short; extend the lists with your
moderation team. Self-harm or emergency language is held and the author is shown support
resources straight away (a peer forum is not a crisis service)."""
import re

from agent.safety.policy import classify_input

ABUSE = [r"\bkys\b", r"\bkill (?:yo)?urself\b", r"\bgo die\b", r"\bretard(?:ed)?\b",
         r"\byou(?:'re| are) (?:worthless|pathetic|disgusting)\b", r"\bnobody (?:likes|wants) you\b"]
ABUSE_RE = re.compile("|".join(ABUSE), re.IGNORECASE)
PHONE_RE = re.compile(r"(?:\+?\d[\s-]?){10,13}")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
ADDRESS_RE = re.compile(r"\b(?:my address is|i live at|house no\.?|flat no\.?)\b", re.IGNORECASE)
SPAM_RE = re.compile(r"(?:https?://\S+.*){4,}|\b(?:buy now|earn money fast|crypto giveaway)\b",
                     re.IGNORECASE)

CRISIS_MESSAGE = ("Your post is being held so a person can check on it. If you are thinking "
                  "about harming yourself or are in danger, please call 112 now, or Tele-MANAS "
                  "on 14416 (free, 24/7). You deserve support right now.")


def check(text, author_is_minor=False):
    """Returns (status, reason, message_for_author)."""
    safety = classify_input(text)
    if safety["category"] in ("self_harm", "emergency", "psychosis_crisis", "harm_to_others"):
        return "held", "safety", CRISIS_MESSAGE
    if ABUSE_RE.search(text):
        return "held", "abuse", ("This contains words that can hurt people, so a moderator will "
                                 "review it first.")
    if PHONE_RE.search(text) or EMAIL_RE.search(text) or ADDRESS_RE.search(text):
        return "held", "personal_info", ("For your safety, posts with phone numbers, emails or "
                                         "addresses are checked by a moderator first. You can use "
                                         "Connections to talk privately with adults you know.")
    if SPAM_RE.search(text):
        return "held", "spam", "This looks like spam, so a moderator will review it."
    return "visible", None, None
