"""Seed the eval/prompt-store schema with one realistic suite.

Populates a freshly-migrated database (docs/eval-prompt-store-schema.sql) so the
end-to-end shape is visible: a system → domain → suite, two prompt versions (v2
promoted live via suites.active_prompt_version_id), one template, two test cases
whose scoring column is a build_scorers() spec.

Idempotent — re-running upserts, never duplicates.

Run:
    DATABASE_URL=postgresql://macbook@localhost/ryuu_eval python scripts/seed_eval.py
"""

from __future__ import annotations

import asyncio
import json
import os

from ryuu_prompts import PromptConfig, PromptStatus, PromptTemplate, PromptVersion
from ryuu_storage_postgres import PostgresPromptStore, close_all
from ryuu_storage_postgres._pool import get_pool

DSN = os.environ["DATABASE_URL"]

SYSTEM_ID = "code-analysis"
DOMAIN_ID = "diagrams"
SUITE_ID = "crud_matrix"


def _prompt(version: str, system: str) -> PromptConfig:
    return PromptConfig(
        version=version,
        description=f"CRUD matrix extractor {version}",
        model="claude-sonnet-4-6",
        temperature=0.0,
        max_tokens=2048,
        prompts={"extract": PromptTemplate(system=system, user="{query}")},
    )


async def seed() -> None:
    pool = await get_pool(DSN)
    store = PostgresPromptStore(dsn=DSN)

    # 1. system → domain (parents of the suite)
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO systems(id, name, description) VALUES($1, $2, $3)"
            " ON CONFLICT (id) DO NOTHING",
            SYSTEM_ID, "Code Analysis", "Static analysis evals",
        )
        await conn.execute(
            "INSERT INTO domains(id, system_id, name) VALUES($1, $2, $3)"
            " ON CONFLICT (id) DO NOTHING",
            DOMAIN_ID, SYSTEM_ID, "Diagrams",
        )

    # 2. suite
    await store.ensure_suite(SUITE_ID, domain_id=DOMAIN_ID, name="CRUD Matrix")

    # 3. two prompt versions; v2 is the improved one
    await store.save(PromptVersion(
        id="pv_crud_v1", suite_id=SUITE_ID, version="v1", created_at=1.0,
        config=_prompt("v1", "Extract the CRUD matrix. Return JSON."),
    ))
    await store.save(PromptVersion(
        id="pv_crud_v2", suite_id=SUITE_ID, version="v2", created_at=2.0,
        config=_prompt(
            "v2",
            "Extract the CRUD matrix per entity. Use only C/R/U/D. "
            "Return strict JSON, no prose, no GraphQL.",
        ),
    ))

    # 4. lifecycle: v2 → staging → promote (sets suites.active_prompt_version_id)
    await store.set_status(SUITE_ID, "v2", PromptStatus.STAGING)
    await store.promote(SUITE_ID, "v2", by="seed-script")

    # 5. one template + two test cases (scoring = build_scorers spec)
    input_schema = {"type": "object", "properties": {"code": {"type": "string"}}}
    expected_schema = {"type": "object"}
    scoring_happy = {
        "scorers": [{"type": "contains", "config": {"required": ["CREATE", "READ"]}}],
        "combine": "and",
        "forbidden": ["GraphQL"],
    }
    scoring_strict = {
        "scorers": [{"type": "contains", "config": {"required": ["CREATE", "READ", "UPDATE", "DELETE"]}}],
        "combine": "and",
    }
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO templates(id, suite_id, title, description, input_schema, expected_schema, tags)"
            " VALUES($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb)"
            " ON CONFLICT (id) DO NOTHING",
            "tpl_crud", SUITE_ID, "CRUD extraction", "Extract CRUD ops per entity",
            json.dumps(input_schema), json.dumps(expected_schema), json.dumps(["crud", "diagrams"]),
        )
        for tc_id, name, scoring in [
            ("tc_orders_happy", "orders happy path", scoring_happy),
            ("tc_users_full", "users full CRUD", scoring_strict),
        ]:
            await conn.execute(
                "INSERT INTO test_cases(id, suite_id, template_id, name, input, expected, scoring, metadata)"
                " VALUES($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, '{}'::jsonb)"
                " ON CONFLICT (suite_id, id) DO UPDATE SET scoring = EXCLUDED.scoring",
                tc_id, SUITE_ID, "tpl_crud", name,
                json.dumps({"code": "// ..."}), json.dumps({}), json.dumps(scoring),
            )

    # 6. report
    async with pool.acquire() as conn:
        counts = {}
        for t in ["systems", "domains", "suites", "prompt_versions", "templates", "test_cases"]:
            counts[t] = await conn.fetchval(f"SELECT count(*) FROM {t}")
        active = await conn.fetchval(
            "SELECT active_prompt_version_id FROM suites WHERE id = $1", SUITE_ID
        )
    print("Seeded row counts:", counts)
    print(f"suites.active_prompt_version_id for {SUITE_ID!r} =", active)

    await close_all()


if __name__ == "__main__":
    asyncio.run(seed())
