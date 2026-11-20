"""Skill definition.

RECONSTRUCTED: the original agent/skills/base.py exists on Google Drive but its source never
appeared in the build notebook. This version implements the API the notebook uses:
Skill(name, description, instructions, triggers, required_tools, safety_rules).
"""
from dataclasses import dataclass, field


@dataclass
class Skill:
    name: str
    description: str
    instructions: str = ""
    triggers: list = field(default_factory=list)
    required_tools: list = field(default_factory=list)
    safety_rules: list = field(default_factory=list)
    default: bool = False  # always selected as a baseline skill
    metadata: dict = field(default_factory=dict)

    def matches(self, text):
        text = (text or "").lower()
        return sum(1 for trigger in self.triggers if trigger.lower() in text)

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "instructions": self.instructions,
            "triggers": list(self.triggers),
            "required_tools": list(self.required_tools),
            "safety_rules": list(self.safety_rules),
        }
