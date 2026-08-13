"""Seed demo eval data into a freshly-migrated database.

Creates a code-analysis system → diagrams domain → three demo suites
(crud_matrix_llm, class_diagram, sequence_diagram), each with two prompt
versions (v2 promoted live) and a few test cases whose `scoring` column is a
build_scorers() spec. Idempotent — re-running upserts, never duplicates.

Run:
    DATABASE_URL=postgresql://macbook@localhost/ryuu_eval python scripts/seed_eval.py
"""

from __future__ import annotations

import asyncio
import os

from ryuu_prompts import PromptConfig, PromptStatus, PromptTemplate, PromptVersion
from ryuu_storage_postgres import (
    PostgresPromptStore,
    PostgresSuiteStore,
    PostgresTestCaseStore,
    close_all,
)
from ryuu_storage_postgres._pool import get_pool
from ryuu_eval_core.models import EvalCase

DSN = os.environ["DATABASE_URL"]
SYSTEM_ID = "code-analysis"
DOMAIN_ID = "diagrams"


def _prompt(version: str, system: str) -> PromptConfig:
    return PromptConfig(
        version=version, description=f"{version}", model="claude-sonnet-4-6",
        temperature=0.0, max_tokens=2048,
        prompts={"system": PromptTemplate(system=system, user="{query}")},
    )


# ── Production prompts (the thing under test) ────────────────────────────────
# v1 of each suite is a naive one-liner kept as a weak baseline so the demo
# shows a real before/after contrast. v2 is a proper production prompt and is
# the one promoted live — runs resolve the ACTIVE version's system prompt, so
# this is what actually drives output quality.

CRUD_PROD_V2 = """\
You are a CRUD matrix classifier for backend code. Given the source for an HTTP
route/controller and its data entities, determine the database-column-level CRUD
operation the route performs on each (entity, field) pair.

OUTPUT — strict JSON only, no prose, no markdown fences:
{
  "cells": {
    "<EntityName>": {
      "<fieldName>": { "op": "one or more of C R U D", "confidence": "low|medium|high",
                       "why": "1-2 sentence justification" }
    }
  }
}

RULES:
- Copy entity and field names EXACTLY as they appear in the input — never
  rename, re-case, or convert between camelCase and snake_case. Verbatim only.
- Never invent an entity, field, or column that is not present in the input.
- Op letters in CRUD order: C=insert, R=read/select, U=update, D=delete
  (combine when several apply, e.g. "CR", "RU").
- Omit a field entirely if the route does not touch it.
- Emit the JSON object and nothing else."""

CLASS_PROD_V2 = """\
You are a UML class-diagram extractor. From the given source, produce the
classes, their fields and methods, and the relationships between them.

OUTPUT — strict JSON only, no prose, no markdown fences:
{
  "classes": [ { "name": "<ClassName>", "fields": ["<name: type>"], "methods": ["<name()>"] } ],
  "relationships": [ { "from": "<Class>", "to": "<Class>", "kind": "extends|implements|association" } ]
}

RULES:
- Use class/field/method names EXACTLY as written in the source — verbatim.
- Capture inheritance (extends), interface realization (implements), and
  field-typed associations. Do not invent members not present in the source.
- Emit the JSON object and nothing else."""

SEQ_PROD_V2 = """\
You are a UML sequence-diagram extractor. From the given source, list the
participants and the ordered messages exchanged between them.

OUTPUT — strict JSON only, no prose, no markdown fences:
{
  "participants": ["<Participant>"],
  "messages": [ { "from": "<Participant>", "to": "<Participant>", "method": "<method>" } ]
}

RULES:
- Preserve the exact call order in which messages occur.
- Use participant and method names EXACTLY as written in the source — verbatim.
- Do not invent participants or calls not present in the source.
- Emit the JSON object and nothing else."""


