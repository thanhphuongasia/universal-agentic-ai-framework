"""End-to-end smoke test for Oracle Ground Truth Studio backend.

Hits a running dev_server (default http://localhost:8001) and exercises:
  1. GET  /oracle-review/providers
  2. POST /oracle-review/meta-generate     — production prompt → oracle prompt
  3. POST /oracle-review/run-with-prompt    — oracle prompt → cells

Real LLM call — costs a few cents. Defaults to provider=openai + gpt-4o-mini
to keep cost low; override with --provider / --model.

Usage:
    # default Anki demo prompt
    python3 scripts/oracle_studio_smoke.py

    # real prod-grade-code-analysis CRUD matrix prompt
    python3 scripts/oracle_studio_smoke.py \\
        --prompt-file "../prod-grade-code-analysis/src/prompts/chat/agents/crud_matrix_column.java_springboot.v1.yml" \\
        --project-name prod-code-analysis \\
        --domain-hint "Java Spring Boot CRUD matrix"

    # different provider/model
    python3 scripts/oracle_studio_smoke.py --provider anthropic --model claude-opus-4-7
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib import error, request


def _post(url: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = request.Request(
        url, data=data, headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except error.HTTPError as exc:
        return {"_status": exc.code, "_body": exc.read().decode()}


def _get(url: str) -> dict:
    try:
        with request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())
    except error.HTTPError as exc:
        return {"_status": exc.code, "_body": exc.read().decode()}


_DEFAULT_PROMPT = (
    "You generate Anki flashcards from text. Output JSON: "
    "{front, back, tags}. Rule: if input has >20 words, split."
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8001/api/eval")
    ap.add_argument("--provider", default="openai")
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument(
        "--prompt-file",
        type=Path,
        default=None,
        help="path to production prompt file (txt/yml/md). "
             "Default: built-in Anki demo prompt.",
    )
    ap.add_argument("--project-name", default="anki_smoke")
    ap.add_argument("--domain-hint", default="Spaced repetition flashcards")
    args = ap.parse_args()

    if args.prompt_file:
        if not args.prompt_file.exists():
            print(f"! prompt file not found: {args.prompt_file}", file=sys.stderr)
            return 1
        production_prompt = args.prompt_file.read_text(encoding="utf-8")
        print(f"production prompt: {args.prompt_file}  ({len(production_prompt)} chars)")
    else:
        production_prompt = _DEFAULT_PROMPT
        print(f"production prompt: (default Anki demo, {len(production_prompt)} chars)")

    print(f"[1/3] GET {args.base}/oracle-review/providers")
    providers = _get(f"{args.base}/oracle-review/providers")
    print(f"      → {providers}")
    if args.provider not in providers.get("providers", []):
        print(
            f"      ! {args.provider!r} not registered "
            f"(available: {providers.get('providers')})",
            file=sys.stderr,
        )
        return 1

    print(f"\n[2/3] POST /meta-generate  (provider={args.provider}, model={args.model})")
    meta = _post(f"{args.base}/oracle-review/meta-generate", {
        "production_prompt": production_prompt,
        "project_name": args.project_name,
        "domain_hint": args.domain_hint,
        "provider": args.provider,
        "model": args.model,
    })
    if "_status" in meta:
        print(f"      ! HTTP {meta['_status']}: {meta['_body']}", file=sys.stderr)
        return 1
    print(f"      → meta_prompt_version={meta.get('meta_prompt_version')}")
    print(f"      → oracle_prompt ({len(meta.get('oracle_prompt', ''))} chars):")
    print("        " + (meta.get("oracle_prompt", "")[:300] + "…").replace("\n", "\n        "))

    print(f"\n[3/3] POST /run-with-prompt  (handcrafted CRUD-matrix prompt)")
    handcrafted = (
        "system: |\n"
        "  You are a Java Spring expert acting as oracle.\n"
        "  Decide CRUD op per (entity, field) for the given HTTP route.\n"
        "  Output JSON: {entity: {field: {op, confidence, why}}}\n"
        "\n"
        "user_template: |\n"
        "  Route context:\n"
        "  {{ input_json }}\n"
        "\n"
        "  Determine CRUD ops. JSON only.\n"
    )
    run = _post(f"{args.base}/oracle-review/run-with-prompt", {
        "oracle_prompt": handcrafted,
        "input_data": {
            "route": {"endpoint": "/users/{id}", "http_method": "GET"},
            "entities": [{
                "short_name": "User",
                "fields": [
                    {"name": "id", "annotations": ["@Id", "@GeneratedValue"]},
                    {"name": "email"},
                    {"name": "name"},
                ],
            }],
        },
        "provider": args.provider,
        "model": args.model,
    })
    if "_status" in run:
        print(f"      ! HTTP {run['_status']}: {run['_body']}", file=sys.stderr)
        return 1
    print(f"      → latency={run.get('latency_ms', 0):.0f}ms  "
          f"cost=${run.get('cost_usd', 0):.4f}  "
          f"tokens={run.get('input_tokens')}/{run.get('output_tokens')}")
    cells = run.get("cells") or {}
    if not cells:
        print(f"      ! cells empty (parse_error: {run.get('parse_error')})", file=sys.stderr)
        return 1
    for entity, fields in cells.items():
        print(f"      → {entity}:")
        for field, cell in fields.items():
            print(f"          {field}: op={cell.get('op')} "
                  f"conf={cell.get('confidence')}")

    print("\n✓ All 3 endpoints responded successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
