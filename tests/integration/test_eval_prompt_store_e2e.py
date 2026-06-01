"""End-to-end seed + flow: prompt lifecycle → resolve live prompt → score output.

Self-contained — uses the in-memory stores so it runs without a database. It
exercises the two framework abstractions added for the eval/prompt store
(``ryuu_prompts.IPromptStore`` lifecycle + ``ryuu_eval_scorers.build_scorers``)
together, the way the eval router will wire them.

Run with narration:
    pytest tests/integration/test_eval_prompt_store_e2e.py -s
"""

from __future__ import annotations

from pathlib import Path

from ryuu_eval_core.models import EvalCase
from ryuu_eval_scorers import build_scorers
from ryuu_prompts import (
    InMemoryPromptStore,
    PromptConfig,
    PromptRegistry,
    PromptStatus,
    PromptTemplate,
    PromptVersion,
)

SUITE = "crud_matrix"


def _crud_prompt(version: str, system: str) -> PromptConfig:
    """A prompt config for the CRUD-matrix suite."""
    return PromptConfig(
        version=version,
        description=f"CRUD matrix extractor {version}",
        model="claude-sonnet-4-6",
        temperature=0.0,
        max_tokens=2048,
        prompts={"extract": PromptTemplate(system=system, user="{query}")},
    )


async def _seed(store: InMemoryPromptStore) -> None:
    """Seed the suite with two prompt versions; v2 is the improved one."""
    await store.save(PromptVersion(
        id="pv_001", suite_id=SUITE, version="v1", created_at=1.0,
        config=_crud_prompt("v1", "Extract the CRUD matrix. Return JSON."),
    ))
    await store.save(PromptVersion(
        id="pv_002", suite_id=SUITE, version="v2", created_at=2.0,
        config=_crud_prompt(
            "v2",
            "Extract the CRUD matrix per entity. Use only C/R/U/D. "
            "Return strict JSON, no prose, no GraphQL.",
        ),
    ))


async def test_end_to_end_seed_lifecycle_and_scoring():
    store = InMemoryPromptStore()
    await _seed(store)

    # --- 1. lifecycle: both drafts, none live yet --------------------------
    versions = await store.list_versions(SUITE)
    assert [v.version for v in versions] == ["v1", "v2"]
    assert await store.get_active(SUITE) is None

    # --- 2. promote v2 through staging → live ------------------------------
    await store.set_status(SUITE, "v2", PromptStatus.STAGING)
    promoted = await store.promote(SUITE, "v2", by="phuong")
    assert promoted.promoted_by == "phuong"

    active = await store.get_active(SUITE)
    assert active is not None and active.version == "v2"

    # --- 3. resolve the live prompt into a ready-to-send request -----------
    registry = PromptRegistry(prompts_root=Path("."))  # roots only used by load(); we render directly
    request = registry.build_request(active.config, "extract", query="Map orders API")
    assert request.model == "claude-sonnet-4-6"
    assert any("CRUD matrix" in m.content for m in request.messages)

    # --- 4. build scorers from a JSONB-style scoring spec ------------------
    scoring_spec = {
        "scorers": [
            {"type": "contains", "config": {"required": ["CREATE", "READ"]}},
        ],
        "combine": "and",
        "forbidden": ["GraphQL"],   # hard gate, always AND-ed
    }
    scorers = build_scorers(scoring_spec)
    assert len(scorers) == 2  # [Composite(main), Constraint(forbidden)]

    # --- 5. score a model output against the spec --------------------------
    case = EvalCase(case_id="tc_001", input="Map orders API", expected="CREATE READ")

    good_output = "Orders: CREATE, READ on /orders"
    good = [await s.score(case, good_output) for s in scorers]
    assert all(r.passed for r in good)

    bad_output = "Orders exposed via GraphQL: CREATE, READ"
    bad = [await s.score(case, bad_output) for s in scorers]
    assert not all(r.passed for r in bad)  # forbidden 'GraphQL' trips the gate
