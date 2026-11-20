"""NeuroBridge API.

Kept from the notebook version: /, /health, /providers, /chat, /agent/run, /agent/tools,
/agent/status, /memory/suggest, /memory/save, /memory/{user_id}, DELETE /memory/{user_id}/{key},
and initialize(gateway_instance).

New: safety checks on chat, real agent runs with tools + verification, approvals,
booking endpoints, /ui. Run with:  uvicorn agent.api.app:app --port 8000
"""
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from agent.memory.memory_store import initialize_memory, memory_context, save_memory, \
    get_memories, delete_memory
from agent.memory.memory_manager import extract_memory_candidates
from agent.pipeline import NeuroBridgePipeline
from agent.llm.multilingual_gateway import multilingual_generate
from agent.safety.policy import classify_input, enforce_output
from agent.skills import load_default_skills
from agent.tools.builtin import build_tool_registry, BOOKING_WRITE
from agent.tools.booking_db import BookingStore
from agent.tools.events_db import EventStore
from agent.orchestrator import NeuroBridgeAgent

gateway = None
pipeline = None
agent = None
tool_registry = None
booking_store = None
event_store = None
init_status = {"initialized": False}

STATIC_DIR = Path(__file__).resolve().parent / "static"

@asynccontextmanager
async def _lifespan(_app):
    _auto_initialize()
    yield


