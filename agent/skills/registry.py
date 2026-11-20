"""Skill registry (RECONSTRUCTED — see base.py)."""
from agent.skills.base import Skill


class SkillRegistry:
    def __init__(self):
        self._skills = {}

    def register(self, skill):
        if not isinstance(skill, Skill):
            raise TypeError("skill must be a Skill instance")
        if skill.name in self._skills:
            raise ValueError(f"Skill already registered: {skill.name}")
        self._skills[skill.name] = skill
        return skill

    def get(self, name):
        if name not in self._skills:
            raise KeyError(f"Unknown skill: {name}")
        return self._skills[name]

    def names(self):
        return list(self._skills.keys())

    def list_skills(self):
        return [skill.to_dict() for skill in self._skills.values()]

    def select(self, text, include_defaults=True):
        """Skills whose triggers appear in `text`, best match first, plus default skills."""
        scored = [(skill.matches(text), skill) for skill in self._skills.values()]
        selected = [s for score, s in sorted(scored, key=lambda x: -x[0]) if score > 0]
        if include_defaults:
            selected += [s for s in self._skills.values() if s.default and s not in selected]
        return selected
