from typing import Callable, Optional

from agent.schemas import TaskStatus, PlanStatus
from agent.executor.engine import AgentExecutionEngine


class AgentLoop:
    """
    Bounded orchestration loop for NeuroBridge.

    This initial version supports:
    - Ready-task orchestration
    - Dependency-aware execution
    - Controlled task handlers
    - Dry-run simulation
    - Approval pauses
    - Iteration limits
    - Structured execution events
    """

    def __init__(
        self,
        engine: AgentExecutionEngine,
        max_steps: int = 25,
        dry_run: bool = True,
    ):
        self.engine = engine
        self.max_steps = max_steps
        self.dry_run = dry_run

    def _event(self, state, event_type, **details):
        events = state.metadata.setdefault("agent_loop_events", [])
        events.append({
            "event": event_type,
            "iteration": state.iteration,
            **details,
        })
        state.update_timestamp()

    def run(
        self,
        state,
        task_handler: Optional[Callable] = None,
    ):
        """
        task_handler(state, task) may be supplied to handle safe,
        application-specific tasks.

        Returns the same AgentState with execution metadata updated.
        """

        if state.plan is None:
            raise ValueError("Cannot run AgentLoop without an active plan.")

        if state.is_completed:
            return state

        if state.is_paused:
            return state

        if not state.is_running:
            self.engine.resume(state)

        self._event(state, "loop_started")

        steps = 0

        while (
            state.is_running
            and not state.is_paused
            and not state.is_completed
            and steps < self.max_steps
        ):
            steps += 1
            state.iteration += 1

            ready_tasks = self.engine.refresh_ready_tasks(state)

            # Also consider tasks that were READY before this loop.
            ready_tasks += [
                task for task in state.plan.tasks
                if task.status == TaskStatus.READY
                and task not in ready_tasks
            ]

            if not ready_tasks:
                unfinished = [
                    task for task in state.plan.tasks
                    if task.status not in (
                        TaskStatus.COMPLETED,
                        TaskStatus.CANCELLED,
                    )
                ]

                if not unfinished:
                    self.engine._check_plan_completion(state)
                    break

                self._event(
                    state,
                    "loop_blocked",
                    unfinished_tasks=[t.task_id for t in unfinished],
                )
                break

            progressed = False

            for task in ready_tasks:
                if not state.is_running or state.is_paused:
                    break

                # Approval-required tasks must stop for human review.
                if task.requires_approval:
                    approval = self.engine.request_approval(
                        state,
                        task.task_id,
                        reason="Human approval required before task execution.",
                    )

                    if approval:
                        self.engine.pause(state)
                        self._event(
                            state,
                            "approval_required",
                            task_id=task.task_id,
                            approval_id=approval.approval_id,
                        )
                        break

                    continue

                # Tasks requiring tools cannot be silently simulated
                # as completed.
                if task.required_tool and task_handler is None:
                    self._event(
                        state,
                        "tool_unavailable",
                        task_id=task.task_id,
                        required_tool=task.required_tool,
                    )
                    continue

                if not self.engine.start_task(state, task.task_id):
                    continue

                try:
                    if task_handler is not None:
                        result = task_handler(state, task)
                    elif self.dry_run:
                        result = {
                            "simulated": True,
                            "message": "Task simulated; no real action performed.",
                            "task": task.name,
                        }
                    else:
                        raise RuntimeError(
                            "No task handler configured for real execution."
                        )

                    self.engine.complete_task(
                        state,
                        task.task_id,
                        result=result,
                    )

                    self._event(
                        state,
                        "task_completed",
                        task_id=task.task_id,
                        simulated=self.dry_run and task_handler is None,
                    )

                    progressed = True

                except Exception as exc:
                    self.engine.fail_task(
                        state,
                        task.task_id,
                        error=str(exc),
                    )

                    self._event(
                        state,
                        "task_failed",
                        task_id=task.task_id,
                        error=str(exc),
                    )

                    progressed = True

            if state.is_paused or not state.is_running:
                break

            self.engine.refresh_ready_tasks(state)
            self.engine._check_plan_completion(state)

            if state.is_completed:
                break

            if not progressed:
                self._event(state, "no_progress")
                break

        if steps >= self.max_steps and not state.is_completed:
            self._event(state, "iteration_limit_reached")

        self._event(
            state,
            "loop_finished",
            completed=state.is_completed,
            paused=state.is_paused,
            running=state.is_running,
            steps=steps,
        )

        return state
