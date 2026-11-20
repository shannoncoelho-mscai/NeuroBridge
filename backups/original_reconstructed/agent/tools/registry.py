
from dataclasses import dataclass, field
from typing import Callable, Any
from datetime import datetime, timezone
import uuid


def _now():
    return datetime.now(timezone.utc).isoformat()


def _id():
    return str(uuid.uuid4())


class ToolExecutionError(Exception):
    pass


@dataclass
class ToolSpec:
    name: str
    description: str
    function: Callable
    required_permissions: set = field(default_factory=set)
    required_arguments: set = field(default_factory=set)
    approval_required: bool = False
    enabled: bool = True
    metadata: dict = field(default_factory=dict)


class ToolRegistry:

    def __init__(self):
        self._tools = {}

    def register(self, tool: ToolSpec):
        if not isinstance(tool, ToolSpec):
            raise TypeError("Tool must be a ToolSpec instance.")

        if not tool.name or not tool.name.strip():
            raise ValueError("Tool name cannot be empty.")

        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")

        if not callable(tool.function):
            raise TypeError("Tool function must be callable.")

        self._tools[tool.name] = tool
        return tool

    def get(self, name):
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        return self._tools[name]

    def list_tools(self, enabled_only=True):
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "enabled": tool.enabled,
                "approval_required": tool.approval_required,
                "required_permissions": sorted(tool.required_permissions),
                "required_arguments": sorted(tool.required_arguments),
            }
            for tool in self._tools.values()
            if (tool.enabled or not enabled_only)
        ]

    def execute(
        self,
        name,
        arguments=None,
        granted_permissions=None,
        approved=False,
    ):
        arguments = arguments or {}
        granted_permissions = granted_permissions or set()

        tool = self.get(name)

        if not tool.enabled:
            raise ToolExecutionError(f"Tool is disabled: {name}")

        if not isinstance(arguments, dict):
            raise ToolExecutionError("Tool arguments must be a dictionary.")

        missing = tool.required_arguments - set(arguments.keys())
        if missing:
            raise ToolExecutionError(
                f"Missing required arguments: {sorted(missing)}"
            )

        missing_permissions = (
            tool.required_permissions - granted_permissions
        )

        if missing_permissions:
            raise ToolExecutionError(
                f"Permission denied. Missing permissions: "
                f"{sorted(missing_permissions)}"
            )

        if tool.approval_required and not approved:
            raise ToolExecutionError(
                f"Tool requires explicit approval: {name}"
            )

        call_id = _id()
        started_at = _now()

        try:
            result = tool.function(**arguments)

            return {
                "call_id": call_id,
                "tool_name": name,
                "status": "success",
                "result": result,
                "error": None,
                "started_at": started_at,
                "completed_at": _now(),
                "metadata": {},
            }

        except Exception as exc:
            return {
                "call_id": call_id,
                "tool_name": name,
                "status": "failure",
                "result": None,
                "error": str(exc),
                "started_at": started_at,
                "completed_at": _now(),
                "metadata": {
                    "exception_type": type(exc).__name__,
                },
            }

    def disable(self, name):
        tool = self.get(name)
        tool.enabled = False
        return tool

    def enable(self, name):
        tool = self.get(name)
        tool.enabled = True
        return tool

    def unregister(self, name):
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        return self._tools.pop(name)