# Demo suites: each → (title, [(version, system_prompt)], [(case_id, name, input, expected, scoring)])
SUITES: list[dict] = [
    {
        "id": "crud_matrix_llm", "title": "CRUD Matrix",
        "versions": [
            ("v1", "Extract the CRUD matrix. Return JSON."),
            ("v2", CRUD_PROD_V2),
        ],
        "cases": [
            ("orders_happy", "Orders CRUD", {"code": "class OrderController {...}"},
             {"Order": "CR"},
             {"scorers": [{"type": "contains", "config": {"required": ["CREATE", "READ"]}}],
              "combine": "and", "forbidden": ["GraphQL"]}),
            ("users_full", "Users full CRUD", {"code": "class UserController {...}"},
             {"User": "CRUD"},
             {"scorers": [{"type": "contains",
              "config": {"required": ["CREATE", "READ", "UPDATE", "DELETE"]}}]}),
        ],
    },
    {
        "id": "class_diagram", "title": "Class Diagram",
        "versions": [
            ("v1", "Extract a UML class diagram from the code. Return JSON."),
            ("v2", CLASS_PROD_V2),
        ],
        "cases": [
            ("order_model", "Order aggregate", {"code": "class Order extends Base { Item[] items; }"},
             {"classes": ["Order", "Item"], "relationships": ["Order->Item"]},
             {"scorers": [{"type": "contains", "config": {"required": ["Order", "Item"]}}],
              "combine": "and"}),
            ("inheritance", "Inheritance chain", {"code": "class Admin extends User implements Auditable {}"},
             {"classes": ["Admin", "User", "Auditable"]},
             {"scorers": [{"type": "contains",
              "config": {"required": ["Admin", "User", "extends"]}}]}),
        ],
    },
    {
        "id": "sequence_diagram", "title": "Sequence Diagram",
        "versions": [
            ("v1", "Extract a UML sequence diagram from the code. Return JSON."),
            ("v2", SEQ_PROD_V2),
        ],
        "cases": [
            ("checkout_flow", "Checkout flow",
             {"code": "Controller.checkout() -> Service.pay() -> Gateway.charge()"},
             {"participants": ["Controller", "Service", "Gateway"],
              "messages": ["Controller->Service:pay", "Service->Gateway:charge"]},
             {"scorers": [{"type": "contains",
              "config": {"required": ["Controller", "Service", "Gateway"]}}],
              "combine": "and"}),
        ],
    },
]


async def seed() -> None:
    pool = await get_pool(DSN)
    prompts = PostgresPromptStore(dsn=DSN)
    suites = PostgresSuiteStore(dsn=DSN)
    cases = PostgresTestCaseStore(dsn=DSN)

    # system → domain (parents of every suite)
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

    for spec in SUITES:
        sid = spec["id"]
        await suites.create_suite(sid, title=spec["title"], domain_id=DOMAIN_ID)
        for ver, system in spec["versions"]:
            await prompts.save(PromptVersion(
                id=f"{sid}-{ver}", suite_id=sid, version=ver, config=_prompt(ver, system),
            ))
        await prompts.set_status(sid, "v2", PromptStatus.STAGING)
        await prompts.promote(sid, "v2", by="seed-script")
        for cid, name, inp, exp, scoring in spec["cases"]:
            await cases.save_case(
                sid, EvalCase(case_id=cid, input=inp, expected=exp, metadata={"name": name}),
                scoring=scoring,
            )

    # report
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT s.id, s.active_prompt_version_id,"
            "  (SELECT count(*) FROM prompt_versions p WHERE p.suite_id = s.id) AS versions,"
            "  (SELECT count(*) FROM test_cases t WHERE t.suite_id = s.id) AS cases"
            " FROM suites s ORDER BY s.id"
        )
    print("Seeded suites:")
    for r in rows:
        print(f"  {r['id']:<18} versions={r['versions']} cases={r['cases']} "
              f"active={r['active_prompt_version_id']}")
    await close_all()


if __name__ == "__main__":
    asyncio.run(seed())