app = FastAPI(title="NeuroBridge API",
              description="Caregiver-support chat and research agent (not a medical service)",
              version="0.2.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("NEUROBRIDGE_CORS_ORIGINS", "*").split(","),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

CHAT_SYSTEM_PROMPT = (
    "You are NeuroBridge, a helpful caregiver-support AI. "
    "Be empathetic, clear, practical, and cautious. "
    "Do not diagnose, prescribe, or recommend changing medication. "
    "For emergencies, advise contacting local emergency services (112 in India). "
    "Do not pretend to perform actions you have not performed. "
    "If asked for specific providers, facts or sources, say the user can use Research mode, "
    "which searches the web and cites sources; do not invent names, numbers or links. "
    "In sensitive situations, be soft, slow and calming in tone, but take a clear stand: if "
    "something could need medical help, say plainly that they should get it, and if it is "
    "severe or sudden they must call 112 now. Always finish your answer; keep it complete "
    "rather than long, and prefer short paragraphs over large tables. "
)


# ----------------------------------------------------------------- models
class ChatRequest(BaseModel):
    message: str
    history: List[Dict[str, str]] = Field(default_factory=list)
    provider: Optional[str] = None
    preferred_language: Optional[str] = None
    user_id: Optional[str] = None


class MemorySuggestRequest(BaseModel):
    user_id: str
    conversation_text: str


class MemorySaveRequest(BaseModel):
    user_id: str
    candidates: List[Dict[str, Any]]
    approved_keys: List[str] = Field(default_factory=list)
    explicit_consent: bool = False
    allow_sensitive: bool = False


class AgentRequest(BaseModel):
    goal: str
    priority: str = "normal"
    success_criteria: List[str] = Field(default_factory=list)
    user_id: Optional[str] = None
    preferred_language: Optional[str] = None
    simulate: bool = False
    allow_booking_actions: bool = False


class ApprovalDecision(BaseModel):
    approval_id: str
    approved: bool
    reviewed_by: str = "caregiver"
    rejection_reason: Optional[str] = None


class ProviderRequest(BaseModel):
    provider: str


class ProviderRegistration(BaseModel):
    provider_name: str
    profession: str
    specialties: List[str] = Field(default_factory=list)
    age_groups: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    location: Optional[str] = None
    organization: Optional[str] = None
    credentials: Optional[str] = None
    online_consultation: bool = False
    fee_amount: Optional[float] = None


class SlotRequest(BaseModel):
    provider_id: int
    start_time: str
    end_time: str
    duration_minutes: int = 60
    fee_amount: Optional[float] = None


class AppointmentRequest(BaseModel):
    slot_id: int
    caregiver_user_id: str
    child_age: Optional[int] = None
    appointment_type: str = "consultation"
    caregiver_notes: Optional[str] = None


class AppointmentDecision(BaseModel):
    appointment_id: int
    caregiver_user_id: str
    explicit_approval: bool = False


# ----------------------------------------------------------------- setup
def initialize(gateway_instance, tools=None, store=None, skills=None, agent_options=None, events=None):
    """Wire components. `gateway_instance` may be None (no LLM): research then returns
    sources without an answer, and chat returns 503."""
    global gateway, pipeline, agent, tool_registry, booking_store, event_store, init_status
    gateway = gateway_instance
    initialize_memory()
    booking_store = store or BookingStore(os.environ.get("NEUROBRIDGE_BOOKING_DB") or None)
    event_store = events or EventStore(booking_store.db_path)
    tool_registry = tools or build_tool_registry(booking_store=booking_store, event_store=event_store)
    pipeline = NeuroBridgePipeline(gateway=gateway, dry_run=True, max_iterations=25,
                                   max_loop_steps=10) if gateway else None
    agent = NeuroBridgeAgent(gateway, tool_registry, skills or load_default_skills(),
                             events=event_store, **(agent_options or {}))
    if os.environ.get("NEUROBRIDGE_SEED_DEMO_EVENTS") == "1":
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        from seed_demo_events import seed
        seed(event_store)
    from agent.tools.web_search import available_providers
    init_status = {"initialized": True, "llm_providers": gateway.list_providers() if gateway else [],
                   "search_providers": available_providers()}
    return init_status


def _auto_initialize():
    if init_status.get("initialized") or os.environ.get("NEUROBRIDGE_AUTO_INIT", "1") != "1":
        return
    from agent.bootstrap import build_gateway_from_env
    gw, status = build_gateway_from_env()
    initialize(gw)
    init_status["provider_errors"] = status["errors"]
    init_status["local_models"] = status.get("local_models")
    init_status["environment"] = os.environ.get("NEUROBRIDGE_ENV", "production")


def extract_response_text(response):
    if isinstance(response, str):
        return response
    for attr in ("text", "content", "output", "response"):
        value = getattr(response, attr, None)
        if isinstance(value, str):
            return value
    if isinstance(response, dict):
        for key in ("text", "content", "output", "response"):
            if isinstance(response.get(key), str):
                return response[key]
    return str(response)


def _require_agent():
    if agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")


# ----------------------------------------------------------------- general
@app.get("/")
def root():
    return {"name": "NeuroBridge API", "status": "running", "version": "0.2.0",
            "modes": ["chat", "agent"], "ui": "/ui",
            "notice": "Caregiver-support assistant. Not a doctor or an emergency service."}


@app.get("/health")
def health():
    return {"status": "healthy", "gateway_initialized": gateway is not None,
            "agent_initialized": agent is not None,
            "llm_providers": init_status.get("llm_providers", []),
            "search_providers": init_status.get("search_providers", []),
            "provider_errors": init_status.get("provider_errors", []),
            "default_provider": gateway.default_provider if gateway else None,
            "local_models": init_status.get("local_models"),
            "environment": init_status.get("environment", "production")}


HOSTED_LABELS = {"groq": "Groq (hosted)", "gemini": "Gemini (hosted)",
                 "dev_mock": "Development mock (not an AI)"}


def provider_label(name):
    try:
        prov = gateway.registry.get(name)
        if hasattr(prov, "label"):
            return prov.label
    except Exception:
        pass
    from agent.llm.hf_provider import LABELS
    if name in LABELS:
        return LABELS[name].replace("({base}, no fine-tuning)", "(no fine-tuning)")
    return HOSTED_LABELS.get(name, name)


@app.get("/providers")
def providers():
    if gateway is None:
        raise HTTPException(status_code=503, detail="Gateway not initialized")
    return {"providers": gateway.list_providers(), "default_provider": gateway.default_provider,
            "fallback_provider": gateway.fallback_provider,
            "models": [{"provider": n, "label": provider_label(n)} for n in gateway.list_providers()]}


@app.get("/ui", response_class=HTMLResponse)
def ui():
    return FileResponse(STATIC_DIR / "index.html")


# ----------------------------------------------------------------- chat
class CompareRequest(BaseModel):
    message: str
    providers: List[str]
    history: List[Dict[str, str]] = Field(default_factory=list)
    preferred_language: Optional[str] = None
    user_id: Optional[str] = None


def _safety_meta(safety):
    return {"category": safety["category"],
            "flags": {k: bool(v) for k, v in safety["flags"].items()}}


def _chat_reply(message, history, provider, preferred_language, user_id, safety, no_fallback=False):
    messages = [{"role": m.get("role"), "content": str(m.get("content", ""))}
                for m in history if m.get("role") in ("user", "assistant")]
    messages.append({"role": "user", "content": message})
    system_prompt = CHAT_SYSTEM_PROMPT
    if safety["policy_note"]:
        system_prompt += "\nSAFETY NOTE: " + safety["policy_note"]
    if user_id:
        system_prompt += "\n" + memory_context(user_id)

    def call(extra=None):
        return multilingual_generate(
            gateway=gateway, messages=messages, preferred_language=preferred_language,
            system_prompt=system_prompt + (("\n" + extra) if extra else ""),
            provider=provider, temperature=0.4, max_tokens=2048, no_fallback=no_fallback)

    response = call()
    reply, out_safety = enforce_output(extract_response_text(response),
                                       regenerate=lambda note: extract_response_text(call(note)))
    metadata = dict(getattr(response, "metadata", {}) or {})
    metadata["safety"] = {**_safety_meta(safety), "output": out_safety}
    metadata["llm_called"] = True
    metadata["label"] = provider_label(getattr(response, "provider", provider) or "")
    return {"reply": reply, "provider": getattr(response, "provider", None), "metadata": metadata}


@app.post("/chat")
def chat(request: ChatRequest):
    safety = classify_input(request.message)
    if safety["halt_agent"]:
        # Fixed, verified guidance (agent/safety/first_aid.py); no LLM call, no actions.
        return {"reply": safety["override_response"], "provider": None,
                "metadata": {"safety": _safety_meta(safety), "llm_called": False}}
    if gateway is None:
        raise HTTPException(status_code=503, detail="Gateway not initialized (no LLM API key "
                                                    "configured)")
    try:
        return _chat_reply(request.message, request.history, request.provider,
                           request.preferred_language, request.user_id, safety)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}")


