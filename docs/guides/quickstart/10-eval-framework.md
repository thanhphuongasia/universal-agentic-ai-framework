# Eval Framework — Templates, Streaming, Optimization Loop

← [Quickstart Index](README.md) | [Prompt Optimizer (07)](07-prompt-optimizer.md)

> Build production eval UIs in minutes. Framework supplies templates + form generation + SSE streaming + refine logging + optimization loop. Any project adds 5 small files for full integration.

---

## TL;DR

```python
# In your project:
from ryuu_eval import EvalCaseTemplate, EvalRunner
from ryuu_eval.http import build_eval_router
from ryuu.refine_logger import RefineLogger

# 1. Define a template (input/expected JSON schemas)
INTENT_TEMPLATE = EvalCaseTemplate(
    template_id="intent_v1", suite_id="intent_classifier", title="Intent",
    input_schema={"properties": {"message": {"type": "string"}}},
    expected_schema={"properties": {"intent": {"type": "string"}}},
    examples=[{"input": {...}, "expected": {...}}],
)

# 2. Build a runner factory (project supplies target + scorers)
def my_runner_factory(suite_id, log_path):
    return EvalRunner(
        suite_id=suite_id,
        target=MyProjectTarget(),
        scorers=[MyScorer()],
        refine_logger=RefineLogger(log_path),
    )

# 3. Mount HTTP router (11 routes — UI, streaming, history, optimize)
app.include_router(build_eval_router(
    runner_factory=my_runner_factory,
    template_registry={INTENT_TEMPLATE.template_id: INTENT_TEMPLATE},
), prefix="/api/eval")
```

UI gets: template gallery, form editor (auto-generated từ JSON Schema), live SSE progress, diff view, refine history panel, optimize button.

---

## 1. Architecture — What's Where

```
┌─ FRAMEWORK ─────────────────────────────────────────────────┐
│ ryuu_eval_core:                                              │
│   EvalCase, EvalCaseTemplate, CaseResult, SuiteResult         │
│   ProgressEvent (8 types: suite_start, case_start, ...)       │
│   EvalRunner.run()          sync — returns SuiteResult         │
│   EvalRunner.stream()       async iter — yields ProgressEvent  │
│   FixtureLoader              YAML + !py escape hatch + JSON    │
│   Protocols: EvalTarget, Scorer                                │
│                                                              │
│ ryuu_eval.http:                                              │
│   build_eval_router(runner_factory, template_registry)        │
│   → 11 endpoints (templates, cases, run, stream, refine, opt) │
│                                                              │
│ ryuu.refine_logger:                                          │
│   RefineEvent, RefineLogger — persistent JSONL training data  │
│                                                              │
│ ryuu.prompt_optimizer:                                       │
│   PromptOptimizer + delimiter_variant_generator               │
└──────────────────────────────────────────────────────────────┘

┌─ PROJECT (5 files) ─────────────────────────────────────────┐
│ eval/templates.py        EvalCaseTemplate instances           │
│ eval/scorers.py          Scorer impls (domain-specific score) │
│ eval/targets.py          EvalTarget impl (wraps workflow)     │
│ eval/runner.py           build_runner factory                  │
│ api/app.py               app.include_router(build_eval_router) │
└──────────────────────────────────────────────────────────────┘

Reuse: ~80% framework / ~20% project per new domain.
```

---

## 2. EvalCaseTemplate — Form Schema for UI

Multiple templates per suite supported (e.g. happy_path, edge_case, regression):

```python
from ryuu_eval import EvalCaseTemplate

HAPPY_PATH = EvalCaseTemplate(
    template_id="crud_happy_v1",
    suite_id="crud_matrix",
    title="CRUD Happy Path",
    description="Standard route + entity → expected CRUD ops",
    input_schema={
        "type": "object",
        "properties": {
            "route": {"type": "string", "examples": ["POST /orders"]},
            "entities": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "fields": {"type": "array"},
                },
            }},
        },
    },
    expected_schema={
        "type": "object",
        "properties": {
            "cells": {"type": "array", "items": {
                "type": "object",
                "properties": {"entity": "str", "column": "str", "op": "str"},
            }},
        },
    },
    examples=[
        {"input": {"route": "POST /orders", "entities": [...]},
         "expected": {"cells": [...]}},
    ],
    tags=["smoke", "happy"],
)
```

