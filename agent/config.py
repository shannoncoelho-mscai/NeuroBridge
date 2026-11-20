from dataclasses import dataclass, field
from typing import Optional


# =========================================================
# NeuroBridge Deep Agent Configuration
# =========================================================

APP_NAME = "NeuroBridge"
APP_VERSION = "0.1.0"


# -------------------------
# Operating modes
# -------------------------

CHATBOT_MODE = "chatbot"
AGENT_MODE = "agent"


# -------------------------
# LLM providers
# -------------------------

SUPPORTED_PROVIDERS = [
    "gemini",
    "groq",
    "local",
]


@dataclass
class LLMConfig:
    provider: str = "gemini"
    model: Optional[str] = None
    temperature: float = 0.3
    max_tokens: int = 1024
    timeout_seconds: int = 60
    fallback_provider: Optional[str] = "groq"


# -------------------------
# Language configuration
# -------------------------

SUPPORTED_LANGUAGES = {
    "en": "English",
    "hi": "Hindi",
    "kok": "Konkani",
    "mr": "Marathi",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "ml": "Malayalam",
    "kn": "Kannada",
    "gu": "Gujarati",
    "pa": "Punjabi",
    "ur": "Urdu",
}


@dataclass
class LanguageConfig:
    default_language: str = "en"
    auto_detect: bool = True
    allow_language_switch: bool = True
    simple_language: bool = True
    bilingual_responses: bool = False
    preserve_medical_terms: bool = True
    translate_care_instructions: bool = True
    supported_languages: dict = field(
        default_factory=lambda: SUPPORTED_LANGUAGES.copy()
    )


# -------------------------
# Agent autonomy
# -------------------------

AUTONOMY_LEVELS = {
    0: "observe",
    1: "prepare",
    2: "execute_reversible_actions",
    3: "human_approval_required",
    4: "prohibited_autonomous_actions",
}


# -------------------------
# Execution limits
# -------------------------

@dataclass
class AgentConfig:
    max_iterations: int = 8
    max_tool_calls: int = 12
    max_retries: int = 2
    timeout_seconds: int = 180

    enable_planning: bool = True
    enable_replanning: bool = True
    enable_verification: bool = True

    enable_tool_execution: bool = True
    enable_memory: bool = True

    default_autonomy_level: int = 1


# -------------------------
# Safety settings
# -------------------------

@dataclass
class SafetyConfig:
    require_tool_permission: bool = True
    require_approval_for_external_actions: bool = True
    require_approval_for_sensitive_data_sharing: bool = True

    prohibit_autonomous_diagnosis: bool = True
    prohibit_medication_changes: bool = True
    prohibit_autonomous_emergency_decisions: bool = True

    enable_input_validation: bool = True
    enable_output_safety_checks: bool = True
    enable_audit_logging: bool = True


# -------------------------
# Memory settings
# -------------------------

@dataclass
class MemoryConfig:
    enabled: bool = True
    save_conversation_summaries: bool = True
    save_user_preferences: bool = True
    save_tasks: bool = True

    require_consent_for_sensitive_memory: bool = True
    allow_user_memory_review: bool = True
    allow_user_memory_deletion: bool = True


# -------------------------
# Main configuration
# -------------------------

@dataclass
class NeuroBridgeConfig:
    mode: str = CHATBOT_MODE

    llm: LLMConfig = field(default_factory=LLMConfig)
    language: LanguageConfig = field(default_factory=LanguageConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)


# Default application configuration
DEFAULT_CONFIG = NeuroBridgeConfig()
