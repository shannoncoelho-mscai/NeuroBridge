
from datetime import datetime, timezone
import uuid

from agent.schemas import ToolResult, ToolStatus
from agent.tools.registry import ToolExecutionError


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _new_id():
    return str(uuid.uuid4())


class AgentToolExecutor:

    def __init__(self, registry, max_tool_calls=50):
        self.registry = registry
        self.max_tool_calls = max_tool_calls

    def execute_tool(
        self,
        state,
        tool_name,
        arguments=None,
        granted_permissions=None,
        approved=False,
    ):
        arguments = arguments or {}
        granted_permissions = granted_permissions or set()

        started_at = _utc_now()
        call_id = _new_id()

        # Agent execution state checks
        if not state.is_running or state.is_paused:
            return self._record(
                state,
                call_id,
                tool_name,
                ToolStatus.DENIED,
                error="Agent is not actively running.",
                started_at=started_at,
            )

        if state.is_completed:
            return self._record(
                state,
                call_id,
                tool_name,
                ToolStatus.DENIED,
                error="Agent has already completed.",
                started_at=started_at,
            )

        if state.tool_call_count >= self.max_tool_calls:
            return self._record(
                state,
                call_id,
                tool_name,
                ToolStatus.DENIED,
                error="Maximum tool-call limit reached.",
                started_at=started_at,
            )

        # Count each attempted call
        state.tool_call_count += 1

        try:
            registry_result = self.registry.execute(
                name=tool_name,
                arguments=arguments,
                granted_permissions=granted_permissions,
                approved=approved,
            )

            status_map = {
                "success": ToolStatus.SUCCESS,
                "failure": ToolStatus.FAILURE,
            }

            status = status_map.get(
                registry_result.get("status"),
                ToolStatus.FAILURE,
            )

            error = registry_result.get("error")
            payload = registry_result.get("result")

            # Many NeuroBridge tools catch their own exceptions and return
            # {"success": False, "error": ...}. Do not record those as SUCCESS.
            if (
                status == ToolStatus.SUCCESS
                and isinstance(payload, dict)
                and payload.get("success") is False
            ):
                status = ToolStatus.FAILURE
                error = error or payload.get("error") or payload.get("message") \
                    or "Tool reported success=False"

            result = self._record(
                state,
                registry_result.get("call_id", call_id),
                tool_name,
                status,
                result=payload,
                error=error,
                started_at=registry_result.get("started_at", started_at),
                completed_at=registry_result.get("completed_at"),
                metadata=registry_result.get("metadata", {}),
            )

            return result

        except ToolExecutionError as exc:
            message = str(exc)

            if "requires explicit approval" in message.lower():
                status = ToolStatus.NEEDS_APPROVAL
            else:
                status = ToolStatus.DENIED

            return self._record(
                state,
                call_id,
                tool_name,
                status,
                error=message,
                started_at=started_at,
            )

        except Exception as exc:
            return self._record(
                state,
                call_id,
                tool_name,
                ToolStatus.FAILURE,
                error=str(exc),
                started_at=started_at,
                metadata={"exception_type": type(exc).__name__},
            )

    def _record(
        self,
        state,
        call_id,
        tool_name,
        status,
        result=None,
        error=None,
        started_at=None,
        completed_at=None,
        metadata=None,
    ):
        tool_result = ToolResult(
            call_id=call_id,
            tool_name=tool_name,
            status=status,
            result=result,
            error=error,
            started_at=started_at or _utc_now(),
            completed_at=completed_at or _utc_now(),
            metadata=metadata or {},
        )

        state.tool_results.append(tool_result)
        state.update_timestamp()

        return tool_result
