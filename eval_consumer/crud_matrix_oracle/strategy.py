"""CrudMatrixOracleStrategy — IOracleStrategy implementation for CRUD matrix domain."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from ryuu_eval_oracle import ReviewSchema
from ryuu_providers_core import CompletionRequest, ILLMProvider, Message

from .normalizer import normalize_op

_PROMPT_DIR = Path(__file__).parent / "prompts"
PROMPT_VERSION = "crud_matrix_oracle.v1"


def _load_prompt(framework: str) -> dict[str, Any]:
    path = _PROMPT_DIR / f"{framework}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Oracle prompt not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _extract_valid_fields(route_context: dict[str, Any]) -> dict[str, list[str]]:
    valid: dict[str, list[str]] = {}
    for ent in route_context.get("entities", []):
        short_name = ent.get("short_name") or ent.get("fqn", "").split(".")[-1]
        fields = [
            f.get("db_column") or f.get("name", "")
            for f in ent.get("fields", [])
            if f.get("db_column") or f.get("name")
        ]
        valid[short_name] = fields
    return valid


class CrudMatrixOracleStrategy:
    """Oracle strategy for CRUD matrix extraction from Java/Spring route contexts.

    Implements IOracleStrategy[dict, dict]:
      - InputT  = full case YAML dict (has ``case_id`` + ``input`` route_context)
      - CandidateT = {cells: {...}, valid_fields: {...}, framework: str}
    """

    prompt_version: str = PROMPT_VERSION

    def __init__(
        self,
        provider: ILLMProvider,
        *,
        framework: str = "java_spring",
        model: str | None = None,
    ) -> None:
        """Build the strategy.

        Args:
            provider: shared ILLMProvider — created once by the caller (no
                      lazy import / per-call instantiation).
            framework: prompt YAML key (e.g. "java_spring").
            model: optional override; falls back to the value in the prompt
                   YAML (e.g. "claude-opus-4-7").
        """
        self._provider = provider
        self._framework = framework
        self._prompt_cfg = _load_prompt(framework)
        self._model = model or self._prompt_cfg.get("model", "claude-opus-4-7")

    def review_schema(self) -> ReviewSchema:
        return ReviewSchema(
            kind="table",
            columns=["ENTITY", "FIELD", "OP", "CONFIDENCE"],
            actions=["approve", "fix", "remove"],
            meta={
                "domain": "crud_matrix",
                "framework": self._framework,
                # Oracle generation provenance — surfaced read-only in the UI so
                # reviewers know which oracle prompt / default model produced cells.
                "prompt_version": self.prompt_version,
                "default_model": self._model,
            },
        )

    async def generate_candidate(
        self,
        input: dict[str, Any],
        existing_output: Any | None = None,
    ) -> dict[str, Any]:
        """Generate oracle ground truth.

        Args:
            input: full case YAML dict (``input`` sub-key holds route_context).
            existing_output: ignored for now (Case B only — no production target yet).
        """
        route_context: dict[str, Any] = input.get("input", input)
        cells = await self._call_oracle(route_context)
        valid_fields = _extract_valid_fields(route_context)
        return {
            "cells": cells,
            "valid_fields": valid_fields,
            "framework": self._framework,
        }

    def render_prompt(self, input_data: dict[str, Any]) -> dict[str, str]:
        """Return {"system": ..., "user": ...} with route_context injected."""
        route_context: dict[str, Any] = input_data.get("input", input_data)
        cfg = self._prompt_cfg
        user_text = cfg["user_template"].replace(
            "{{ route_context_json }}",
            json.dumps(route_context, ensure_ascii=False, indent=2),
        )
        return {"system": cfg["system"], "user": user_text}

    async def _call_oracle(self, route_context: dict[str, Any]) -> dict[str, Any]:
        cfg = self._prompt_cfg
        user_text = cfg["user_template"].replace(
            "{{ route_context_json }}",
            json.dumps(route_context, ensure_ascii=False, indent=2),
        )
        req = CompletionRequest(
            messages=[Message(role="user", content=user_text)],
            model=self._model,
            system=cfg["system"],
            temperature=0.0,
            max_tokens=4096,
        )
        resp = await self._provider.complete(req)
        raw = resp.content.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"[oracle] JSON parse error: {e}\nRaw:\n{raw[:500]}", file=sys.stderr)
            raise

        return {
            entity: {
                field_name: {
                    "op": normalize_op(cell_data.get("op", "")),
                    "confidence": cell_data.get("confidence", "high"),
                    "oracle_why": cell_data.get("why", ""),
                }
                for field_name, cell_data in fields.items()
            }
            for entity, fields in parsed.get("cells", {}).items()
        }
