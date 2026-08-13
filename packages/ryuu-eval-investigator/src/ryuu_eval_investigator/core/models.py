"""Generic data models for investigation.

Agent-agnostic. Does NOT reference any LLM SDK.
Domain-specific issue types are NOT defined here — projects extend
via `issue_type: str` (free-form). Use string literals or your own Enum
in the domain plugin.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class InputBundle(BaseModel):
    """One investigation input. Domain-specific payload goes in `payload`."""

    case_id: str
    target_id: str                              # e.g. route_id, query_id — opaque to core
    payload: dict[str, Any] = Field(default_factory=dict)
    diff: dict[str, Any] = Field(default_factory=dict)
    repo_path: str
    project_id: str = ""


class Evidence(BaseModel):
    source: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)
    context_gap: str = ""


class Finding(BaseModel):
    """One classified issue.

    `issue_type` is free-form string — domain plugins define their own
    taxonomy (e.g. "REASONING_ERROR", "MISSING_CALLS_EDGE" for CRUD matrix;
    different buckets for other domains).
    """

    entity: str
    field: str
    issue_type: str
    confidence: Confidence
    evidence: Evidence
    root_cause: str
    suggested_fix: str


class RootCauseReport(BaseModel):
    target_id: str
    findings: list[Finding] = Field(default_factory=list)
    summary: str = ""
    tool_calls_used: int = 0
    cost_usd: float = 0.0
