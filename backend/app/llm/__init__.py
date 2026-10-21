"""Pacote da camada de IA e templates (SPEC §8 e §9)."""

from .client import (
    LLMError,
    OllamaAPIError,
    OllamaConnectionError,
    OllamaTimeoutError,
    chat,
    check_ollama_health,
)
from .facts_builder import Anonymizer, build_facts
from .schemas import (
    AnalysisSection,
    Evidence,
    FactsResult,
    Finding,
    Recommendation,
)
from .templates import (
    SIGNAL_TEMPLATES,
    render_signal_message,
    render_signal_title,
)

from .validator import (
    ValidationResult,
    format_retry_feedback,
    validate_analysis_section,
)

__all__ = [
    "LLMError",
    "OllamaAPIError",
    "OllamaConnectionError",
    "OllamaTimeoutError",
    "chat",
    "check_ollama_health",
    "SIGNAL_TEMPLATES",
    "render_signal_title",
    "render_signal_message",
    "build_facts",
    "Anonymizer",
    "AnalysisSection",
    "Evidence",
    "Finding",
    "Recommendation",
    "FactsResult",
    "validate_analysis_section",
    "format_retry_feedback",
    "ValidationResult",
]