**UI behavior:**
- Browse template gallery, filter by tags
- Pick template → form auto-generated từ `input_schema`
- Pre-filled với first example (user edits as needed)
- Save → POST `/api/eval/templates/{tid}/cases` → persists as YAML

**JSON Schema → form library:** UI uses `@rjsf/core` (React) or equivalent. Framework only emits schema; client renders form.

---

## 3. Streaming EvalRunner

Two modes — sync (blocking) and streaming (SSE):

```python
runner = EvalRunner(suite_id="my_suite", target=t, scorers=[s])

# Sync — collect all results
result: SuiteResult = await runner.run(cases)

# Streaming — yields ProgressEvent for SSE / live UI
async for event in runner.stream(cases):
    print(event.type, event.payload)
```

**Event sequence:**
```
suite_start                  {suite_id, total_cases}
  case_start                 {case_id, index, total}
    [refine_done]            {refine_count, feedback_history, passed}   ← if Evaluator used
  case_done                  {case_id, passed, scores, latency_ms, cost_usd}
  ... per case
suite_done                   {pass_rate, passed_count, total_count}
```

---

## 4. RefineLogger — Capture Refine Cycles

When `EvalTarget` wraps `ryuu.Evaluator`, refine events auto-logged:

```python
from ryuu.refine_logger import RefineLogger
from ryuu.facades.evaluator import Evaluator

class MyTarget:
    def __init__(self):
        self._evaluator = Evaluator(
            generator=Agent(model="gpt-4o-mini", instructions="..."),
            verifier=my_verifier,
            max_refines=2,
        )

    def set_refine_logger(self, logger):
        self._evaluator.refine_logger = logger

    async def run(self, case):
        output = await self._evaluator.run(case.input)
        return CaseResult(case=case, output=output)

# Logger attached at runner level — propagates to target via duck-typed setter
runner = EvalRunner(
    suite_id="s", target=MyTarget(), scorers=[],
    refine_logger=RefineLogger(Path("artifacts/refine_history.jsonl")),
)
```

**Per-suite, rotated 30 days, gzip when archive** (Q5 default).

---

## 5. YAML Fixtures — Q4 = C (Python Escape Hatch)

Cases và templates persist as YAML. `!py "expr"` tag for computed values:

```yaml
# artifacts/eval/cases/intent_classifier/case_today_login.yml
case_id: today_login_attempt
input:
  message: "I logged in at 9am today"
expected:
  intent: "ACCOUNT_ACCESS"
  timestamp: !py "datetime.datetime.now().isoformat()"   # ← computed
metadata:
  template_id: intent_v1
```

**Safe sandbox:** Only `datetime` + safe builtins available (`int, float, str, list, dict, len, range, sum, min, max`). No `os`, no `subprocess`, no file IO.

Loader API:
```python
from ryuu_eval import FixtureLoader

# Load cases for a suite
cases = FixtureLoader.load("artifacts/eval/cases/intent_classifier/case_today_login.yml")

# Discover templates in a suite directory
templates = FixtureLoader.list_templates("artifacts/eval/cases/intent_classifier")
```

---

## 6. HTTP Router — `build_eval_router` + Pre-Built UI

Mount once, get 11 API endpoints + (optionally) a full eval workbench UI:

### 6.1 Backend only (default)

```python
from ryuu_eval.http import build_eval_router

router = build_eval_router(
    runner_factory=my_factory,
    template_registry={t.template_id: t for t in [HAPPY_PATH, EDGE_CASE]},
    cases_dir=Path("artifacts/eval/cases"),
    refine_log_dir=Path("artifacts/eval/refine_history"),
    require_auth=require_auth,         # optional FastAPI dep
    optimizer_callback=my_optimizer,    # called by POST /optimize
)
app.include_router(router, prefix="/api/eval")
```

