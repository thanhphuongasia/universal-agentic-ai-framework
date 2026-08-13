# ryuu-eval-investigator

Generic investigation framework for eval failures. Agent-agnostic core, pluggable LLM backends.

## Status

Skeleton only — Phase 1 (models + protocols + store) committed. Backends and prompts come next.

## Layout

```
core/        ← agent-agnostic. NO LLM SDK imports.
  models.py  ← InputBundle, Finding, RootCauseReport
  backend.py ← InvestigatorBackend Protocol
  store.py   ← InvestigationStore Protocol + create_store() factory

backends/    ← (TBD) per-LLM adapters: agent_sdk, anthropic, ryuu
prompts/     ← (TBD) base templates with {domain_rules} slot
```

## Usage (planned)

```python
from ryuu_eval_investigator import InputBundle, create_store
from ryuu_eval_investigator.backends.agent_sdk import AgentSdkBackend  # TBD

backend = AgentSdkBackend(model="claude-sonnet-4-6")
store = create_store()  # reads INVESTIGATION_DB_BACKEND env

report = await backend.investigate(bundle, system_prompt=domain_prompt)
store.save(case_id, suite_id, report)
```

## Domain plugins

Domain-specific classification rules live in `uaaf-framework/eval_consumer/<your_domain>_investigator/`.
See `eval_consumer/code_analysis_investigator/` for the CRUD-matrix / Spring + Neo4j example.
