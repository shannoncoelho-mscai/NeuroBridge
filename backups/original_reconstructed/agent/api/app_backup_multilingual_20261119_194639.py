from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent.pipeline import NeuroBridgePipeline

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


class AgentRequest(BaseModel):
    goal: str
    priority: str = "normal"
    success_criteria: List[str] = Field(default_factory=list)


class ProviderRequest(BaseModel):
    provider: str


def initialize(gateway_instance):
    global gateway, pipeline
    gateway = gateway_instance

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
        response = gateway.generate(
            messages=messages,
            system_prompt=(
                "You are NeuroBridge, a helpful caregiver-support AI. "
                "Be empathetic, clear, practical, and cautious. "
                "Do not diagnose, prescribe, or recommend changing medication. "
                "For emergencies, advise contacting local emergency services. "
                "Do not pretend to perform actions you have not performed."
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