**Endpoints:**
| Method | Path | Purpose |
|---|---|---|
| GET | `/templates` | List all registered templates |
| GET | `/templates/{template_id}` | Template detail (input + expected schemas) |
| POST | `/templates/{template_id}/cases` | Persist new case từ UI form |
| GET | `/suites/{suite_id}/cases` | List cases for a suite |
| PUT | `/suites/{suite_id}/cases/{case_id}` | Edit existing case |
| DELETE | `/suites/{suite_id}/cases/{case_id}` | Remove case |
| POST | `/run` | Blocking run, returns SuiteResult |
| GET | `/run/stream/{suite_id}` | SSE stream of ProgressEvent |
| GET | `/refine_history/{suite_id}` | Recent refine events + stats |
| POST | `/optimize/{suite_id}` | Manual fire PromptOptimizer (Q3 = C) |
| GET | `/status` | Framework status + cron flag |

### 6.2 Backend + Pre-Built UI (Tier 1)

Add `serve_ui=True` để get a full eval workbench UI at no extra effort:

```python
# Install: pip install ryuu-eval-frontend
app.include_router(build_eval_router(
    runner_factory=my_factory,
    template_registry={...},
    serve_ui=True,       # ← serves UI at /api/eval/ui
), prefix="/api/eval")
```

Open `http://localhost:8000/api/eval/ui` → working workbench:
- Sidebar: suite picker, template gallery (filter by tags), case list
- Editor: split input/expected JSON, save case persists as YAML
- Live SSE progress log
- Diff view (actual vs expected, highlighted mismatches)
- Refine history panel (LLM mistakes + per-iteration feedback)
- Optimize button → fires `POST /api/eval/optimize/{suite_id}` → diff modal

**Tech stack (no build step needed):**
- Pure static HTML/JS/CSS bundle (~30KB total)
- Preact + htm loaded via esm.sh CDN (cached)
- Zero npm install for consumers

**Custom prefix:**
```python
build_eval_router(..., serve_ui=True, ui_prefix="/workbench")
# → UI at /api/eval/workbench
```

