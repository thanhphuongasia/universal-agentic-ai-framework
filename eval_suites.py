"""Eval suite registry — templates, targets, and runner factory.

Imported by dev_server.py (and any other entry point) to keep wiring logic
out of the server startup file. Project-specific data (templates, scorers,
target wrappers) lives under ``eval_consumer/<suite>/`` — this file only
wires them up.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from ryuu_observability_core.logger import ILogger, NullLogger

from ryuu_core.context import ContextScope, ExecutionContext
from ryuu_core.models import AgentResult, Cost, Task
from ryuu_eval_core.models import CaseResult, EvalCase, EvalCaseTemplate
from ryuu_eval_core.runner import EvalRunner
from eval_consumer.crud_matrix_llm.scorer import CRUDOpsMatch
from eval_consumer.crud_matrix_llm.target import CrudMatrixTarget
from eval_consumer.crud_matrix_llm.template import TEMPLATE as crud_matrix_llm_template
from ryuu_eval_scorers import ExactMatch, SemanticSimilarity
from ryuu_execution.llm_agent import LLMAgent
from ryuu_providers_core._pricing import calculate_usd
from ryuu_providers_core.llm import CompletionRequest, Message


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

_CODE_FENCE = re.compile(r"^```(?:json|python|javascript|yaml|xml)?\s*\n?(.*?)\n?```\s*$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    """Remove markdown code fence wrappers that LLMs add around JSON output."""
    m = _CODE_FENCE.match(text.strip())
    return m.group(1).strip() if m else text.strip()


# ---------------------------------------------------------------------------
# Step-collecting callbacks — wired into _react_loop for trace capture
# ---------------------------------------------------------------------------

@dataclass
class _StepCallbacks:
    """Collects _react_loop events into a steps list for the eval UI trace panel."""

    steps: list[dict] = field(default_factory=list)

    async def on_thought(self, text: str) -> None:
        if text.strip():
            self.steps.append({"type": "thought", "content": text, "label": "thinking"})

    async def on_action(self, tool_name: str, args: dict[str, Any]) -> None:
        self.steps.append({
            "type": "tool_call",
            "content": {"name": tool_name, "arguments": args},
            "label": tool_name,
        })

    async def on_observation(self, tool_name: str, result: str) -> None:
        self.steps.append({"type": "observation", "content": result, "label": tool_name})

    async def on_final(self, text: str) -> None:
        self.steps.append({"type": "llm_output", "content": text.strip(), "label": "output"})


# ---------------------------------------------------------------------------
# Framework-backed eval agent
# ---------------------------------------------------------------------------

@dataclass
class _EvalLLMAgent(LLMAgent):
    """One-shot eval agent — uses _react_loop(max_rounds=1) for proper framework routing.

    Steps (system prompt, user input, thinking, output) are captured via
    _StepCallbacks and stored in AgentResult.metadata["steps"] so the UI
    trace panel can render them.
    """

    model_name: str = ""
    eval_logger: ILogger = field(default_factory=NullLogger)

    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:  # noqa: ARG002
        user_input = str(task.payload["input"])
        system: str = task.payload.get("system", "") or ""
        response_schema: dict | None = task.payload.get("response_schema")
        # max_tokens / temperature are optional. None → don't pass → provider default.
        max_tokens: int | None = task.payload.get("max_tokens")
        temperature: float | None = task.payload.get("temperature")

        # Pre-steps: static context before LLM is called
        cb = _StepCallbacks()
        if system:
            cb.steps.append({"type": "llm_input", "content": system, "label": "system prompt"})
        cb.steps.append({"type": "llm_input", "content": user_input, "label": "user"})

        req_kwargs: dict[str, Any] = {
            "model": self.model_name,
            "messages": [Message(role="user", content=user_input)],
            "system": system or None,
            "response_schema": response_schema,
        }
        if max_tokens is not None:
            req_kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            req_kwargs["temperature"] = temperature
        req = CompletionRequest(**req_kwargs)

        self.eval_logger.info(
            "[eval] %s → task=%s | schema=%s | max_tokens=%s | temp=%s",
            self.model_name, task.task_id[:8], bool(response_schema),
            max_tokens, temperature,
        )
        content, usage = await self._react_loop(req, max_rounds=1, callbacks=cb)

        # Strip markdown code fences that LLMs add around JSON responses
        stripped = _strip_code_fence(content)
        if stripped != content:
            self.eval_logger.debug("[eval] stripped markdown code fence from LLM output")
        content = stripped

        # Annotate the llm_output step with model + token info
        if cb.steps and cb.steps[-1].get("type") == "llm_output":
            cb.steps[-1]["content"] = content  # update with stripped content
            cb.steps[-1]["label"] = (
                f"{self.model_name} · {usage.input_tokens}in/{usage.output_tokens}out tok"
            )

        cost_usd = calculate_usd(self.model_name, usage.input_tokens, usage.output_tokens)
        return AgentResult(
            task_id=task.task_id,
            output=content.strip(),
            cost=Cost(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                usd=cost_usd,
                provider=getattr(self.llm, "provider_id", "llm"),
                model=self.model_name,
            ),
            metadata={"steps": cb.steps},
        )


# ---------------------------------------------------------------------------
# Provider factory — raises immediately if required key is missing
# ---------------------------------------------------------------------------

def _build_provider(model: str) -> Any:
    if model.startswith("claude"):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                f"Model '{model}' requires ANTHROPIC_API_KEY. "
                "Add it to your .env file or run: export ANTHROPIC_API_KEY=sk-ant-..."
            )
        from ryuu_providers_anthropic import AnthropicProvider
        return AnthropicProvider(default_model=model)

    if any(model.startswith(p) for p in ("gpt-", "o1", "o3", "o4")):
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                f"Model '{model}' requires OPENAI_API_KEY. "
                "Add it to your .env file or run: export OPENAI_API_KEY=sk-..."
            )
        from ryuu_providers_openai import OpenAIProvider
        return OpenAIProvider(default_model=model)

    raise ValueError(
        f"No provider registered for model: {model!r}. "
        "Use claude-* (Anthropic) or gpt-*/o1/o3/o4 (OpenAI)."
    )


# ---------------------------------------------------------------------------
# EvalCase adapter — wraps _EvalLLMAgent for EvalRunner
# ---------------------------------------------------------------------------

class LLMEvalTarget:
    """Adapts _EvalLLMAgent to the EvalRunner target protocol."""

    def __init__(
        self,
        model: str,
        system_prompt: str = "",
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        response_schema: dict | None = None,
        logger: ILogger | None = None,
    ) -> None:
        self._model = model
        self._system = system_prompt
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._response_schema = response_schema
        self._logger: ILogger = logger or NullLogger()
        self._agent = _EvalLLMAgent(
            agent_id=f"eval-{model}",
            llm=_build_provider(model),   # raises if key missing
            model_name=model,
            eval_logger=self._logger,
        )

    async def run(self, case: EvalCase) -> CaseResult:
        import time

        # Prefer a per-case schema override; otherwise use the suite-level
        # schema threaded in at construction. Passing a schema switches the
        # provider into structured/JSON mode → output is guaranteed parseable
        # JSON with no prose. _strip_code_fence() / robust extraction remain a
        # safety net for providers/cases that opt out.
        response_schema: dict | None = (
            case.metadata.get("response_schema") or self._response_schema
        )
        payload: dict[str, Any] = {
            "input": case.input,
            "system": self._system,
            "response_schema": response_schema,
        }
        if self._max_tokens is not None:
            payload["max_tokens"] = self._max_tokens
        if self._temperature is not None:
            payload["temperature"] = self._temperature

        task = Task(task_id=str(uuid.uuid4()), payload=payload)
        ctx = ExecutionContext(
            scope=ContextScope(user_id="eval", session_id=case.case_id, domain="eval"),
            correlation_id=case.case_id,
        )

        t0 = time.monotonic()
        try:
            result = await self._agent.execute(task, ctx)
        except Exception:
            self._logger.exception("[eval] case=%s model=%s FAILED", case.case_id, self._model)
            raise
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
        self._logger.info("[eval] case=%s done in %.0fms cost=$%.5f", case.case_id, latency_ms, result.cost.usd)

        steps: list[dict] = result.metadata.get("steps", [])
        if steps and steps[-1].get("type") == "llm_output":
            steps[-1]["label"] += f" · {round(latency_ms)}ms"

        return CaseResult(
            case=case,
            output=result.output,
            latency_ms=latency_ms,
            cost_usd=round(result.cost.usd, 6),
            steps=steps,
        )


# ---------------------------------------------------------------------------
# Judge provider factory — Registry pattern, returns None when no key set.
# NO default_model — provider falls back to whatever its package default is,
# or fails. Avoids silently picking haiku.
# ---------------------------------------------------------------------------

_JUDGE_REGISTRY: list[tuple[str, str, str, dict]] = [
    ("ANTHROPIC_API_KEY", "ryuu_providers_anthropic", "AnthropicProvider", {}),
    ("OPENAI_API_KEY",    "ryuu_providers_openai",    "OpenAIProvider",    {}),
]


def _make_judge_provider() -> Any:
    for env_var, module_path, cls_name, kwargs in _JUDGE_REGISTRY:
        if os.environ.get(env_var):
            mod = __import__(module_path, fromlist=[cls_name])
            return getattr(mod, cls_name)(**kwargs)
    return None


# ---------------------------------------------------------------------------
# Suite behavior registry — CATEGORY (template_id) → (target wrapper, scorers).
#
# Dispatch is keyed on the suite's CATEGORY, never its instance name. A cloned
# suite ("crud_matrix_llm_phuong_suite") keeps the right wiring as long as its
# suite_config declares ``template_id: "crud_matrix_llm"``. Adding a category =
# one entry here; no branching elsewhere (Registry + Open/Closed).
# ---------------------------------------------------------------------------

def _crud_matrix_behavior(base: Any) -> tuple[Any, list]:
    """CRUD matrix: project-specific target normalizes expected + actual to flat
    op maps; CRUDOpsMatch scores op-by-op. All CRUD format knowledge stays in
    eval_consumer/crud_matrix_llm/."""
    return CrudMatrixTarget(base), [CRUDOpsMatch(threshold=0.8)]


_SUITE_BEHAVIOR: dict[str, Any] = {
    "crud_matrix_llm": _crud_matrix_behavior,
}


# ---------------------------------------------------------------------------
# Runner factory — called by build_eval_router per run request
# ---------------------------------------------------------------------------

def runner_factory(
    suite_id: str,
    _log_path: object,
    model: str | None = None,
    system_prompt: str | None = None,
    *,
    template_id: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    budget_cap_usd: float | None = None,
    logger: ILogger | None = None,
) -> EvalRunner:
    if not model:
        raise ValueError(
            "No model selected. Choose a model in the Run dialog before starting."
        )

    # NOTE: we deliberately do NOT auto-enforce the suite's output_schema here.
    # Benchmarked it (2026-05-30): forcing structured output via the schema makes
    # Anthropic's forced-tool path emit a degenerate empty `{}` for open
    # (dynamic-key) schemas — claude-opus-4-7 fell from 1.00 → 0.00. The robust
    # JSON extraction in CrudMatrixTarget already strips prose without altering
    # generation, so scores reflect reasoning, not output mode. Per-case schema
    # override (case.metadata["response_schema"]) is still honored for callers
    # that explicitly opt in on a closed schema.

    # LLMEvalTarget raises immediately if the required API key is not set
    base_target: Any = LLMEvalTarget(
        model, system_prompt or "",
        max_tokens=max_tokens, temperature=temperature,
        logger=logger,
    )

    # Resolve the suite's CATEGORY and dispatch via the registry. Prefer the
    # explicit template_id (from suite_config); fall back to suite_id for legacy
    # suites whose name IS the category (e.g. the original "crud_matrix_llm").
    category = template_id or suite_id
    behavior = _SUITE_BEHAVIOR.get(category)
    target: Any
    scorers: list
    if behavior is not None:
        target, scorers = behavior(base_target)
    else:
        # Generic suite: LLM-judge similarity when a judge key is set, else exact.
        target = base_target
        judge = _make_judge_provider()
        scorers = (
            [SemanticSimilarity(provider=judge, threshold=0.7)]
            if judge else [ExactMatch()]
        )

    # budget_cap_usd reserved for future EvalRunner-level cost enforcement.
    # Currently logged for visibility; runner has no built-in budget gate yet.
    if budget_cap_usd is not None and logger is not None:
        logger.info("[eval] suite=%s budget_cap=$%.4f (advisory only — not enforced yet)",
                    suite_id, budget_cap_usd)

    return EvalRunner(suite_id=suite_id, target=target, scorers=scorers)


# ---------------------------------------------------------------------------
# Template registry — generic templates here; project-specific imported.
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, EvalCaseTemplate] = {
    "qa": EvalCaseTemplate(
        template_id="qa",
        suite_id="qa",
        title="Q&A Suite",
        description="Factual question-answering. Model must give the correct short answer.",
        input_schema={"type": "string", "description": "Question to ask the model"},
        expected_schema={"type": "string", "description": "Expected short answer"},
        examples=[
            {"input": "Capital of France?", "expected": "Paris"},
            {"input": "Capital of Japan?", "expected": "Tokyo"},
            {"input": "What year did WWII end?", "expected": "1945"},
            {"input": "Who wrote Romeo and Juliet?", "expected": "Shakespeare"},
        ],
        tags=["smoke", "factual"],
    ),
    "summarization": EvalCaseTemplate(
        template_id="summarization",
        suite_id="summarization",
        title="Summarization Suite",
        description="Tests model's ability to produce concise, accurate summaries.",
        input_schema={"type": "string", "description": "Text to summarize (prefix with 'Summarise: ')"},
        expected_schema={"type": "string", "description": "Expected concise summary (2-5 words)"},
        examples=[
            {"input": "Summarise: The cat sat on the mat.", "expected": "Cat on mat."},
            {"input": "Summarise: The sun rose over the mountains at dawn.", "expected": "Sun rose at dawn."},
            {"input": "Summarise: Scientists discovered a new species of deep-sea fish in the Pacific Ocean.", "expected": "New deep-sea fish found."},
        ],
        tags=["summarization"],
    ),
    "code-review": EvalCaseTemplate(
        template_id="code-review",
        suite_id="code-review",
        title="Code Review",
        description="Test model's ability to identify bugs, security issues, and code quality problems.",
        input_schema={"type": "string", "description": "Code snippet to review. Start with a comment indicating the language."},
        expected_schema={"type": "string", "description": "'PASS' or a short description of the primary issue found."},
        examples=[
            {"input": "# Python\ndef divide(a, b):\n    return a / b", "expected": "FAIL: ZeroDivisionError — no zero guard"},
            {"input": "# Python\ndef greet(name: str) -> str:\n    return f'Hello, {name}!'", "expected": "PASS"},
            {"input": "# SQL\nquery = \"SELECT * FROM users WHERE id = \" + user_input", "expected": "FAIL: SQL injection vulnerability"},
            {"input": "# JavaScript\nconst users = await fetch('/api/users').then(r => r.json());", "expected": "FAIL: no error handling on fetch"},
        ],
        tags=["code", "security", "edge_case"],
    ),
    "classification": EvalCaseTemplate(
        template_id="classification",
        suite_id="classification",
        title="Text Classification",
        description="Test model's ability to classify text into predefined categories.",
        input_schema={"type": "string", "description": "Instruction + text to classify (e.g. 'Classify sentiment: ...')"},
        expected_schema={"type": "string", "description": "Expected category label (lowercase)"},
        examples=[
            {"input": "Classify sentiment: 'I love this product, it's amazing!'", "expected": "positive"},
            {"input": "Classify sentiment: 'Terrible experience, never buying again.'", "expected": "negative"},
            {"input": "Classify sentiment: 'The package arrived on time.'", "expected": "neutral"},
            {"input": "Classify topic: 'The Fed raised interest rates by 25 basis points.'", "expected": "finance"},
            {"input": "Classify topic: 'Barcelona beat Real Madrid 3-1 in El Clásico.'", "expected": "sports"},
        ],
        tags=["classification", "smoke"],
    ),
    "translation": EvalCaseTemplate(
        template_id="translation",
        suite_id="translation",
        title="Translation Suite",
        description="Test translation quality across language pairs.",
        input_schema={"type": "string", "description": "Translation instruction + source text (e.g. 'Translate to Japanese: ...')"},
        expected_schema={"type": "string", "description": "Expected translation in target language"},
        examples=[
            {"input": "Translate to Japanese: Good morning.", "expected": "おはようございます"},
            {"input": "Translate to French: Thank you very much.", "expected": "Merci beaucoup"},
            {"input": "Translate to Spanish: Where is the nearest station?", "expected": "¿Dónde está la estación más cercana?"},
            {"input": "Translate to German: I would like a coffee, please.", "expected": "Ich hätte gerne einen Kaffee, bitte."},
        ],
        tags=["translation", "multilingual"],
    ),
    "hallucination-check": EvalCaseTemplate(
        template_id="hallucination-check",
        suite_id="hallucination-check",
        title="Hallucination Check",
        description="Detect when the model fabricates facts not grounded in the provided context.",
        input_schema={"type": "string", "description": "Context paragraph + question. Model must answer from context only."},
        expected_schema={"type": "string", "description": "'GROUNDED' if model answers correctly, or the specific false claim to watch for."},
        examples=[
            {
                "input": "Context: Tokyo is the capital city of Japan, with a population of ~14 million.\nQ: What is the capital of Japan?",
                "expected": "GROUNDED",
            },
            {
                "input": "Context: (no context provided)\nQ: What did Einstein say about quantum mechanics?",
                "expected": "GROUNDED",
            },
            {
                "input": "Context: The Eiffel Tower was built in 1889 for the World's Fair.\nQ: When was the Eiffel Tower built and why?",
                "expected": "GROUNDED",
            },
        ],
        tags=["hallucination", "safety", "regression"],
    ),
    # Project-specific template — owned by eval_consumer/crud_matrix_llm/
    "crud_matrix_llm": crud_matrix_llm_template,
}
