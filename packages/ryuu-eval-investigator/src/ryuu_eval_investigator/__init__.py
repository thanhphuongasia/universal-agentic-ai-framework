"""ryuu-eval-investigator — generic investigation framework.

Layout:
    core/        — agent-agnostic models, protocols, persistence
    backends/    — optional LLM adapters (to be added per need)
    prompts/     — base prompt templates with domain-rule slots

Domain projects pick one backend + provide their own classification rules.
"""

from .core import (
    Confidence,
    Evidence,
    Finding,
    InputBundle,
    InvestigationStore,
    InvestigatorBackend,
    RootCauseReport,
    create_store,
)

__all__ = [
    "Confidence",
    "Evidence",
    "Finding",
    "InputBundle",
    "InvestigationStore",
    "InvestigatorBackend",
    "RootCauseReport",
    "create_store",
]
