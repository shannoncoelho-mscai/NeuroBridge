from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional
from datetime import datetime, timezone
import uuid


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# =========================================================
# ENUMS
# =========================================================

class AgentMode(str, Enum):
    CHATBOT = "chatbot"
    AGENT = "agent"


class TaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PlanStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ToolStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
    NEEDS_APPROVAL = "needs_approval"


# =========================================================
# GOAL
# =========================================================

@dataclass
class AgentGoal:
    description: str
    goal_id: str = field(default_factory=lambda: generate_id("goal"))
    created_at: str = field(default_factory=utc_now)
    priority: str = "normal"
    deadline: Optional[str] = None
    success_criteria: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# =========================================================
# TASK
# =========================================================

@dataclass
class AgentTask:
    name: str
    description: str = ""
    task_id: str = field(default_factory=lambda: generate_id("task"))
    status: TaskStatus = TaskStatus.PENDING
    priority: str = "normal"

    dependencies: list[str] = field(default_factory=list)
    required_tool: Optional[str] = None
    required_skill: Optional[str] = None

    requires_approval: bool = False
    result: Any = None
    error: Optional[str] = None

    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    metadata: dict[str, Any] = field(default_factory=dict)


# =========================================================
# PLAN
# =========================================================

@dataclass
class AgentPlan:
    goal_id: str
    tasks: list[AgentTask] = field(default_factory=list)

    plan_id: str = field(default_factory=lambda: generate_id("plan"))
    status: PlanStatus = PlanStatus.DRAFT

    reasoning_summary: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    current_task_id: Optional[str] = None
    revision: int = 0

    metadata: dict[str, Any] = field(default_factory=dict)


# =========================================================
# TOOL CALL
# =========================================================

@dataclass
class ToolCall:
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    call_id: str = field(default_factory=lambda: generate_id("call"))
    requested_at: str = field(default_factory=utc_now)

    # Set by permission/safety checks before execution
    authorized: bool = False
    requires_approval: bool = False


@dataclass
class ToolResult:
    call_id: str
    tool_name: str
    status: ToolStatus

    result: Any = None
    error: Optional[str] = None

    started_at: Optional[str] = None
    completed_at: str = field(default_factory=utc_now)

    metadata: dict[str, Any] = field(default_factory=dict)


# =========================================================
# HUMAN APPROVAL
# =========================================================

@dataclass
class ApprovalRequest:
    action: str
    reason: str

    approval_id: str = field(default_factory=lambda: generate_id("approval"))
    status: ApprovalStatus = ApprovalStatus.PENDING

    requested_by: str = "neurobridge_agent"
    created_at: str = field(default_factory=utc_now)
    expires_at: Optional[str] = None
    reviewed_at: Optional[str] = None
    reviewed_by: Optional[str] = None

    action_details: dict[str, Any] = field(default_factory=dict)
    rejection_reason: Optional[str] = None


# =========================================================
# OBSERVATION
# =========================================================

@dataclass
class AgentObservation:
    source: str
    content: Any

    observation_id: str = field(default_factory=lambda: generate_id("obs"))
    observed_at: str = field(default_factory=utc_now)

    confidence: Optional[float] = None
    metadata: dict[str, Any] = field(default_factory=dict)


# =========================================================
# MESSAGE
# =========================================================

@dataclass
class AgentMessage:
    role: str
    content: str

    message_id: str = field(default_factory=lambda: generate_id("msg"))
    timestamp: str = field(default_factory=utc_now)

    language: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


# =========================================================
# AGENT EXECUTION STATE
# =========================================================

@dataclass
class AgentState:
    goal: AgentGoal
    mode: AgentMode = AgentMode.CHATBOT

    state_id: str = field(default_factory=lambda: generate_id("state"))

    plan: Optional[AgentPlan] = None

    messages: list[AgentMessage] = field(default_factory=list)
    observations: list[AgentObservation] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    approval_requests: list[ApprovalRequest] = field(default_factory=list)

    iteration: int = 0
    tool_call_count: int = 0

    is_running: bool = False
    is_paused: bool = False
    is_completed: bool = False

    preferred_language: str = "en"
    detected_language: Optional[str] = None

    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def update_timestamp(self):
        self.updated_at = utc_now()

    def add_message(self, role: str, content: str, language: Optional[str] = None):
        message = AgentMessage(
            role=role,
            content=content,
            language=language,
        )
        self.messages.append(message)
        self.update_timestamp()
        return message

    def add_observation(
        self,
        source: str,
        content: Any,
        confidence: Optional[float] = None,
    ):
        observation = AgentObservation(
            source=source,
            content=content,
            confidence=confidence,
        )
        self.observations.append(observation)
        self.update_timestamp()
        return observation

    def to_dict(self):
        return asdict(self)
