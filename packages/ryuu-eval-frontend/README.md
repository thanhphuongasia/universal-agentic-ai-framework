# ryuu-eval-frontend

Pre-built eval workbench UI for ryuu framework. Static bundle (vanilla JS +
Preact + htm) — no Node.js build pipeline needed at install time.

## Usage

```python
from fastapi import FastAPI
from ryuu_eval.http import build_eval_router

app = FastAPI()
app.include_router(build_eval_router(
    runner_factory=my_runner_factory,
    template_registry={my_template.template_id: my_template},
    serve_ui=True,     # ← serves UI at /api/eval/ui
), prefix="/api/eval")
```

User opens `http://localhost:8000/api/eval/ui` → working eval workbench:
- Template gallery (filter by tags)
- Form editor (auto-rendered from JSON Schema)
- Live SSE progress
- Diff view (actual vs expected)
- Refine history panel
- 1-click prompt optimization

## What's Inside

```
dist/
├── index.html              entry HTML, loads bundle
├── ryuu-eval.js             ~20KB — UI logic (Preact + htm + Ajv via CDN)
└── ryuu-eval.css            ~5KB — styles
```

## Customization

Set `window.RYUU_EVAL_CONFIG` before bundle loads to override defaults:

```html
<script>
  window.RYUU_EVAL_CONFIG = {
    apiPrefix: "/api/v2/eval",  // custom prefix
    defaultSuiteId: "intent_classifier",
    theme: "dark",
  };
</script>
```

## Tiers (Roadmap)

- **Tier 1 (this package)** — Standalone static UI, served by Python.
- **Tier 2 (future)** — npm package `@ryuu/eval-frontend-react` for projects
  với existing React app, composable components.
- **Tier 3 (future)** — MCP server `ryuu_eval.mcp` for Claude desktop / agents
  to query eval data directly.
