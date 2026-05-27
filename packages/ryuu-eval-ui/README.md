# ryuu-eval-ui

React eval workbench UI for the Ryuu framework. Built with Vite + React 18 +
TypeScript + Tailwind CSS. Served as a pre-built static bundle via FastAPI.

## Installation

```bash
pip install ryuu-eval-ui
```

## Usage

```python
from fastapi import FastAPI
from ryuu_eval.http import build_eval_router

app = FastAPI()
app.include_router(build_eval_router(
    runner_factory=my_runner_factory,
    template_registry={my_template.template_id: my_template},
    serve_ui=True,      # ← serves UI at /api/eval/ui
), prefix="/api/eval")
```

Open `http://localhost:8000/api/eval/ui` → full eval workbench:

- **Dashboard** — suite overview, pass-rate stats, recent runs
- **Suite Detail** — cases table, scorers, last run summary
- **Run Config** — model, prompt, parallel/sequential, concurrency, budget cap
- **Live Run Monitor** — SSE progress, cost meter, per-case status, cancel
- **Run Results** — stat cards, score distribution chart, failure clusters, CSV export
- **Case Detail** — input/expected/actual diff view, keyboard nav, human review
- **Comparison** — suite A vs suite B metric diff
- **Prompt Playground** — single-case run, version history, output panel
- **Dark mode** — auto-detects system preference, persists to localStorage

## Dev workflow (React source)

```bash
cd packages/ryuu-eval-ui/web
npm install
npm run dev          # Vite dev server at :5173, proxies /api → localhost:8000
npm run build        # builds into src/ryuu_eval_ui/dist/ for the Python wheel
npm run lint         # ESLint
```

## Architecture

```
packages/ryuu-eval-ui/
├── pyproject.toml              Python wheel (name: ryuu-eval-ui)
├── src/ryuu_eval_ui/
│   ├── __init__.py             exports dist_dir()
│   └── dist/                  built Vite output (shipped in wheel)
│       ├── index.html
│       ├── .vite/manifest.json
│       └── assets/            hashed JS + CSS chunks
└── web/                       React source (Vite + TS)
    ├── vite.config.ts          outDir → ../src/ryuu_eval_ui/dist
    └── src/
        ├── api/               TanStack Query hooks + types
        ├── components/        Layout, StatusBadge, ScoreBar, Skeleton…
        └── pages/             Dashboard, SuiteDetail, RunMonitor…
```

## Backward compatibility

The old package name `ryuu-eval-frontend` still works via a meta-package shim
that depends on `ryuu-eval-ui`. It will be removed in the next minor release.

```bash
# Migrate
pip uninstall ryuu-eval-frontend
pip install ryuu-eval-ui
```

## Roadmap

- **v2 (next)** — Trace tree (requires backend span events), analytics trends, suite/case CRUD
- **Tier 2 (future)** — npm package `@ryuu/eval-ui` for embedding in existing React apps
- **Tier 3 (future)** — MCP server `ryuu_eval.mcp` for agents to query eval data directly
