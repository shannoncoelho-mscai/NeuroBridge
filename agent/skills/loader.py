"""Built-in NeuroBridge skills (RECONSTRUCTED — the research and caregiver_support
definitions are copied from notebook cell 84; the others are new)."""
from agent.skills.base import Skill
from agent.skills.registry import SkillRegistry


def builtin_skills():
    return [
        Skill(
            name="research",
            description="Research information using web search and source analysis",
            instructions=("Search for information, collect sources, compare findings, "
                          "evaluate credibility, and report evidence with uncertainty."),
            triggers=["research", "search", "find information", "investigate", "sources",
                      "find", "look up", "compare", "evidence"],
            required_tools=["web_search", "web_page_reader"],
            safety_rules=["Do not invent sources", "Report uncertainty"],
        ),
        Skill(
            name="caregiver_support",
            description="Provide empathetic and practical support to caregivers",
            instructions=("Understand the caregiver's situation and provide compassionate, "
                          "practical support and manageable next steps."),
            triggers=["caregiver", "support", "care", "stress", "help"],
            safety_rules=["Do not diagnose", "Do not replace professional advice"],
            default=True,
        ),
        Skill(
            name="appointment_booking",
            description="Find verified providers and request appointments with caregiver approval",
            instructions=("Search only verified, booking-enabled providers in the NeuroBridge "
                          "registry. Never book without explicit caregiver approval."),
            triggers=["book", "appointment", "schedule a visit", "slot", "consultation"],
            required_tools=["provider_search", "find_slots", "request_appointment"],
            safety_rules=["Require explicit caregiver approval", "Never invent availability"],
        ),
        Skill(
            name="community_events",
            description="Find and book NeuroBridge community events: support groups, workshops, clubs, gatherings",
            instructions=("Search events that fit the person's needs (audience, accessibility, online or in "
                          "person). Present options; register only after explicit approval of the exact details."),
            triggers=["event", "workshop", "support group", "group", "club", "meetup", "meet-up", "gathering",
                      "community meeting", "class", "social", "activity", "activities", "circle", "session"],
            required_tools=["event_search", "register_for_event"],
            safety_rules=["Require explicit approval bound to exact details", "Mark demo listings clearly"],
        ),
        Skill(
            name="routine_planning",
            description="Help caregivers organise daily or weekly care routines",
            instructions="Break routines into manageable steps and include caregiver rest.",
            triggers=["routine", "schedule", "organize", "organise", "plan my", "week"],
            safety_rules=["Do not change medication timing without a clinician"],
        ),
    ]


def load_default_skills(registry=None):
    registry = registry or SkillRegistry()
    for skill in builtin_skills():
        if skill.name not in registry.names():
            registry.register(skill)
    return registry