**Override config (in project's HTML wrapper if iframing):**
```html
<script>
  window.RYUU_EVAL_CONFIG = {
    apiPrefix: "/api/v2/eval",
    defaultSuiteId: "intent_classifier",
  };
</script>
```

### 6.3 Tier 2/3 (Future)

For projects với existing React app or non-HTTP consumers:

- **Tier 2** — `@ryuu/eval-frontend-react` npm package — composable React
  components (planned)
- **Tier 3** — `ryuu_eval.mcp` — MCP server exposing eval as tools/resources
  to Claude desktop / agent clients (planned)

---

## 7. Optimization Loop — Q3 = C (Manual + Cron Opt-in)

**Manual fire (always enabled):**
```typescript
// UI button click handler
fetch(`/api/eval/optimize/${suiteId}`, {
  method: "POST",
  body: JSON.stringify({max_rounds: 2, threshold_pp: 5}),
})
```

**Cron auto-PR (opt-in via env):**
```bash
# Enable cron pipeline (default OFF)
export CRON_OPTIMIZE_ENABLED=true

# Cron runs nightly:
#   1. Load refine_history.jsonl per suite
#   2. Convert events → EvalCase
#   3. Run PromptOptimizer
#   4. If score gain ≥ threshold, open PR with new YAML
```

`build_eval_router(...)` accepts `optimizer_callback`:
```python
async def my_optimizer(suite_id: str, params: dict) -> dict:
    """Project's callback — invokes scripts/optimize_<suite>.py."""
    return {
        "base_score": 0.50,
        "best_score": 0.83,
        "gain_pp": 33.0,
        "best_prompt": "...",
        "applied": False,  # human review required
    }

router = build_eval_router(..., optimizer_callback=my_optimizer)
```

---

## 8. Complete Example — New Project in ~30 Minutes

```python
# my_project/eval/templates.py
from ryuu_eval import EvalCaseTemplate

INTENT_TPL = EvalCaseTemplate(
    template_id="intent_v1", suite_id="support",
    title="Intent Classifier",
    input_schema={"properties": {"message": {"type": "string"}}},
    expected_schema={"properties": {
        "intent": {"type": "string", "enum": ["BILLING", "TECH", "OTHER"]},
        "confidence": {"type": "number"},
    }},
    examples=[{
        "input": {"message": "I want a refund"},
        "expected": {"intent": "BILLING", "confidence": 0.9},
    }],
)
```

```python
# my_project/eval/scorers.py
from ryuu_eval_core import EvalCase, ScoreResult
import json

class IntentScorer:
    scorer_id = "intent_match"
    async def score(self, case: EvalCase, output: str) -> ScoreResult:
        try:
            actual = json.loads(output)
            match = actual.get("intent") == case.expected["intent"]
            return ScoreResult(self.scorer_id, 1.0 if match else 0.0, match)
        except Exception:
            return ScoreResult(self.scorer_id, 0.0, False, "parse error")
```

```python
# my_project/eval/targets.py
from ryuu import Agent
from ryuu_eval_core import CaseResult, EvalCase

class IntentTarget:
    def __init__(self):
        self._agent = Agent(model="gpt-4o-mini", instructions="Classify intent. JSON.")
    async def run(self, case: EvalCase) -> CaseResult:
        result = await self._agent.run(case.input)
        return CaseResult(case=case, output=result.output)
```

```python
# my_project/eval/runner.py
from pathlib import Path
from ryuu_eval_core import EvalRunner
from ryuu.refine_logger import RefineLogger
from my_project.eval.targets import IntentTarget
from my_project.eval.scorers import IntentScorer

def build_runner(suite_id: str, log_path: Path) -> EvalRunner:
    return EvalRunner(
        suite_id=suite_id,
        target=IntentTarget(),
        scorers=[IntentScorer()],
        refine_logger=RefineLogger(log_path),
    )
```

```python
# my_project/api/app.py
from fastapi import FastAPI
from ryuu_eval.http import build_eval_router
from my_project.eval.runner import build_runner
from my_project.eval.templates import INTENT_TPL

app = FastAPI()
app.include_router(
    build_eval_router(
        runner_factory=build_runner,
        template_registry={INTENT_TPL.template_id: INTENT_TPL},
    ),
    prefix="/api/eval",
)
```

**That's it.** UI works, templates discoverable, SSE streams, optimizer triggerable.

---

## 9. UI Components (Reference)

For React frontend, recommended pattern:

```typescript
import { useEffect, useState } from 'react'
import Form from '@rjsf/core'
import validator from '@rjsf/validator-ajv8'

function EvalPage({ suiteId }) {
  const [templates, setTemplates] = useState([])
  const [cases, setCases] = useState([])
  const [progress, setProgress] = useState([])

  useEffect(() => {
    fetch('/api/eval/templates').then(r => r.json()).then(setTemplates)
    fetch(`/api/eval/suites/${suiteId}/cases`).then(r => r.json()).then(setCases)
  }, [suiteId])

  const runStream = () => {
    const sse = new EventSource(`/api/eval/run/stream/${suiteId}`)
    sse.onmessage = (e) => setProgress(p => [...p, JSON.parse(e.data)])
  }

  return (
    <div className="grid grid-cols-4 gap-4">
      <Sidebar templates={templates} cases={cases} />
      <main className="col-span-3">
        {/* Form auto-rendered từ template.input_schema */}
        <Form schema={selectedTemplate.input_schema} validator={validator} />
        <Form schema={selectedTemplate.expected_schema} validator={validator} />
        <button onClick={runStream}>Run</button>
        <ProgressLog events={progress} />
      </main>
    </div>
  )
}
```

---

## 10. Migration From Custom Eval Code

If your project has custom eval code (subprocess + bespoke routes), migrate gradually:

| Phase | Action |
|---|---|
| **A** | Ship framework additions; existing code keeps running |
| **B** | Add YAML loader alongside Python cases (both work) |
| **C** | Convert ONE suite's cases to YAML — prove UX |
| **D** | Convert remaining suites |
| **E** | Remove custom code, single source of truth = framework |

---

## 11. References

- [Prompt Optimizer (07)](07-prompt-optimizer.md) — uses `RefineLogger` events as training data
- [Cross-cutting (03)](03-cross-cutting.md) — `RefineLogger` joins audit/tracer/cost as opt-in observability
- DSPy + OpenAI Prompt Optimizer beta — inspiration for the optimization pattern

---

**Status:** v0.4.0a1 — Ships in `ryuu-eval-core` 0.4.0a1 + `ryuu` (umbrella) 0.3.0a18+.
