import time

from agent.schemas import ToolStatus, ApprovalStatus
from agent.loop import ApprovalRequiredError


# Errors that are worth retrying (transient network / provider problems).
TRANSIENT_MARKERS = (
    "timeout", "timed out", "connection", "reset by peer", "temporarily",
    "503", "502", "429", "rate limit", "unavailable",
)


def is_transient_error(message):
    text = (message or "").lower()
    return any(marker in text for marker in TRANSIENT_MARKERS)


class AgentToolBridge:
    """Controlled bridge between AgentLoop and AgentToolExecutor.

    - Approval-required tools pause the loop (ApprovalRequiredError) instead of being
      silently blocked; once a human approves the task, the call proceeds.
    - Transient failures are retried up to `max_retries` times with backoff.
    - Non-transient failures raise immediately so the loop marks the task FAILED.
    """

    def __init__(self, registry, tool_executor, granted_permissions=None,
                 max_retries=2, backoff_seconds=0.5, argument_resolver=None):
        self.registry = registry
        self.tool_executor = tool_executor
        self.granted_permissions = set(granted_permissions or [])
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        # Optional callable(state, task, arguments) -> arguments, used to fill
        # arguments from earlier task results (e.g. URLs for the page reader).
        self.argument_resolver = argument_resolver

    @staticmethod
    def _task_approved(state, task):
        return any(
            a.action_details.get("task_id") == task.task_id
            and a.status == ApprovalStatus.APPROVED
            for a in state.approval_requests
        )

    def __call__(self, state, task):
        if not task.required_tool:
            raise RuntimeError(f"Task '{task.name}' has no required_tool.")

        tool = self.registry.get(task.required_tool)

        if not tool.enabled:
            raise RuntimeError(f"Tool is disabled: {task.required_tool}")

        arguments = dict(task.metadata.get("tool_arguments") or {})
        if not isinstance(arguments, dict):
            raise ValueError("tool_arguments must be a dictionary.")
        if self.argument_resolver:
            arguments = self.argument_resolver(state, task, arguments)

        approved = self._task_approved(state, task)
        if tool.approval_required and not approved:
            raise ApprovalRequiredError(
                task.metadata.get("approval_reason")
                or f"'{tool.name}' is a consequential action and needs your approval.",
                details={"tool_name": tool.name, "arguments": arguments,
                         "summary": task.metadata.get("approval_summary")},
            )

        attempts = []
        for attempt in range(self.max_retries + 1):
            result = self.tool_executor.execute_tool(
                state=state,
                tool_name=task.required_tool,
                arguments=arguments,
                granted_permissions=self.granted_permissions,
                approved=approved,
            )
            attempts.append({"attempt": attempt + 1, "status": result.status.value,
                             "error": result.error})

            if result.status == ToolStatus.SUCCESS:
                return {
                    "tool_name": result.tool_name,
                    "call_id": result.call_id,
                    "status": result.status.value,
                    "result": result.result,
                    "attempts": attempts,
                }

            if result.status in (ToolStatus.DENIED, ToolStatus.NEEDS_APPROVAL):
                break
            if not is_transient_error(result.error) or attempt == self.max_retries:
                break
            time.sleep(self.backoff_seconds * (2 ** attempt))

        task.metadata["tool_attempts"] = attempts
        raise RuntimeError(
            f"Tool execution failed: {result.status.value}; {result.error} "
            f"(attempts: {len(attempts)})"
        )
