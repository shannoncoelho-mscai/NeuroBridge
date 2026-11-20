
from agent.memory.memory_store import initialize_memory, memory_context
from agent.memory.memory_manager import extract_memory_candidates
from agent.memory.memory_approval import save_approved_memory_candidates
from agent.memory.memory_store import get_memories, delete_memory

from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent.pipeline import NeuroBridgePipeline
from agent.llm.multilingual_gateway import multilingual_generate

# The existing gateway is injected when this module is initialized.
gateway = None
pipeline = None

app = FastAPI(
    title="NeuroBridge API",
    description="AI Chat and Deep Agent API for NeuroBridge",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict this before production deployment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


class ProviderRequest(BaseModel):
    provider: str


def initialize(gateway_instance):
    global gateway, pipeline
    gateway = gateway_instance

    # Initialize persistent memory database.
    initialize_memory()

    # Safe prototype mode: agent tasks are simulated by default.
    pipeline = NeuroBridgePipeline(
        gateway=gateway,
        dry_run=True,
        max_iterations=25,
        max_loop_steps=10,
    )


def extract_response_text(response):
    # Support common response shapes from providers.
    if isinstance(response, str):
        return response

    for attr in ("text", "content", "output", "response"):
        value = getattr(response, attr, None)
        if isinstance(value, str):
            return value

    if isinstance(response, dict):
        for key in ("text", "content", "output", "response"):
            value = response.get(key)
            if isinstance(value, str):
                return value

    return str(response)




@app.post("/memory/suggest")
def memory_suggest(request: MemorySuggestRequest):
    if gateway is None:
        raise HTTPException(status_code=503, detail="Gateway not initialized")

    try:
        existing = get_memories(request.user_id)

        result = extract_memory_candidates(
            gateway=gateway,
            conversation_text=request.conversation_text,
            existing_memories=existing,
        )

        return {
            "success": True,
            "requires_user_approval": True,
            "candidates": result.get("candidates", []),
            "provider": result.get("provider"),
        }

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/memory/save")
def memory_save(request: MemorySaveRequest):
    if not request.explicit_consent:
        raise HTTPException(
            status_code=403,
            detail="Explicit consent is required to save memories."
        )

    try:
        result = save_approved_memory_candidates(
            user_id=request.user_id,
            candidates=request.candidates,
            approved_keys=request.approved_keys,
            explicit_consent=request.explicit_consent,
            allow_sensitive=request.allow_sensitive,
        )
        return result

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/memory/{user_id}")
def memory_get(user_id: str):
    try:
        return {
            "success": True,
            "user_id": user_id,
            "memories": get_memories(user_id),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.delete("/memory/{user_id}/{key}")
def memory_delete(user_id: str, key: str):
    try:
        result = delete_memory(user_id=user_id, key=key)
        return {
            "success": True,
            "user_id": user_id,
            "key": key,
            "result": result,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))



@app.get("/")
def root():
    return {
        "name": "NeuroBridge API",
        "status": "running",
        "version": "0.1.0",
        "modes": ["chat", "agent"],
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "gateway_initialized": gateway is not None,
        "agent_initialized": pipeline is not None,
    }


@app.get("/providers")
def providers():
    if gateway is None:
        raise HTTPException(status_code=503, detail="Gateway not initialized")

    return {
        "providers": gateway.list_providers(),
        "default_provider": gateway.default_provider,
        "fallback_provider": gateway.fallback_provider,
    }


@app.post("/chat")
def chat(request: ChatRequest):
    if gateway is None:
        raise HTTPException(status_code=503, detail="Gateway not initialized")

    messages = list(request.history)
    messages.append({"role": "user", "content": request.message})

    try:
        response = multilingual_generate(
            gateway=gateway,
            messages=messages,
            preferred_language=request.preferred_language,
            system_prompt=(
                "You are NeuroBridge, a helpful caregiver-support AI. "
                "Be empathetic, clear, practical, and cautious. "
                "Do not diagnose, prescribe, or recommend changing medication. "
                "For emergencies, advise contacting local emergency services. "
                "Do not pretend to perform actions you have not performed. "
                + (memory_context(request.user_id) if request.user_id else "")
            ),
            provider=request.provider,
            temperature=0.4,
            max_tokens=1024,
        )

        return {
            "reply": extract_response_text(response),
            "provider": getattr(response, "provider", None),
            "metadata": getattr(response, "metadata", {}),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"LLM request failed: {str(exc)}",
        )


@app.post("/agent/run")
def run_agent(request: AgentRequest):
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        state = pipeline.run_goal(
            description=request.goal,
            priority=request.priority,
            success_criteria=request.success_criteria,
        )

        try:
            state_data = state.to_dict()
        except Exception:
            state_data = {
                "goal": getattr(state.goal, "description", request.goal),
                "status": str(getattr(state, "status", "unknown")),
                "completed": getattr(state, "is_completed", False),
                "iteration": getattr(state, "iteration", 0),
            }

        return {
            "goal": request.goal,
            "completed": getattr(state, "is_completed", False),
            "paused": getattr(state, "is_paused", False),
            "iteration": getattr(state, "iteration", 0),
            "state": state_data,
            "execution_mode": "simulation",
            "notice": "Prototype simulation mode. Real actions are not enabled by this endpoint.",
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Agent execution failed: {str(exc)}",
        )


@app.get("/agent/tools")
def list_tools():
    return {
        "tools": [],
        "notice": "Tool API registration is not connected yet.",
    }


@app.get("/agent/status")
def agent_status():
    return {
        "agent": "NeuroBridge Deep Agent",
        "initialized": pipeline is not None,
        "mode": "simulation",
    }
