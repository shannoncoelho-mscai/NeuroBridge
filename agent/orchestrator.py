"""NeuroBridge agent orchestrator.

    safety check -> language -> skills -> plan (LLM, validated; deterministic fallback)
    -> execute (AgentLoop + AgentToolBridge: permissions, approvals, retries)
    -> observe (tool results -> observations -> ranked evidence)
    -> replan if evidence is missing -> read top pages
    -> synthesize -> verify (deterministic + LLM) -> correct -> controller -> redact
    -> output safety -> goal-completion gate -> gap research (bounded) -> result

Honesty rules enforced here:
- no answer is synthesized without retrieved evidence;
- a run is COMPLETED only when the goal gate says so;
- simulated work is never reported as completed;
- consequential tools pause for human approval; booking confirmation is not an agent tool.
"""
from datetime import datetime, timezone
import re
import uuid

from agent.schemas import AgentGoal, AgentPlan, AgentTask, AgentState, AgentMode, TaskStatus, \
    PlanStatus, ApprovalStatus
from agent.planner.planner import AgentPlanner
from agent.executor.engine import AgentExecutionEngine
from agent.executor.tool_executor import AgentToolExecutor
from agent.executor.tool_bridge import AgentToolBridge
from agent.loop import AgentLoop
from agent.safety.policy import classify_input, enforce_output
from agent.middleware.language_support import get_language_context
from agent.research import evidence as ev
from agent.research.synthesis import synthesize
from agent.research.verification import verify_answer, deterministic_check
from agent.research.correction import correct_answer, choose_answer, redact_unsupported
from agent.research.goal_gate import goal_gate, GOAL_COMPLETE
from agent.research.expansion import initial_queries, gap_queries, keyword_query

STATUS_COMPLETED = "COMPLETED"
STATUS_PARTIAL = "PARTIAL"
STATUS_WAITING_APPROVAL = "WAITING_APPROVAL"
STATUS_FAILED = "FAILED"
STATUS_NO_EVIDENCE = "NO_EVIDENCE"
STATUS_EMERGENCY = "EMERGENCY_GUIDANCE"

RESEARCH_TOOLS = {"web_search", "web_page_reader"}
BOOKING_READ_TOOLS = {"provider_search", "find_slots", "event_search"}


def _now():
    return datetime.now(timezone.utc).isoformat()


class AgentRun:
    def __init__(self, goal_text, criteria, user_id, language, permissions):
        self.run_id = "run_" + uuid.uuid4().hex[:12]
        self.goal_text = goal_text
        self.criteria = list(criteria or [])
        self.user_id = user_id
        self.language = language
        self.permissions = set(permissions or [])
        self.state = None
        self.trace = []
        self.status = "RUNNING"
        self.answer = None
        self.sources = []
        self.verification = None
        self.gate = None
        self.errors = []
        self.round = 0
        self.tried_queries = []
        self.safety = None
        self.policy_note = None
        self.read_urls = set()
        self.read_rounds = set()
        self.engine = None
        self.research_needed = True
        self.ranked = {"evidence": []}

    def to_dict(self):
        state = self.state
        tasks = []
        if state and state.plan:
            tasks = [{"task_id": t.task_id, "name": t.name, "status": t.status.value,
                      "tool": t.required_tool, "error": t.error,
                      "requires_approval": t.requires_approval,
                      "revision": t.metadata.get("plan_revision", 0)} for t in state.plan.tasks]
        approvals = []
        if state:
            approvals = [{"approval_id": a.approval_id, "status": a.status.value,
                          "reason": a.reason, "task_id": a.action_details.get("task_id"),
                          "task_name": a.action_details.get("task_name"),
                          "tool_name": a.action_details.get("tool_name"),
                          "arguments": a.action_details.get("arguments"),
                          "summary": a.action_details.get("summary")}
                         for a in state.approval_requests]
        return {
            "run_id": self.run_id, "status": self.status, "goal": self.goal_text,
            "answer": self.answer, "sources": self.sources, "verification": self.verification,
            "goal_gate": self.gate, "tasks": tasks, "approvals": approvals,
            "tool_calls": state.tool_call_count if state else 0,
            "trace": self.trace, "errors": self.errors, "language": self.language,
            "safety": self.safety, "rounds": self.round,
            "plan_reasoning": state.plan.reasoning_summary if state and state.plan else None,
            "provider_request": bool(getattr(self, "wants_providers", False)),
        }


