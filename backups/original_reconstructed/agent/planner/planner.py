import json
import re
from typing import Any

from agent.schemas import AgentGoal, AgentTask, AgentPlan


class AgentPlanner:

    MAX_TASKS = 12

    def __init__(self, gateway, skills=None, tools=None):
        self.gateway = gateway
        self.skills = skills or []
        self.tools = tools or []

    def _build_prompt(self, goal: AgentGoal) -> str:
        return f"""
You are the planning component of NeuroBridge, an AI agent
that supports caregivers.

Create a safe, practical, step-by-step plan for the goal below.

GOAL:
{goal.description}

PRIORITY:
{goal.priority}

DEADLINE:
{goal.deadline or "None specified"}

SUCCESS CRITERIA:
{json.dumps(goal.success_criteria, ensure_ascii=False)}

AVAILABLE SKILLS:
{json.dumps(self.skills, ensure_ascii=False, indent=2)}

AVAILABLE TOOLS:
{json.dumps(self.tools, ensure_ascii=False, indent=2)}

RULES:
- Break the goal into small, actionable tasks.
- Use only skills listed under AVAILABLE SKILLS.
- Use only tools listed under AVAILABLE TOOLS.
- Select a required_tool when a task needs an available tool.
- Select a required_skill when a task matches an available skill.
- For tool tasks, provide tool_arguments matching that tool.
- Do not invent tool names or tool arguments.
- Use no more than {self.MAX_TASKS} tasks.
- Tasks must be ordered logically.
- Dependencies must refer to task indices starting at 0.
- Use an empty dependencies list when a task has no dependencies.
- Do not invent completed work.
- Do not claim that any task has already been executed.
- Do not autonomously make medical decisions.
- Do not recommend medication changes or diagnoses.
- Tasks involving external, sensitive, irreversible, or consequential
  actions should have requires_approval set to true.
- Prefer tasks that gather information or prepare drafts before
  any consequential action.
- required_tool and required_skill may be null if unknown.
- Keep task descriptions clear and understandable.

Return ONLY valid JSON in this format:

{{
  "reasoning_summary": "Short explanation of the plan",
  "tasks": [
    {{
      "name": "Task name",
      "description": "What needs to be done",
      "priority": "normal",
      "dependencies": [],
      "required_tool": null,
      "required_skill": null,
      "tool_arguments": {{}},
      "requires_approval": false
    }}
  ]
}}
"""

    def _extract_json(self, text: str) -> dict:
        text = text.strip()

        # Remove markdown code fences if present
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

        # Try parsing the complete response first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Attempt to extract a JSON object
        start = text.find("{")
        end = text.rfind("}")

        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])

        raise ValueError("Planner response did not contain valid JSON.")

    def create_plan(self, goal: AgentGoal) -> AgentPlan:
        response = self.gateway.generate(
            messages=[
                {
                    "role": "user",
                    "content": self._build_prompt(goal),
                }
            ],
            system_prompt=(
                "You are NeuroBridge's careful task planner. "
                "Return valid JSON only. Plan tasks, but never "
                "execute them."
                ),
            temperature=0.2,
            max_tokens=1800,
        )

        data = self._extract_json(response.text)

        raw_tasks = data.get("tasks", [])

        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise ValueError("Planner returned no tasks.")

        if len(raw_tasks) > self.MAX_TASKS:
            raise ValueError(
                f"Planner returned too many tasks: {len(raw_tasks)}."
            )

        # Create task IDs first so dependencies can be resolved.
        tasks = []
        task_ids = []

        for item in raw_tasks:
            if not isinstance(item, dict):
                raise ValueError("Each task must be a JSON object.")

            name = str(item.get("name", "")).strip()
            description = str(item.get("description", "")).strip()

            if not name or not description:
                raise ValueError(
                    "Every task must have a name and description."
                )

            task = AgentTask(
                name=name,
                description=description,
                priority=str(item.get("priority", "normal")),
                required_tool=item.get("required_tool"),
                required_skill=item.get("required_skill"),
                requires_approval=bool(
                    item.get("requires_approval", False)
                ),
                metadata={
                    "planner_generated": True,
                    "dependencies_raw": item.get("dependencies", []),
                    "tool_arguments": item.get("tool_arguments", {}),
                },
            )

            tasks.append(task)
            task_ids.append(task.task_id)

        # Resolve dependency indices into actual task IDs.
        for index, item in enumerate(raw_tasks):
            raw_dependencies = item.get("dependencies", [])

            if not isinstance(raw_dependencies, list):
                raise ValueError(
                    f"Dependencies for task {index} must be a list."
                )

            resolved = []

            for dependency in raw_dependencies:
                if isinstance(dependency, int):
                    if dependency < 0 or dependency >= len(tasks):
                        raise ValueError(
                            f"Invalid dependency index: {dependency}"
                        )

                    if dependency == index:
                        raise ValueError(
                            "A task cannot depend on itself."
                        )

                    resolved.append(task_ids[dependency])

                elif isinstance(dependency, str):
                    # Accept an existing task ID if provided.
                    if dependency in task_ids:
                        if dependency == task_ids[index]:
                            raise ValueError(
                                "A task cannot depend on itself."
                            )
                        resolved.append(dependency)
                    else:
                        raise ValueError(
                            f"Unknown dependency reference: {dependency}"
                        )

                else:
                    raise ValueError(
                        "Dependencies must be task indices or task IDs."
                    )

            tasks[index].dependencies = list(set(resolved))

        plan = AgentPlan(
            goal_id=goal.goal_id,
            tasks=tasks,
            reasoning_summary=str(
                data.get("reasoning_summary", "")
            ),
            metadata={
                "planner_generated": True,
                "provider": response.provider,
                "model": response.model,
            },
        )

        return plan