@app.post("/chat/compare")
def chat_compare(request: CompareRequest):
    """Send the same message to several models (e.g. nb_base, nb_sft, nb_sft_orpo)."""
    safety = classify_input(request.message)
    if safety["halt_agent"]:
        return {"emergency": True, "reply": safety["override_response"],
                "safety": _safety_meta(safety), "results": []}
    if gateway is None:
        raise HTTPException(status_code=503, detail="Gateway not initialized")
    results = []
    for name in request.providers[:4]:
        if name not in gateway.list_providers():
            results.append({"provider": name, "error": "not configured"})
            continue
        try:
            r = _chat_reply(request.message, request.history, name, request.preferred_language,
                            request.user_id, safety, no_fallback=True)
            if r["provider"] != name:
                r["metadata"]["note"] = f"{name} failed; reply came from fallback {r['provider']}"
            results.append({"provider": name, "label": provider_label(name), **r})
        except Exception as exc:
            results.append({"provider": name, "label": provider_label(name), "error": str(exc)})
    return {"emergency": False, "results": results}


# ----------------------------------------------------------------- agent
@app.post("/agent/run")
def run_agent(request: AgentRequest):
    _require_agent()
    if request.simulate:
        if pipeline is None:
            raise HTTPException(status_code=503, detail="Simulation needs an LLM for planning")
        try:
            state = pipeline.run_goal(description=request.goal, priority=request.priority,
                                      success_criteria=request.success_criteria)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Agent execution failed: {exc}")
        return {"goal": request.goal, "completed": state.is_completed, "goal_achieved": False,
                "paused": state.is_paused, "iteration": state.iteration,
                "state": state.to_dict(), "execution_mode": "simulation",
                "notice": "Simulation: tasks were planned but NOT performed."}
    permissions = {BOOKING_WRITE} if (request.allow_booking_actions and request.user_id) else set()
    try:
        return agent.run(request.goal, success_criteria=request.success_criteria,
                         user_id=request.user_id, preferred_language=request.preferred_language,
                         granted_permissions=permissions)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent execution failed: {exc}")


