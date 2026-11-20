from typing import Callable, Optional

from agent.schemas import TaskStatus, ApprovalStatus
from agent.executor.engine import AgentExecutionEngine


class ApprovalRequiredError(Exception):
    """Raised by a task handler when an action needs explicit human approval."""

    def __init__(self, reason, details=None):
        super().__init__(reason)
        self.reason = reason
        self.details = details or {}


class AgentLoop:
    """
    Bounded orchestration loop for NeuroBridge.

    Supports:
    - Ready-task orchestration and dependency-aware execution
    - Controlled task handlers
    - Dry-run simulation (always flagged: state.metadata["simulated"] = True)
    - Approval pauses (task-level and handler-raised ApprovalRequiredError)
    - Step limits
    - Structured execution events

    Changes vs. the notebook version (see docs/AUDIT.md):
    - iterations are counted once (by engine.start_task), not twice
    - start_task errors (e.g. iteration limit) are caught and recorded
    - simulated completions are flagged so they cannot be reported as real work
    - tasks whose approval was granted proceed after resume instead of re-requesting
    """

    def __init__(
        self,
        engine: AgentExecutionEngine,
        max_steps: int = 25,
        dry_run: bool = True,
        on_event: Optional[Callable] = None,
    ):
        self.engine = engine
        self.max_steps = max_steps
        self.dry_run = dry_run
        self.on_event = on_event

    def _event(self, state, event_type, **details):
        event = {"event": event_type, "iteration": state.iteration, **details}
        state.metadata.setdefault("agent_loop_events", []).append(event)
        state.update_timestamp()
        if self.on_event:
            try:
                self.on_event(event)
            except Exception:
                pass

    @staticmethod
    def _approval_status(state, task):
        statuses = [
            a.status for a in state.approval_requests
            if a.action_details.get("task_id") == task.task_id
        ]
        if ApprovalStatus.APPROVED in statuses:
            return "approved"
        if ApprovalStatus.PENDING in statuses:
            return "pending"
        return None

    def run(self, state, task_handler: Optional[Callable] = None):
        if state.plan is None:
            raise ValueError("Cannot run AgentLoop without an active plan.")

        if state.is_completed or state.is_paused:
            return state

        if not state.is_running:
            raise RuntimeError("Agent is not running; activate or resume it first.")

        self._event(state, "loop_started")
        steps = 0

        while (
            state.is_running
            and not state.is_paused
            and not state.is_completed
            and steps < self.max_steps
        ):
            steps += 1

            self.engine.refresh_ready_tasks(state)
            ready_tasks = [t for t in state.plan.tasks if t.status == TaskStatus.READY]

            if not ready_tasks:
                unfinished = [
                    t for t in state.plan.tasks
                    if t.status not in (TaskStatus.COMPLETED, TaskStatus.CANCELLED)
                ]
                if not unfinished:
                    self.engine._check_plan_completion(state)
                    break
                self._event(
                    state, "loop_blocked",
                    unfinished_tasks=[t.task_id for t in unfinished],
                    failed_tasks=[t.task_id for t in unfinished if t.status == TaskStatus.FAILED],
                )
                break

            progressed = False

            for task in ready_tasks:
                if not state.is_running or state.is_paused:
                    break

                # Task-level approval (set by the planner or the safety policy).
                if task.requires_approval:
                    approval_state = self._approval_status(state, task)
                    if approval_state != "approved":
                        approval = self.engine.request_approval(
                            state, task.task_id,
                            reason=task.metadata.get(
                                "approval_reason",
                                "Human approval required before task execution.",
                            ),
                        )
                        # Show the reviewer exactly what would be executed.
                        approval.action_details.setdefault("tool_name", task.required_tool)
                        approval.action_details.setdefault(
                            "arguments", dict(task.metadata.get("tool_arguments") or {}))
                        self.engine.pause(state)
                        self._event(
                            state, "approval_required",
                            task_id=task.task_id, task_name=task.name,
                            approval_id=approval.approval_id,
                        )
                        break

                if task.required_tool and task_handler is None and not self.dry_run:
                    self._event(state, "tool_unavailable", task_id=task.task_id,
                                required_tool=task.required_tool)
                    continue

                try:
                    self.engine.start_task(state, task.task_id)
                except Exception as exc:
                    self._event(state, "task_start_blocked", task_id=task.task_id, error=str(exc))
                    state.error = str(exc)
                    self.engine.pause(state)
                    break

                self._event(state, "task_started", task_id=task.task_id, task_name=task.name,
                            tool=task.required_tool)

                try:
                    if task_handler is not None:
                        result = task_handler(state, task)
                        simulated = False
                    elif self.dry_run:
                        result = {
                            "simulated": True,
                            "message": "Task simulated; no real action performed.",
                            "task": task.name,
                        }
                        simulated = True
                        state.metadata["simulated"] = True
                    else:
                        raise RuntimeError("No task handler configured for real execution.")

                    self.engine.complete_task(state, task.task_id, result=result)
                    self._event(state, "task_completed", task_id=task.task_id,
                                task_name=task.name, simulated=simulated)
                    progressed = True

                except ApprovalRequiredError as exc:
                    # Return the task to READY and pause for a human decision.
                    task.status = TaskStatus.READY
                    task.requires_approval = True
                    task.metadata["approval_reason"] = exc.reason
                    task.metadata["approval_details"] = exc.details
                    approval = self.engine.request_approval(state, task.task_id, reason=exc.reason)
                    approval.action_details.update(exc.details)
                    self.engine.pause(state)
                    self._event(state, "approval_required", task_id=task.task_id,
                                task_name=task.name, approval_id=approval.approval_id,
                                reason=exc.reason)
                    break

                except Exception as exc:
                    self.engine.fail_task(state, task.task_id, error=str(exc))
                    self._event(state, "task_failed", task_id=task.task_id,
                                task_name=task.name, error=str(exc))
                    progressed = True

            if state.is_paused or not state.is_running:
                break

            self.engine._check_plan_completion(state)
            if state.is_completed:
                break

            if not progressed:
                self._event(state, "no_progress")
                break

        if steps >= self.max_steps and not state.is_completed and not state.is_paused:
            self._event(state, "iteration_limit_reached")

        self._event(
            state, "loop_finished",
            completed=state.is_completed, paused=state.is_paused,
            running=state.is_running, steps=steps,
            simulated=bool(state.metadata.get("simulated")),
        )
        return state