class NeuroBridgeAgent:
    def __init__(self, gateway, tool_registry, skill_registry=None, max_rounds=2, events=None,
                 max_tool_calls=20, max_iterations=60, use_llm_verifier=True,
                 tool_retries=2, retry_backoff=0.5, on_event=None):
        self.gateway = gateway
        self.tools = tool_registry
        self.skills = skill_registry
        self.max_rounds = max_rounds
        self.max_tool_calls = max_tool_calls
        self.max_iterations = max_iterations
        self.use_llm_verifier = use_llm_verifier
        self.tool_retries = tool_retries
        self.retry_backoff = retry_backoff
        self.on_event = on_event
        self.events = events
        self.runs = {}

    # ------------------------------------------------------------------ utils
    def _log(self, run, phase, message, **data):
        event = {"time": _now(), "phase": phase, "message": message, **data}
        run.trace.append(event)
        if self.on_event:
            try:
                self.on_event(run.run_id, event)
            except Exception:
                pass

    def _has_tool(self, name):
        try:
            self.tools.get(name)
            return True
        except KeyError:
            return False

    def _search_task(self, query, revision=0, reason="research"):
        return AgentTask(name=f"Search: {query}", description=f"Web search for '{query}'",
                         required_tool="web_search", required_skill="research",
                         metadata={"tool_arguments": {"query": query, "max_results": 5},
                                   "plan_revision": revision, "origin": reason})

    # --------------------------------------------------------------- planning
    def _fallback_plan(self, goal, run):
        tasks = [self._search_task(q, reason="fallback_plan") for q in initial_queries(run.goal_text)]
        run.tried_queries += [t.metadata["tool_arguments"]["query"] for t in tasks]
        tasks.append(AgentTask(name="Synthesize findings",
                               description="Write an evidence-grounded answer with citations.",
                               dependencies=[t.task_id for t in tasks],
                               metadata={"plan_revision": 0}))
        return AgentPlan(goal_id=goal.goal_id, tasks=tasks,
                         reasoning_summary="Deterministic fallback research plan.",
                         metadata={"planner_generated": False})

    def _make_plan(self, goal, run, selected_skills):
        if self.gateway is None:
            self._log(run, "plan", "No LLM configured; using deterministic fallback plan.")
            return self._fallback_plan(goal, run)
        planner = AgentPlanner(self.gateway, skills=[s.to_dict() for s in selected_skills],
                               tools=self.tools.list_tools())
        try:
            plan = planner.create_plan(goal)
            self._log(run, "plan", "LLM planner produced a plan.", tasks=len(plan.tasks))
            return plan
        except Exception as exc:
            run.errors.append(f"Planner failed: {exc}")
            self._log(run, "plan", "Planner failed; using deterministic fallback plan.",
                      error=str(exc))
            return self._fallback_plan(goal, run)

    EVENT_TYPE_WORDS = [("support_group", ["support group", "peer group", "circle", "support meeting"]),
                        ("workshop", ["workshop", "class", "training", "course"]),
                        ("club", ["club"]),
                        ("social_gathering", ["gathering", "social", "meetup", "meet-up", "coffee", "hangout"]),
                        ("community_meeting", ["community meeting", "town hall", "forum"]),
                        ("activity", ["activity", "activities", "art", "walk", "yoga", "games"])]
    AUDIENCE_WORDS = {"autism": ["autis"], "adhd": ["adhd"], "caregivers": ["caregiver", "carer", "parent"],
                      "psychosis": ["psychosis", "schizophren", "hearing voices"], "did": ["did", "dissociat"],
                      "teens": ["teen", "adolescent"], "anxiety": ["anxiety", "anxious"]}

    PROFESSION_WORDS = [("Psychiatrist", ["psychiatrist", "psychiatry"]),
                        ("Developmental paediatrician", ["developmental paediatrician",
                                                         "developmental pediatrician"]),
                        ("Occupational therapist", ["occupational therapist", "occupational therapy"]),
                        ("Speech therapist", ["speech therapist", "speech therapy", "speech-language"]),
                        ("Psychologist", ["psychologist", "psychology", "psychotherapist"]),
                        ("Counsellor", ["counsellor", "counselor", "counselling", "counseling"]),
                        ("therapist", ["therapist", "therapy"])]
    PLACE_RE = re.compile(r"\b(?:in|near|around|at)\s+((?!me\b|my\b|the\b|a\b)[A-Z][\w.-]+"
                          r"(?:[ ,]+(?!and\b|for\b)[A-Z][\w.-]+){0,2})")
    BOOK_RE = re.compile(r"\b(book|reserve|schedule|sign (me|us) up|make an appointment|"
                         r"get an appointment|fix an appointment)\b", re.IGNORECASE)

    def _profession(self, goal_text):
        t = goal_text.lower()
        for name, words in self.PROFESSION_WORDS:
            if any(w in t for w in words):
                return name
        return None

    def _place(self, goal_text):
        m = self.PLACE_RE.search(goal_text)
        return m.group(1).strip(" ,.") if m else None

    def _provider_tasks(self, goal_text):
        prof, place = self._profession(goal_text), self._place(goal_text)
        args = {k: v for k, v in (("profession", prof), ("location", place)) if v}
        search = AgentTask(name="Search the NeuroBridge provider directory",
                           description="Find verified, bookable providers",
                           required_tool="provider_search", required_skill="appointment_booking",
                           metadata={"tool_arguments": dict(args), "plan_revision": 0,
                                     "origin": "provider_plan"})
        slots = AgentTask(name="Find open times", description="Open times with listed providers",
                          required_tool="find_slots", required_skill="appointment_booking",
                          dependencies=[search.task_id],
                          metadata={"tool_arguments": dict(args), "plan_revision": 0,
                                    "origin": "provider_plan"})
        tasks = [search, slots]
        if self.BOOK_RE.search(goal_text) and self._has_tool("book_appointment"):
            tasks.append(AgentTask(name="Book the earliest suitable time",
                                   description="Reserve after the person approves the exact details",
                                   required_tool="book_appointment",
                                   required_skill="appointment_booking",
                                   dependencies=[slots.task_id],
                                   metadata={"tool_arguments": {}, "plan_revision": 0,
                                             "origin": "provider_plan"}))
        return tasks

    def _provider_queries(self, goal_text):
        prof = self._profession(goal_text) or "mental health professional"
        place = self._place(goal_text) or "India"
        return [f"{prof} {place} clinic appointment contact",
                f"{prof} {place} autism ADHD neurodivergent adults"]

    def _event_tasks(self, goal_text):
        t = goal_text.lower()
        args = {}
        for etype, words in self.EVENT_TYPE_WORDS:
            if any(w in t for w in words):
                args["event_type"] = etype
                break
        for aud, words in self.AUDIENCE_WORDS.items():
            if any(re.search(rf"\b{w}", t) for w in words):
                args["audience"] = aud
                break
        if "online" in t:
            args["online"] = True
        if "sensory" in t or "quiet" in t:
            args["accessibility"] = ["sensory_friendly"]
        search = AgentTask(name="Search community events", description="Find matching NeuroBridge events",
                           required_tool="event_search", required_skill="community_events",
                           metadata={"tool_arguments": args, "plan_revision": 0, "origin": "events_plan"})
        tasks = [search]
        if re.search(r"\b(book|register|sign (me|us) up|reserve|enrol|enroll|join)\b", t):
            tasks.append(AgentTask(name="Register for the best match", description="Register after approval",
                                   required_tool="register_for_event", required_skill="community_events",
                                   dependencies=[search.task_id],
                                   metadata={"tool_arguments": {}, "plan_revision": 0, "origin": "events_plan"}))
        return tasks

    def _validate_plan(self, plan, run, research_needed):
        """Make the plan safe and executable. Never trust tool names/args from the LLM."""
        for task in plan.tasks:
            task.metadata.setdefault("plan_revision", 0)
            tool = task.required_tool
            if tool and not self._has_tool(tool):
                self._log(run, "plan", f"Planner referenced unknown tool '{tool}'; removed.",
                          task=task.name)
                task.metadata["invalid_tool"] = tool
                task.required_tool = None
                continue
            if not tool:
                continue
            spec = self.tools.get(tool)
            args = dict(task.metadata.get("tool_arguments") or {})
            if tool == "web_search":
                query = args.get("query") or keyword_query(task.description)
                args["query"] = " ".join(str(query).split()[:15])
                args.setdefault("max_results", 5)
                run.tried_queries.append(args["query"])
            if tool == "web_page_reader":
                args.pop("urls", None)  # resolved at runtime from ranked evidence
            if "caregiver_user_id" in spec.required_arguments or tool in {"request_appointment",
                                                                         "cancel_appointment"}:
                args["caregiver_user_id"] = run.user_id  # never act for another user
            if tool == "register_for_event":
                args["user_id"] = run.user_id          # never register someone else
                args.pop("approved_details_hash", None)  # computed from the live listing, never by the LLM
            allowed = spec.required_arguments | {"max_results", "profession", "specialty",
                                                 "language", "location", "child_age",
                                                 "online_only", "provider_id", "slot_id",
                                                 "caregiver_notes", "appointment_type",
                                                 "appointment_id", "caregiver_user_id",
                                                 "event_type", "audience", "text", "online",
                                                 "accessibility", "event_id", "attendees", "needs",
                                                 "user_id", "date_from", "date_to"}
            args = {k: v for k, v in args.items() if k in allowed}
            task.metadata["tool_arguments"] = args
            if tool == "book_appointment":
                args["caregiver_user_id"] = run.user_id
            if spec.approval_required and tool not in ("register_for_event", "book_appointment"):
                task.requires_approval = True
                task.metadata["approval_reason"] = (
                    f"'{tool}' is a consequential action. Arguments: {args}")
            # register_for_event: approval is requested at execution time, after the event is
            # resolved, so the person approves the exact live details (see _resolve_arguments).

        if getattr(run, "wants_events", False) and self._has_tool("event_search") and \
                not any(t.required_tool == "event_search" for t in plan.tasks):
            new = self._event_tasks(run.goal_text)
            for t in plan.tasks:
                if t.required_tool == "register_for_event":
                    t.dependencies = list({*t.dependencies, new[0].task_id})
                    new = new[:1]
            plan.tasks = new + plan.tasks
            self._log(run, "plan", "Added community-event search to the plan.",
                      arguments=new[0].metadata["tool_arguments"])
        if getattr(run, "wants_providers", False) and self._has_tool("provider_search") and \
                not any(t.required_tool in ("provider_search", "find_slots", "request_appointment",
                                            "book_appointment") for t in plan.tasks):
            new = self._provider_tasks(run.goal_text)
            plan.tasks = new + plan.tasks
            self._log(run, "plan", "Added provider-directory search to the plan.",
                      arguments=new[0].metadata["tool_arguments"],
                      will_book=any(t.required_tool == "book_appointment" for t in new))
        prof = self._profession(run.goal_text) if getattr(run, "wants_providers", False) else None
        if research_needed and prof and not any(
                t.required_tool == "web_search" and prof.lower() in
                str(t.metadata.get("tool_arguments", {}).get("query", "")).lower()
                for t in plan.tasks):
            new = [self._search_task(q, reason="provider_search_queries")
                   for q in self._provider_queries(run.goal_text)]
            run.tried_queries += [t.metadata["tool_arguments"]["query"] for t in new]
            plan.tasks = new + plan.tasks
            self._log(run, "plan", "Added searches for real providers.",
                      queries=[t.metadata["tool_arguments"]["query"] for t in new])
        if research_needed and not any(t.required_tool == "web_search" for t in plan.tasks):
            queries = (self._provider_queries(run.goal_text)
                       if getattr(run, "wants_providers", False) else initial_queries(run.goal_text))
            new = [self._search_task(q, reason="validator_added_search") for q in queries]
            run.tried_queries += [t.metadata["tool_arguments"]["query"] for t in new]
            for t in plan.tasks:
                if not t.dependencies:
                    t.dependencies = [n.task_id for n in new]
            plan.tasks = new + plan.tasks
            self._log(run, "plan", "Plan had no web search; added search tasks.",
                      queries=[t.metadata["tool_arguments"]["query"] for t in new])
        return plan

    # -------------------------------------------------------------- execution
    def _resolve_arguments(self, run):
        def resolve_event(state, task, arguments):
            if arguments.get("approved_details_hash"):
                return arguments  # already resolved and shown to the person; keep what they saw
            if not self.events:
                raise RuntimeError("Events are not available.")
            if not arguments.get("event_id"):
                found = None
                for tr in reversed(state.tool_results):
                    if tr.tool_name == "event_search" and ev.tool_result_succeeded(tr):
                        evs = [e for e in tr.result.get("events", []) if e.get("seats_left", 0) > 0]
                        if evs:
                            found = evs[0]["event_id"]
                            break
                if not found:
                    raise RuntimeError("No matching event with free seats was found to register for.")
                arguments["event_id"] = found
            if not run.user_id:
                raise RuntimeError("A user ID is needed to register for events.")
            arguments["user_id"] = run.user_id
            prep = self.events.prepare_registration(arguments["event_id"], arguments.get("attendees", 1))
            if not prep.get("success"):
                raise RuntimeError(prep.get("message", "Event unavailable."))
            arguments["approved_details_hash"] = prep["details_hash"]
            sm = prep["summary"]
            task.metadata["approval_summary"] = sm
            task.metadata["approval_reason"] = (
                f"Register {sm['attendees']} for '{sm['title']}' ({sm['type']}) on {sm['start']} – "
                f"{sm['where']}, fee: {sm['fee']}" + (" [DEMO LISTING]" if sm["demo_listing"] else "")
                + ". Approve these exact details?")
            task.metadata["tool_arguments"] = dict(arguments)   # persist so approval stays bound
            return arguments

        def resolve_booking(state, task, arguments):
            if arguments.get("slot_id") and task.metadata.get("approval_summary"):
                return arguments          # already shown to the person; keep what they saw
            arguments["caregiver_user_id"] = run.user_id
            if not run.user_id:
                raise RuntimeError("Sign in to book appointments.")
            chosen = None
            for tr in reversed(state.tool_results):
                if tr.tool_name == "find_slots" and ev.tool_result_succeeded(tr):
                    slots = tr.result.get("slots", [])
                    if arguments.get("slot_id"):
                        slots = [x for x in slots if x["slot_id"] == arguments["slot_id"]]
                    if slots:
                        goal = run.goal_text.lower()

                        def rank(x):
                            spec = sum(1 for sp in x.get("specialties") or []
                                       if sp and sp.lower() in goal)
                            # real listings first, then best specialty match, then earliest
                            return (bool(x.get("is_demo")), -spec, x["start_time"])
                        chosen = sorted(slots, key=rank)[0]
                    break
            if not chosen:
                raise RuntimeError("No NeuroBridge-listed provider has an open time that matches, "
                                   "so nothing was booked.")
            arguments["slot_id"] = chosen["slot_id"]
            fee = f"₹{chosen['fee_amount']:g}" if chosen.get("fee_amount") else "not listed"
            where = chosen.get("address") or chosen.get("location") or "see listing"
            if chosen.get("online_consultation"):
                where += " (online possible)"
            sm = {"provider": chosen["provider_name"], "profession": chosen.get("profession"),
                  "start": chosen["start_time"], "end": chosen["end_time"], "where": where,
                  "fee": fee, "demo_listing": bool(chosen.get("is_demo"))}
            task.metadata["approval_summary"] = sm
            task.metadata["approval_reason"] = (
                f"Book {sm['provider']} ({sm['profession']}) on "
                f"{sm['start'][:16].replace('T', ' ')} – {sm['where']}, fee: {sm['fee']}"
                + (" [DEMO LISTING]" if sm["demo_listing"] else "")
                + ". The clinic will still confirm. Approve these exact details?")
            task.metadata["tool_arguments"] = dict(arguments)
            return arguments

        def resolver(state, task, arguments):
            if task.required_tool == "register_for_event":
                return resolve_event(state, task, arguments)
            if task.required_tool == "book_appointment":
                return resolve_booking(state, task, arguments)
            if task.required_tool == "web_page_reader" and not arguments.get("urls"):
                pool = ev.rank_evidence(ev.merge_evidence(state))
                urls = [e["url"] for e in pool["evidence"] if e["url"] not in run.read_urls][:3]
                if not urls:
                    raise RuntimeError("No search results available to read.")
                run.read_urls.update(urls)
                arguments["urls"] = urls
            return arguments
        return resolver

    def _handler(self, run):
        executor = AgentToolExecutor(self.tools, max_tool_calls=self.max_tool_calls)
        bridge = AgentToolBridge(self.tools, executor, granted_permissions=run.permissions,
                                 max_retries=self.tool_retries,
                                 backoff_seconds=self.retry_backoff,
                                 argument_resolver=self._resolve_arguments(run))

        def handle(state, task):
            if task.required_tool:
                return bridge(state, task)
            return {"type": "reasoning_step", "handled_by": "synthesis",
                    "note": "Non-tool step; its content is produced during synthesis."}
        return handle

    def _execute(self, run):
        loop = AgentLoop(run.engine, max_steps=50, dry_run=False,
                         on_event=lambda e: self._log(run, "execute", e["event"], **{
                             k: v for k, v in e.items() if k != "event"}))
        loop.run(run.state, task_handler=self._handler(run))

    def _append_tasks(self, run, tasks):
        state = run.state
        revision = state.plan.revision + 1
        for t in tasks:
            t.metadata["plan_revision"] = revision
        state.plan.tasks.extend(tasks)
        state.plan.revision = revision
        state.plan.status = PlanStatus.ACTIVE
        state.is_completed = False
        state.is_paused = False
        state.is_running = True
        run.engine.refresh_ready_tasks(state)

    # ------------------------------------------------------------- research
    def _collect(self, run):
        ev.record_tool_observations(run.state)
        pool = ev.merge_evidence(run.state)
        for tr in run.state.tool_results:
            if tr.tool_name == "web_page_reader" and ev.tool_result_succeeded(tr):
                ev.add_page_content(pool, tr.result)
        run.ranked = ev.rank_evidence(pool)
        self._log(run, "observe", "Evidence collected.",
                  sources=run.ranked["total"], successful_searches=pool["successful_searches"],
                  failed_searches=pool["failed_searches"])
        return run.ranked

    def _failed_queries(self, run):
        out = []
        for tr in run.state.tool_results:
            if tr.tool_name == "web_search" and not ev.tool_result_succeeded(tr):
                payload = tr.result if isinstance(tr.result, dict) else {}
                out.append({"query": payload.get("query"), "error": tr.error})
        return out

    def _synthesize_and_verify(self, run):
        items = ev.evidence_for_prompt(run.ranked)
        lang = get_language_context(run.language, user_text=run.goal_text)
        lang_note = (f"Write the answer in {lang['language']}." if lang["language"] != "auto-detect"
                     else "Write the answer in the same language as the user goal.")
        draft = synthesize(self.gateway, run.goal_text, items, self._failed_queries(run),
                           language_note=lang_note, policy_note=run.policy_note)
        v1 = verify_answer(self.gateway, run.goal_text, draft, run.ranked, items,
                           use_llm=self.use_llm_verifier)
        self._log(run, "verify", "Draft verified.", passed=v1["passed"], score=v1["score"],
                  critical=len(v1["deterministic"]["critical_issues"]),
                  unsupported=len(v1["deterministic"]["unsupported_claims"]))
        answer, verification, decision = draft, v1, "ACCEPT_ORIGINAL"
        if not v1["passed"]:
            try:
                revised = correct_answer(self.gateway, run.goal_text, draft, v1, items)
                v2 = verify_answer(self.gateway, run.goal_text, revised, run.ranked, items,
                                   use_llm=self.use_llm_verifier)
                choice = choose_answer(draft, v1, revised, v2)
                answer, verification, decision = choice["answer"], choice["verification"], \
                    choice["decision"]
                self._log(run, "correct", f"Self-correction: {decision}.",
                          passed=verification["passed"], score=verification["score"])
            except Exception as exc:
                run.errors.append(f"Correction failed: {exc}")
                self._log(run, "correct", "Self-correction failed.", error=str(exc))
        det = verification["deterministic"]
        if det["critical_issues"] or det["unsupported_claims"]:
            answer, removed = redact_unsupported(answer, det)
            recheck = deterministic_check(answer, run.ranked, run.goal_text)
            verification = {**verification, "deterministic": recheck,
                            "passed": recheck["passed"],
                            "score": recheck["score"],
                            "redacted_statements": removed}
            decision = "REDACTED_UNSUPPORTED"
            self._log(run, "correct", "Redacted unsupported statements.", removed=removed,
                      passed=verification["passed"])

        def regen(instruction):
            return synthesize(self.gateway, run.goal_text, items, policy_note=instruction,
                              language_note=lang_note)
        answer, out_safety = enforce_output(answer, regenerate=regen)
        if out_safety["flagged"]:
            self._log(run, "safety", "Output safety intervention.", **out_safety)
            verification = {**verification, "output_safety": out_safety}
        verification["decision"] = decision
        return answer, verification, items

    # ----------------------------------------------------------------- public
    def run(self, goal_text, success_criteria=None, user_id=None, preferred_language=None,
            granted_permissions=None):
        run = AgentRun(goal_text, success_criteria, user_id, preferred_language,
                       granted_permissions)
        self.runs[run.run_id] = run
        goal = AgentGoal(description=goal_text, success_criteria=list(success_criteria or []))
        run.state = AgentState(goal=goal, mode=AgentMode.AGENT,
                               preferred_language=preferred_language or "auto")
        run.engine = AgentExecutionEngine(max_iterations=self.max_iterations)

        safety = classify_input(goal_text)
        run.safety = {"category": safety["category"],
                      "flags": {k: bool(v) for k, v in safety["flags"].items()}}
        if safety["halt_agent"]:
            run.engine.emergency_stop(run.state, reason=safety["category"])
            run.status, run.answer = STATUS_EMERGENCY, safety["override_response"]
            self._log(run, "safety", "Emergency/self-harm signal: all agent tasks halted; "
                                     "fixed guidance returned. No tools were used.")
            return run.to_dict()
        run.policy_note = safety["policy_note"]
        if run.policy_note:
            self._log(run, "safety", "Medical-safety policy note applied.",
                      category=safety["category"])

        selected = self.skills.select(goal_text) if self.skills else []
        self._log(run, "skills", "Skills selected.", skills=[s.name for s in selected])
        booking_like = {"appointment_booking", "community_events"}
        wants_booking = any(s.name in booking_like for s in selected)
        explicit_research = bool(re.search(r"\b(research|sources?|evidence|studies|study|citations?|"
                                           r"information about|learn about|what does the research)\b",
                                           goal_text, re.IGNORECASE))
        run.wants_events = any(s.name == "community_events" for s in selected)
        run.wants_providers = (any(s.name == "appointment_booking" for s in selected)
                               and not run.wants_events) or (
            bool(self._profession(goal_text)) and bool(self.BOOK_RE.search(goal_text)))
        real_world = bool(self._profession(goal_text) or self._place(goal_text) or
                          re.search(r"\bnear (me|us)\b|\bnearby\b", goal_text, re.IGNORECASE))
        research_needed = explicit_research or not wants_booking or \
            (run.wants_providers and real_world)
        plan = self._validate_plan(self._make_plan(goal, run, selected), run, research_needed)
        run.engine.activate(run.state, plan)
        self._log(run, "plan", "Plan activated.",
                  tasks=[{"name": t.name, "tool": t.required_tool,
                          "approval": t.requires_approval} for t in plan.tasks])
        run.research_needed = research_needed
        return self._continue(run)

    def resume(self, run_id, approval_id, approved, reviewed_by="caregiver",
               rejection_reason=None):
        run = self.runs.get(run_id)
        if run is None:
            raise KeyError(f"Unknown run: {run_id}")
        if run.status != STATUS_WAITING_APPROVAL:
            raise RuntimeError(f"Run is not waiting for approval (status {run.status}).")
        run.engine.review_approval(run.state, approval_id, approved=approved,
                                     reviewed_by=reviewed_by, rejection_reason=rejection_reason)
        self._log(run, "approval", "Approval reviewed.", approval_id=approval_id,
                  approved=bool(approved), reviewed_by=reviewed_by)
        run.state.is_paused = True
        run.engine.resume(run.state)
        run.status = "RUNNING"
        return self._continue(run)

    def _continue(self, run):
        state = run.state
        while True:
            self._execute(run)
            if state.is_paused and any(a.status == ApprovalStatus.PENDING
                                       for a in state.approval_requests):
                run.status = STATUS_WAITING_APPROVAL
                self._log(run, "approval", "Waiting for caregiver approval.")
                return run.to_dict()
            if state.is_paused:
                run.status = STATUS_FAILED
                run.errors.append(state.error or "Agent paused unexpectedly.")
                return run.to_dict()

            ranked = self._collect(run)

            if not getattr(run, "research_needed", True):
                return self._finish_non_research(run)

            if not ranked["evidence"]:
                if run.round < self.max_rounds:
                    run.round += 1
                    queries = gap_queries(self.gateway, run.goal_text,
                                          ["No search results were retrieved"],
                                          run.tried_queries)
                    if queries:
                        run.tried_queries += queries
                        self._log(run, "replan", "No evidence; replanning with new queries.",
                                  round=run.round, queries=queries)
                        self._append_tasks(run, [self._search_task(q, reason="replan_no_evidence")
                                                 for q in queries])
                        continue
                run.status = STATUS_NO_EVIDENCE
                failed = self._failed_queries(run)
                run.answer = ("I could not retrieve any sources for this request, so I have not "
                              "written an answer (NeuroBridge does not answer research questions "
                              "without evidence).\n\nSearch attempts: "
                              + ("; ".join(f"'{f['query']}' — {f['error']}" for f in failed)
                                 or "none succeeded") +
                              "\n\nPlease check the search configuration (TAVILY_API_KEY or ddgs) "
                              "or try rephrasing.")
                self._log(run, "finish", "Finished without evidence.")
                return run.to_dict()

            if self._has_tool("web_page_reader"):
                unread = [e["url"] for e in ranked["evidence"]
                          if e["url"] not in run.read_urls][:3]
                if unread and run.round not in run.read_rounds:
                    run.read_rounds.add(run.round)
                    self._log(run, "read", "Reading top-ranked pages.", urls=unread)
                    self._append_tasks(run, [AgentTask(
                        name="Read top sources", description="Extract page content",
                        required_tool="web_page_reader", required_skill="research",
                        metadata={"tool_arguments": {}})])
                    continue

            if self.gateway is None:
                run.status = STATUS_FAILED
                run.errors.append("No LLM provider configured; cannot synthesize an answer.")
                run.sources = self._sources(run)
                run.answer = ("Sources were retrieved (listed below) but no language model is "
                              "configured, so no answer was written.")
                return run.to_dict()

            try:
                answer, verification, items = self._synthesize_and_verify(run)
            except Exception as exc:
                run.status = STATUS_FAILED
                run.errors.append(f"Synthesis failed: {exc}")
                run.sources = self._sources(run)
                self._log(run, "synthesize", "Synthesis failed.", error=str(exc))
                return run.to_dict()

            gate = goal_gate(self.gateway, run.goal_text, run.criteria, answer, verification,
                             items, simulated=bool(state.metadata.get("simulated")))
            if verification.get("redacted_statements") and gate["goal_complete"]:
                # Content was removed, so the answer may no longer cover the goal.
                gate = {**gate, "status": "QUALITY_APPROVED_BUT_GOAL_INCOMPLETE",
                        "goal_complete": False, "needs_research": True,
                        "unmet_requirements": gate["unmet_requirements"] + [
                            "Some statements were removed because no source supported them"]}
            self._log(run, "goal_gate", gate["status"], unmet=gate["unmet_requirements"])
            actions = self._action_lines(run)
            if actions:
                answer = answer + "\n\n**Actions taken:**\n" + "\n".join(f"- {a}" for a in actions)
            run.answer, run.verification, run.gate = answer, verification, gate
            run.sources = self._sources(run, cited=verification["deterministic"].get(
                "citations_used"))

            if gate["goal_complete"]:
                run.status = STATUS_COMPLETED
                self._log(run, "finish", "Goal complete.")
                return run.to_dict()
            if run.round < self.max_rounds and gate["needs_research"]:
                run.round += 1
                queries = gap_queries(self.gateway, run.goal_text, gate["unmet_requirements"],
                                      run.tried_queries)
                if queries:
                    run.tried_queries += queries
                    self._log(run, "replan", "Goal incomplete; researching gaps.",
                              round=run.round, queries=queries)
                    self._append_tasks(run, [self._search_task(q, reason="gap_research")
                                             for q in queries])
                    continue
            run.status = STATUS_PARTIAL if verification["passed"] or run.answer else STATUS_FAILED
            self._log(run, "finish", "Finished; goal not fully complete.",
                      unmet=gate["unmet_requirements"])
            return run.to_dict()

    def _action_lines(self, run):
        lines, _ = self._registry_lines(run)
        return lines

    def _finish_non_research(self, run):
        """Booking/registry goals: report tool results verbatim, never paraphrase into facts."""
        lines, any_ok = self._registry_lines(run)
        return self._finish_with_lines(run, lines, any_ok)

    def _registry_lines(self, run):
        lines, any_ok = [], False
        for tr in run.state.tool_results:
            if tr.tool_name in RESEARCH_TOOLS:
                continue
            ok = ev.tool_result_succeeded(tr)
            any_ok = any_ok or ok
            payload = tr.result if isinstance(tr.result, dict) else {}
            if tr.tool_name == "provider_search" and ok:
                names = [p.get("provider_name") for p in payload.get("providers", [])]
                lines.append(f"Verified providers found in the NeuroBridge registry: "
                             f"{', '.join(names) if names else 'none'}.")
            elif tr.tool_name == "event_search" and ok:
                evs = payload.get("events", [])
                lines.append("Events found: " + ("; ".join(
                    f"#{e['event_id']} {e['title']} ({e['event_type']}, {e['start_time'][:16].replace('T', ' ')}, "
                    f"{'online' if e['is_online'] else e['location']}, {e['seats_left']} seats left"
                    f"{', DEMO LISTING' if e['is_demo'] else ''})" for e in evs) if evs else "none matched") + ".")
            elif tr.tool_name == "register_for_event" and ok:
                lines.append(f"Registration {payload.get('status')} for '{payload.get('event')}' on "
                             f"{payload.get('start')}" + (f", code {payload['confirmation_code']}" if
                                                          payload.get('confirmation_code') else "")
                             + (" (demo listing)" if payload.get("demo_listing") else "") + ".")
            elif tr.tool_name == "book_appointment" and ok:
                lines.append(f"Booked in NeuroBridge: {payload.get('provider_name')} on "
                             f"{str(payload.get('start_time'))[:16].replace('T', ' ')}, reference "
                             f"{payload.get('confirmation_code')}. The clinic still has to confirm "
                             f"— you'll see it in Providers & appointments when they do.")
            elif tr.tool_name == "find_slots" and ok:
                slots = [f"slot {s['slot_id']}: {s['provider_name']} {s['start_time']}"
                         for s in payload.get("slots", [])]
                lines.append("Available slots: " + ("; ".join(slots) if slots else "none") + ".")
            elif ok:
                lines.append(f"{tr.tool_name}: {payload.get('message', 'done')}")
            else:
                msg = payload.get("message") or tr.error
                lines.append(f"{tr.tool_name} failed: {msg}")
        for t in run.state.plan.tasks:
            if t.required_tool == "book_appointment" and t.status == TaskStatus.FAILED:
                lines.append("Nothing was booked: no NeuroBridge-listed provider has a matching "
                             "open time. To contact a clinic from the sources above, use "
                             "“Track this clinic” — NeuroBridge will keep the details and draft a "
                             "message for you. Please check phone numbers on the clinic's own "
                             "website.")
        return lines, any_ok

    def _finish_with_lines(self, run, lines, any_ok):
        failed_tasks = [t for t in run.state.plan.tasks if t.status == TaskStatus.FAILED]
        cancelled = [t for t in run.state.plan.tasks if t.status == TaskStatus.CANCELLED]
        run.answer = "\n".join(lines) or "No registry actions were performed."
        if cancelled:
            run.answer += f"\n\n{len(cancelled)} action(s) were not performed because approval was declined."
        run.status = STATUS_COMPLETED if (any_ok and not failed_tasks and not cancelled and
                                          run.state.is_completed) else STATUS_PARTIAL if any_ok \
            else STATUS_FAILED
        self._log(run, "finish", f"Registry run finished: {run.status}.")
        return run.to_dict()

    def _sources(self, run, cited=None):
        cited = set(cited or [])
        return [{"id": e["citation_id"], "title": e.get("title"), "url": e.get("url"),
                 "category": e.get("category"), "cited": e["citation_id"] in cited,
                 "page_read": bool(e.get("page_content"))}
                for e in run.ranked.get("evidence", [])]
