#!/usr/bin/env bash
# Install all RYUU packages in editable mode for local development.
#
# Usage from any directory:
#   bash /path/to/uaaf-framework/scripts/install-dev.sh
#
# Run from inside your app's venv (or current Python env). After this:
#   from ryuu import Agent
# works regardless of where your app code lives.
#
# Editable install means: edits in /path/to/uaaf-framework/ryuu/*.py
# are reflected immediately in your app — no reinstall.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "Installing RYUU from: $REPO_ROOT"
echo

# Install order matters for dep resolution. Order = topological sort of
# inter-package deps (core first, leaves last). --no-deps prevents pip from
# trying to fetch sub-package deps from PyPI (they're all local editable).
ORDER=(
    # Tier 1 — zero ryuu-* deps
    "ryuu-core"

    # Tier 2 — depend only on ryuu-core
    "ryuu-workflow"
    "ryuu-providers"
    "ryuu-observability"
    "ryuu-guardrail"
    "ryuu-knowledge-base"

    # Tier 3 — depend on tier 1+2
    "ryuu-cognitive"
    "ryuu-execution"
    "ryuu-knowledge-memory"
    "ryuu-knowledge-graph"
    "ryuu-eval"

    # Tier 4 — depend on tier 3
    "ryuu-knowledge"
    "ryuu-knowledge-rag"   # Phase 11 — RAG pipeline (chunker + vector store + retriever)
    "ryuu-reasoning"       # Phase 14.7 — formal verifiers (RuleVerifier + optional Z3Verifier)

    # Tier 5 — runtime facade
    "ryuu-runtime"

    # Tier 6 — messaging layer (Phase 8.8 — channel-agnostic chat primitives)
    "messaging/ryuu-messaging-core"
    "messaging/ryuu-messaging-cli"
    "messaging/ryuu-messaging-telegram"
)

for pkg in "${ORDER[@]}"; do
    pkg_path="$REPO_ROOT/packages/$pkg"
    if [[ ! -d "$pkg_path" ]]; then
        echo "  ⚠️  $pkg not found at $pkg_path — skipping"
        continue
    fi
    echo "  Installing $pkg (editable)..."
    pip install --quiet --no-deps -e "$pkg_path"
done

# Root ryuu package (depends on all the above + adds Factory/facades/batch/...)
echo "  Installing ryuu (root facade, editable, with [dev] extras)..."
pip install --quiet --no-deps -e "$REPO_ROOT[dev]"

# Backfill external dependencies that --no-deps skipped:
# anyio, openai, anthropic, opentelemetry, pyyaml, pydantic, pytest, etc.
# Re-run root install WITHOUT --no-deps to fetch them (sub-packages will be
# satisfied by the editable installs we just made).
echo
echo "  Backfilling external deps (anyio, openai, opentelemetry, pyyaml, ...)..."
pip install --quiet -e "$REPO_ROOT[dev]" 2>&1 | grep -v "Requirement already satisfied" || true

echo
echo "Verifying public API surface..."
python -c "
import ryuu
print(f'  ryuu              {ryuu.__version__}')
from ryuu import (
    Agent, StreamEvent,
    Chain, FanOut, Router, Orchestrator, Evaluator,
    BatchRunner, BatchItem, BatchAPIClient, OpenAIBatchClient,
    EvalCase, PromptOptimizer, OptimizationResult,
    BaseAgent, AgentPool, AgentResult, Task,
)
print(f'  Imports OK: Agent + 5 facades + 4 batch + 3 optimizer + 4 class primitives')

# Verify sub-packages also importable
import ryuu_core, ryuu_workflow, ryuu_providers, ryuu_observability
import ryuu_execution, ryuu_cognitive, ryuu_runtime, ryuu_eval, ryuu_guardrail
import ryuu_knowledge_base, ryuu_knowledge_memory, ryuu_knowledge_graph, ryuu_knowledge
print(f'  All 13 sub-packages importable')
"

echo
echo "✅ RYUU installed editable. Your app can now: from ryuu import Agent"
echo "   Code edits in $REPO_ROOT/ryuu/ + $REPO_ROOT/packages/ are picked up immediately."
