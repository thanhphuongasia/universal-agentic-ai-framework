# code_analysis_investigator

Domain-specific investigator plugin for **CRUD-matrix ingestion bugs** (Spring + Neo4j pipeline).

Uses generic core `ryuu-eval-investigator` + domain rules in `rules.yml`.

## Status

Skeleton only:
- `rules.yml` — 7 issue types + investigation order
- `input_adapter.py` — eval output → InputBundle
- `run_local.py` — CLI wiring (backend not yet implemented)

## Why here, not in prod-grade-code-analysis?

- Debug tool, not production code
- Don't want it consuming server resources
- Local runs use Claude Max subscription (no API cost)
- Triggered manually or by eval framework, not by FastAPI request flow

## Next session

1. Implement `agent_sdk_backend.py` in `packages/ryuu-eval-investigator/backends/`
2. Wire it into `run_local.py`
3. Move `agent-sdk-investigator/` and `hon-agent-sdk/` content from prod-grade-code-analysis here
