"""Regression tests reproducing the notebook's inline checks plus bugs found in the audit.

These were first run against backups/original_reconstructed (baseline) and then against
the fixed code.
"""
from agent.schemas import AgentGoal, AgentPlan, AgentTask, AgentState, TaskStatus, ToolStatus
from agent.executor.engine import AgentExecutionEngine
from agent.loop import AgentLoop
from agent.tools.registry import ToolRegistry, ToolSpec
from agent.executor.tool_executor import AgentToolExecutor
from agent.llm.gateway import LLMGateway, LLMResponse


class _P:
    def __init__(self, name, fail=False):
        self.provider_name = name
        self.fail = fail

    def generate(self, messages, **kw):
        if self.fail:
            raise RuntimeError("boom")
        return LLMResponse(text=f"hi from {self.provider_name}", provider=self.provider_name)


def test_gateway_fallback():  # notebook cell 11
    gw = LLMGateway(default_provider="a", fallback_provider="b")
    gw.register_provider(_P("a", fail=True))
    gw.register_provider(_P("b"))
    r = gw.generate(messages=[{"role": "user", "content": "x"}])
    assert r.provider == "b" and r.metadata["fallback_used"] is True


def test_engine_approval_gate():  # notebook cell 51
    goal = AgentGoal(description="g")
    task = AgentTask(name="t", description="d", requires_approval=True)
    plan = AgentPlan(goal_id=goal.goal_id, tasks=[task])
    state = AgentState(goal=goal)
    eng = AgentExecutionEngine()
    eng.activate(state, plan)
    req = eng.request_approval(state, task.task_id, "why")
    try:
        eng.start_task(state, task.task_id)
        assert False, "started without approval"
    except RuntimeError:
        pass
    eng.review_approval(state, req.approval_id, approved=True)
    eng.start_task(state, task.task_id)
    assert task.status == TaskStatus.IN_PROGRESS


def test_inner_tool_failure_is_not_reported_as_success():  # audit bug (cell 121)
    reg = ToolRegistry()
    reg.register(ToolSpec(name="s", description="", function=lambda query: {"success": False, "error": "net"},
                          required_arguments={"query"}))
    ex = AgentToolExecutor(reg)
    goal = AgentGoal(description="g")
    state = AgentState(goal=goal)
    state.is_running = True
    res = ex.execute_tool(state, "s", {"query": "q"})
    assert res.status == ToolStatus.FAILURE


def test_loop_does_not_double_count_iterations():  # audit bug
    goal = AgentGoal(description="g")
    t = AgentTask(name="t", description="d")
    plan = AgentPlan(goal_id=goal.goal_id, tasks=[t])
    state = AgentState(goal=goal)
    eng = AgentExecutionEngine()
    eng.activate(state, plan)
    AgentLoop(eng, dry_run=False).run(state, task_handler=lambda s, task: {"ok": True})
    assert state.iteration == 1


def test_dry_run_is_never_reported_as_real_completion():  # audit bug
    goal = AgentGoal(description="g")
    t = AgentTask(name="t", description="d")
    plan = AgentPlan(goal_id=goal.goal_id, tasks=[t])
    state = AgentState(goal=goal)
    eng = AgentExecutionEngine()
    eng.activate(state, plan)
    AgentLoop(eng, dry_run=True).run(state)
    assert state.metadata.get("simulated") is True


def test_truncated_reply_is_continued():
    """Batch-3 bug: long Groq replies were cut off mid-table."""
    class Chunky:
        provider_name = "chunky"
        def __init__(self):
            self.calls = 0
        def generate(self, messages, **kw):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(text="Part one, ", provider="chunky", metadata={"truncated": True})
            return LLMResponse(text="part two.", provider="chunky", metadata={"truncated": False})
    gw = LLMGateway(default_provider="chunky")
    p = Chunky()
    gw.register_provider(p)
    r = gw.generate(messages=[{"role": "user", "content": "long please"}])
    assert r.text == "Part one, part two." and r.metadata["continued"] == 1 and p.calls == 2


def test_continuation_is_bounded():
    class Endless:
        provider_name = "endless"
        def generate(self, messages, **kw):
            return LLMResponse(text="x", provider="endless", metadata={"truncated": True})
    gw = LLMGateway(default_provider="endless")
    gw.register_provider(Endless())
    assert gw.generate(messages=[{"role": "user", "content": "go"}]).text == "xxx"