@app.get("/agent/runs/{run_id}")
def get_run(run_id: str):
    _require_agent()
    run = agent.runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run.to_dict()


@app.post("/agent/runs/{run_id}/approve")
def approve_run(run_id: str, decision: ApprovalDecision):
    _require_agent()
    try:
        return agent.resume(run_id, decision.approval_id, approved=decision.approved,
                            reviewed_by=decision.reviewed_by,
                            rejection_reason=decision.rejection_reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/agent/tools")
def list_tools():
    if tool_registry is None:
        return {"tools": [], "notice": "Agent not initialized."}
    return {"tools": tool_registry.list_tools(enabled_only=False)}


@app.get("/agent/status")
def agent_status():
    return {"agent": "NeuroBridge Deep Agent", "initialized": agent is not None,
            "mode": "live" if gateway else "no_llm",
            "runs": len(agent.runs) if agent else 0}


# ----------------------------------------------------------------- booking
def _store():
    if booking_store is None:
        raise HTTPException(status_code=503, detail="Booking store not initialized")
    return booking_store


@app.post("/booking/providers/register")
def register_provider(body: ProviderRegistration):
    return _store().register_provider(**body.model_dump())


@app.post("/booking/providers/{provider_id}/verify")
def verify_provider(provider_id: int, verified: bool = True,
                    x_admin_token: Optional[str] = Header(default=None)):
    token = os.environ.get("NEUROBRIDGE_ADMIN_TOKEN")
    if not token or x_admin_token != token:
        raise HTTPException(status_code=403, detail="Administrator token required")
    return _store().verify_provider(provider_id, verified=verified)


@app.post("/booking/slots")
def add_slot(body: SlotRequest, x_admin_token: Optional[str] = Header(default=None)):
    token = os.environ.get("NEUROBRIDGE_ADMIN_TOKEN")
    if not token or x_admin_token != token:
        raise HTTPException(status_code=403, detail="Administrator token required")
    return _store().add_availability(**body.model_dump())


@app.get("/booking/providers")
def search_providers(profession: Optional[str] = None, specialty: Optional[str] = None,
                     language: Optional[str] = None, location: Optional[str] = None,
                     child_age: Optional[int] = None, online_only: bool = False):
    return _store().search_providers(profession, specialty, language, location, child_age,
                                     online_only)


@app.get("/booking/slots")
def find_slots(provider_id: Optional[int] = None, location: Optional[str] = None,
               specialty: Optional[str] = None, language: Optional[str] = None,
               child_age: Optional[int] = None):
    return _store().find_available_slots(provider_id, location, specialty, language, child_age)


@app.post("/booking/request")
def request_appointment(body: AppointmentRequest):
    return _store().request_appointment(**body.model_dump())


@app.post("/booking/approve")
def approve_appointment(body: AppointmentDecision):
    result = _store().approve_appointment(body.appointment_id, body.caregiver_user_id,
                                          explicit_approval=body.explicit_approval)
    if not result.get("success") and "Explicit caregiver approval" in result.get("message", ""):
        raise HTTPException(status_code=403, detail=result["message"])
    return result


@app.post("/booking/cancel")
def cancel_appointment(body: AppointmentDecision):
    if not body.explicit_approval:
        raise HTTPException(status_code=403, detail="Explicit caregiver approval is required")
    return _store().cancel_appointment(body.appointment_id, body.caregiver_user_id)


@app.get("/booking/mine/{caregiver_user_id}")
def my_appointments(caregiver_user_id: str):
    return _store().get_appointments(caregiver_user_id)


# ----------------------------------------------------------------- events
class EventCreate(BaseModel):
    title: str
    event_type: str
    start_time: str
    end_time: str
    capacity: int
    description: Optional[str] = None
    organizer: Optional[str] = None
    location: Optional[str] = None
    is_online: bool = False
    fee_amount: float = 0.0
    accessibility: List[str] = Field(default_factory=list)
    audience: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    recurrence: Optional[str] = None


class EventRegistration(BaseModel):
    user_id: str
    attendees: int = 1
    needs: Optional[str] = None
    approved_details_hash: Optional[str] = None
    explicit_approval: bool = False


class RegistrationCancel(BaseModel):
    user_id: str


def _events():
    if event_store is None:
        raise HTTPException(status_code=503, detail="Events not initialized")
    return event_store


def _admin(token):
    expected = os.environ.get("NEUROBRIDGE_ADMIN_TOKEN")
    if not expected or token != expected:
        raise HTTPException(status_code=403, detail="Administrator token required")


@app.get("/events")
def list_events(event_type: Optional[str] = None, audience: Optional[str] = None,
                location: Optional[str] = None, text: Optional[str] = None, online: Optional[bool] = None,
                accessibility: Optional[str] = None):
    acc = [a for a in (accessibility or "").split(",") if a] or None
    return _events().search_events(event_type, audience, location, text, online, acc)


@app.get("/events/{event_id}")
def get_event(event_id: int):
    r = _events().get_event(event_id)
    if not r["success"]:
        raise HTTPException(status_code=404, detail=r["message"])
    return r


@app.post("/events")
def create_event(body: EventCreate, x_admin_token: Optional[str] = Header(default=None)):
    _admin(x_admin_token)
    return _events().create_event(**body.model_dump())


@app.get("/events/{event_id}/prepare")
def prepare_registration(event_id: int, attendees: int = 1):
    """Exact details + fingerprint to show the person before they approve."""
    return _events().prepare_registration(event_id, attendees)


@app.post("/events/{event_id}/register")
def register_event(event_id: int, body: EventRegistration):
    if not body.explicit_approval or not body.approved_details_hash:
        raise HTTPException(status_code=403, detail="Explicit approval of the exact event details is required")
    r = _events().register(event_id, body.user_id, body.attendees, body.needs,
                           body.approved_details_hash, body.explicit_approval)
    if r.get("approval_stale"):
        raise HTTPException(status_code=409, detail=r["message"])
    return r


@app.post("/events/registrations/{registration_id}/cancel")
def cancel_event_registration(registration_id: int, body: RegistrationCancel):
    return _events().cancel_registration(registration_id, body.user_id)


@app.get("/events/mine/{user_id}")
def my_event_registrations(user_id: str):
    return _events().my_registrations(user_id)


# ----------------------------------------------------------------- memory
@app.post("/memory/suggest")
def memory_suggest(request: MemorySuggestRequest):
    if gateway is None:
        raise HTTPException(status_code=503, detail="Gateway not initialized")
    try:
        result = extract_memory_candidates(gateway=gateway,
                                           conversation_text=request.conversation_text,
                                           existing_memories=get_memories(request.user_id))
        return {"success": True, "requires_user_approval": True,
                "candidates": result.get("candidates", []), "provider": result.get("provider")}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/memory/save")
def memory_save(request: MemorySaveRequest):
    if not request.user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    if not request.explicit_consent:
        raise HTTPException(status_code=403, detail="Explicit consent is required to save memories.")
    try:
        from agent.memory.memory_manager import is_sensitive_text
        approved_keys = set(request.approved_keys or [])
        saved, rejected = [], []
        for candidate in request.candidates or []:
            key = candidate.get("key")
            if key not in approved_keys:
                continue
            sensitive = bool(candidate.get("sensitive", False)) or is_sensitive_text(
                f"{key} {candidate.get('value', '')}")
            if sensitive and not request.allow_sensitive:
                rejected.append({"key": key, "reason": "sensitive_memory_requires_separate_approval"})
                continue
            result = save_memory(user_id=request.user_id,
                                 memory_type=candidate.get("memory_type", "long_term"),
                                 category=candidate.get("category", "other"), key=key,
                                 value=candidate.get("value", ""), consent=True,
                                 source="user_approved_candidate",
                                 ttl_days=candidate.get("suggested_ttl_days"))
            if result.get("success"):
                saved.append(key)
            else:
                rejected.append({"key": key, "reason": result.get("error", "save_failed")})
        return {"success": len(rejected) == 0, "saved": saved, "rejected": rejected,
                "saved_count": len(saved)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/memory/{user_id}")
def memory_get(user_id: str):
    try:
        return {"success": True, "user_id": user_id, "memories": get_memories(user_id)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/memory/{user_id}/{key}")
def memory_delete(user_id: str, key: str):
    try:
        return {"success": True, "user_id": user_id, "key": key,
                "result": delete_memory(user_id=user_id, key=key)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
