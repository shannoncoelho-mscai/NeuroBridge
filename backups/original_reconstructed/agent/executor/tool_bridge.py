from agent.schemas import ToolStatus


class AgentToolBridge:
    """Controlled bridge between AgentLoop and AgentToolExecutor."""

    def __init__(self, registry, tool_executor, granted_permissions=None):
        self.registry = registry
        self.tool_executor = tool_executor
        self.granted_permissions = set(granted_permissions or [])

    def __call__(self, state, task):
        if not task.required_tool:
            raise RuntimeError(
                f"Task '{task.name}' has no required_tool."
            )

        tool = self.registry.get(task.required_tool)

        if not tool.enabled:
            raise RuntimeError(f"Tool is disabled: {task.required_tool}")

        if tool.approval_required:
            raise RuntimeError(
                f"Approval-required tool blocked: {task.required_tool}"
            )

        arguments = task.metadata.get("tool_arguments", {})

        if not isinstance(arguments, dict):
            raise ValueError("tool_arguments must be a dictionary.")

        result = self.tool_executor.execute_tool(
            state=state,
            tool_name=task.required_tool,
            arguments=arguments,
            granted_permissions=self.granted_permissions,
            approved=False,
        )

        if result.status != ToolStatus.SUCCESS:
            raise RuntimeError(
                f"Tool execution failed: {result.status.value}; "
                f"{result.error}"
            )

        return {
            "tool_name": result.tool_name,
            "call_id": result.call_id,
            "status": result.status.value,
            "result": result.result,
        }
