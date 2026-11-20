from agent.schemas import AgentGoal, AgentState, AgentMode
from agent.planner.planner import AgentPlanner
from agent.executor.engine import AgentExecutionEngine
from agent.loop import AgentLoop


class NeuroBridgePipeline:
    """
    NeuroBridge goal-to-execution pipeline.

    Flow:
    Goal -> Planner -> State -> Engine -> Agent Loop -> Task Handler

    This is the original plan-and-simulate pipeline (kept for compatibility). The full
    research agent with tools, verification and replanning is agent.orchestrator.
    """

    def __init__(
        self,
        gateway,
        max_iterations=25,
        max_loop_steps=10,
        dry_run=True,
        task_handler=None,
    ):
        self.planner = AgentPlanner(gateway)

        self.engine = AgentExecutionEngine(
            max_iterations=max_iterations
        )

        self.agent_loop = AgentLoop(
            engine=self.engine,
            max_steps=max_loop_steps,
            dry_run=dry_run,
        )

        self.dry_run = dry_run
        self.task_handler = task_handler

    def run_goal(
        self,
        description,
        priority="normal",
        success_criteria=None,
        task_handler=None,
    ):
        # 1. Create goal
        goal = AgentGoal(
            description=description,
            priority=priority,
            success_criteria=success_criteria or [],
        )

        # 2. Generate plan
        plan = self.planner.create_plan(goal)

        if plan is None or not plan.tasks:
            raise RuntimeError("Planner returned an empty plan.")

        # 3. Create state
        state = AgentState(
            goal=goal,
            mode=AgentMode.AGENT,
            plan=plan,
        )

        # 4. Activate engine
        self.engine.activate(state, plan)

        # 5. Select task handler
        active_handler = (
            task_handler
            if task_handler is not None
            else self.task_handler
        )

        # 6. Run Agent Loop
        state = self.agent_loop.run(
            state,
            task_handler=active_handler,
        )

        # 7. Record pipeline metadata
        simulated = bool(state.metadata.get("simulated"))
        state.metadata["pipeline"] = {
            "dry_run": self.dry_run,
            "handler_configured": active_handler is not None,
            "goal_description": description,
            "simulated": simulated,
            # A simulated plan "completes" mechanically, but no goal work was done.
            "goal_achieved": bool(state.is_completed and not simulated),
        }

        state.update_timestamp()

        return state
