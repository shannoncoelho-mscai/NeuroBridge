from agent.schemas import (
    AgentState,
    AgentPlan,
    AgentTask,
    utc_now,
    ApprovalRequest,
    AgentMode,
    ApprovalStatus,
    TaskStatus,
    PlanStatus,
)


class AgentExecutionEngine:

    def __init__(self, max_iterations=25):
        self.max_iterations = max_iterations

    def activate(self, state: AgentState, plan: AgentPlan):
        if state.is_running:
            raise RuntimeError("Agent is already running.")

        if plan.status != PlanStatus.DRAFT:
            raise RuntimeError("Only draft plans can be activated.")

        if plan.goal_id != state.goal.goal_id:
            raise ValueError("Plan does not belong to this agent goal.")

        state.plan = plan
        state.mode = AgentMode.AGENT
        state.is_running = True
        state.is_paused = False
        state.is_completed = False
        state.error = None

        plan.status = PlanStatus.ACTIVE

        self.refresh_ready_tasks(state)
        state.update_timestamp()

        return state

    def refresh_ready_tasks(self, state: AgentState):
        if state.plan is None:
            return []

        newly_ready = []

        for task in state.plan.tasks:
            if task.status != TaskStatus.PENDING:
                continue

            dependencies_completed = all(
                any(
                    candidate.task_id == dep
                    and candidate.status == TaskStatus.COMPLETED
                    for candidate in state.plan.tasks
                )
                for dep in task.dependencies
                )

            if dependencies_completed:
                task.status = TaskStatus.READY
                newly_ready.append(task)

        state.update_timestamp()
        return newly_ready

    def request_approval(self, state, task_id, reason):
        self._ensure_running(state)
        task = self._get_task(state, task_id)

        if task.status != TaskStatus.READY:
            raise RuntimeError("Only ready tasks can request approval.")

        if not task.requires_approval:
            raise RuntimeError("This task does not require approval.")

        for existing in state.approval_requests:
            if (
                existing.action_details.get("task_id") == task_id
                and existing.status == ApprovalStatus.PENDING
            ):
                return existing

        request = ApprovalRequest(
            action="start_task",
            reason=str(reason),
            action_details={
                "task_id": task.task_id,
                "task_name": task.name,
            },
        )

        state.approval_requests.append(request)
        state.update_timestamp()
        return request

    def review_approval(
        self,
        state,
        approval_id,
        approved,
        reviewed_by="user",
        rejection_reason=None,
    ):
        request = next(
            (
                item for item in state.approval_requests
                if item.approval_id == approval_id
            ),
            None,
        )

        if request is None:
            raise KeyError(f"Approval request not found: {approval_id}")

        if request.status != ApprovalStatus.PENDING:
            raise RuntimeError("This approval request has already been reviewed.")

        task = self._get_task(
            state,
            request.action_details.get("task_id"),
        )

        if task.status != TaskStatus.READY:
            raise RuntimeError("Task is no longer ready for approval.")

        request.status = (
            ApprovalStatus.APPROVED if approved
            else ApprovalStatus.REJECTED
        )
        request.reviewed_by = str(reviewed_by)
        request.reviewed_at = utc_now()
        request.rejection_reason = (
            None if approved else str(rejection_reason or "Rejected by reviewer")
        )

        if not approved:
            task.status = TaskStatus.CANCELLED

        state.update_timestamp()
        return request

    def start_task(self, state: AgentState, task_id: str):
        self._ensure_running(state)

        if state.iteration >= self.max_iterations:
            raise RuntimeError("Maximum agent iterations reached.")

        task = self._get_task(state, task_id)

        if task.status != TaskStatus.READY:
            raise RuntimeError(
                f"Task is not ready. Current status: {task.status.value}"
            )

        # Revalidate dependencies immediately before starting.
        if state.plan is None:
            raise RuntimeError("No plan is attached.")

        for dependency_id in task.dependencies:
            dependency = self._get_task(state, dependency_id)

            if dependency.status != TaskStatus.COMPLETED:
                raise RuntimeError(
                    f"Dependency is not completed: {dependency.name}"
                )

        # Enforce human approval for tasks that require it.
        if task.requires_approval:
            matching_approvals = [
                approval
                for approval in state.approval_requests
                if approval.action_details.get("task_id") == task.task_id
            ]

            approved = any(
                approval.status == ApprovalStatus.APPROVED
                for approval in matching_approvals
            )

            if not approved:
                raise RuntimeError(
                    f"Task requires explicit approval before starting: {task.name}"
                )

        task.status = TaskStatus.IN_PROGRESS
        state.iteration += 1
        state.update_timestamp()

        return task

    def complete_task(self, state: AgentState, task_id: str, result=None):
        self._ensure_running(state)

        task = self._get_task(state, task_id)

        if task.status != TaskStatus.IN_PROGRESS:
            raise RuntimeError("Only in-progress tasks can be completed.")

        task.status = TaskStatus.COMPLETED
        task.result = result
        task.error = None

        self.refresh_ready_tasks(state)
        self._check_plan_completion(state)
        state.update_timestamp()

        return task

    def fail_task(self, state: AgentState, task_id: str, error: str):
        task = self._get_task(state, task_id)

        if task.status != TaskStatus.IN_PROGRESS:
            raise RuntimeError("Only in-progress tasks can be failed.")

        task.status = TaskStatus.FAILED
        task.error = str(error)

        state.error = str(error)
        state.update_timestamp()

        return task

    def pause(self, state: AgentState):
        if state.plan is None:
            raise RuntimeError("No plan is attached to this agent state.")

        state.is_running = False
        state.is_paused = True
        state.plan.status = PlanStatus.PAUSED

        state.update_timestamp()
        return state

    def resume(self, state: AgentState):
        if state.plan is None:
            raise RuntimeError("No plan is attached to this agent state.")

        if not state.is_paused:
            raise RuntimeError("Agent is not paused.")

        if state.is_completed:
            raise RuntimeError("Completed agent cannot be resumed.")

        state.is_paused = False
        state.is_running = True
        state.plan.status = PlanStatus.ACTIVE

        self.refresh_ready_tasks(state)
        state.update_timestamp()

        return state

    def cancel(self, state: AgentState):
        if state.plan is None:
            raise RuntimeError("No plan is attached to this agent state.")

        for task in state.plan.tasks:
            if task.status not in (
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            ):
                task.status = TaskStatus.CANCELLED

        state.is_running = False
        state.is_paused = False
        state.is_completed = False
        state.plan.status = PlanStatus.CANCELLED

        state.update_timestamp()
        return state

    def emergency_stop(self, state: AgentState, reason="Emergency interruption"):
        """Immediately suspend routine agent work."""

        if state.plan is not None:
            state.plan.status = PlanStatus.PAUSED

        state.is_running = False
        state.is_paused = True

        state.metadata["emergency_stop"] = True
        state.metadata["emergency_reason"] = str(reason)

        state.update_timestamp()
        return state

    def _check_plan_completion(self, state: AgentState):
        if state.plan is None:
            return

        if all(
            task.status == TaskStatus.COMPLETED
            for task in state.plan.tasks
        ):
            state.plan.status = PlanStatus.COMPLETED
            state.is_running = False
            state.is_paused = False
            state.is_completed = True

    def _ensure_running(self, state: AgentState):
        if not state.is_running:
            raise RuntimeError("Agent is not currently running.")

        if state.is_paused:
            raise RuntimeError("Agent is paused.")

        if state.plan is None:
            raise RuntimeError("No plan is attached.")

    def _get_task(self, state: AgentState, task_id: str):
        if state.plan is None:
            raise RuntimeError("No plan is attached.")

        for task in state.plan.tasks:
            if task.task_id == task_id:
                return task

        raise KeyError(f"Task not found: {task_id}")
