# RYUU — Phase 2 (Verifier first-class) — Task Breakdown

> Phase 2 goal: `IVerifier` Protocol + concrete implementations (`SchemaVerifier`, `LLMJudgeVerifier`, `GroundTruthVerifier`) + `VerifierPipeline`. Replace Phase 1's stub IVerifier with full implementations. `EvaluatorOptimizerStrategy` now gets real verification.

**Status**: Complete
**Last Updated**: 2026-05-07
**Predecessors**: Phase 1 complete (v0.1.0b1)

---

## Task graph

```
P2-T01 Relocate IVerifier+VerificationResult → ryuu/cognitive/verifier.py
         │
         ├──→ P2-T02 SchemaVerifier
         ├──→ P2-T03 LLMJudgeVerifier
         ├──→ P2-T04 GroundTruthVerifier
         └──→ P2-T05 VerifierPipeline (depends on T02-T04)
                  │
                P2-T06 Tests + contract
                  │
                P2-T07 CI gate
```

---

## P2-T01. Relocate IVerifier (`ryuu/cognitive/verifier.py`)

**Acceptance**:
- Move `IVerifier` and `VerificationResult` out of `strategy.py` into `ryuu/cognitive/verifier.py`
- `strategy.py` re-exports them for backward compatibility: `from ryuu.cognitive.verifier import IVerifier, VerificationResult`
- All existing imports still work — 192 tests still pass

**Files**: `ryuu/cognitive/verifier.py` (new), `ryuu/cognitive/strategy.py` (update)

---

## P2-T02. SchemaVerifier (`ryuu/cognitive/verifiers/schema.py`)

**Acceptance**:
- `SchemaVerifier(required_keys: list[str], output_must_be_json: bool = True)`
- `verifier_id = "schema"`
- `verify(output, context)`:
  - If `output_must_be_json=True`: parse output as JSON; fail if not valid JSON
  - Check all `required_keys` exist in parsed dict
  - `passed = True` if all checks pass
  - `confidence = 1.0` if passed, `0.0` if not
  - `feedback` describes the first failure
- Non-JSON mode: just checks required substrings exist in raw output string

**Files**: `ryuu/cognitive/verifiers/__init__.py`, `ryuu/cognitive/verifiers/schema.py`

---

## P2-T03. LLMJudgeVerifier (`ryuu/cognitive/verifiers/llm_judge.py`)

**Acceptance**:
- `LLMJudgeVerifier(provider: ILLMProvider, model: str | None = None, threshold: float = 0.7)`
- `verifier_id = "llm_judge"`
- `verify(output, context)`:
  1. Build judge prompt: asks LLM to rate output quality 0.0–1.0 and say PASS/FAIL + reason
  2. Parse response: extract `score` (float) and `verdict` (`PASS`/`FAIL`)
  3. `passed = score >= threshold`
  4. On parse failure: `passed=False, confidence=0.0, feedback="Judge response unparseable"`
- Response format expected from LLM: `SCORE:0.85\nVERDICT:PASS\nREASON:<text>`

**Files**: `ryuu/cognitive/verifiers/llm_judge.py`

---

## P2-T04. GroundTruthVerifier (`ryuu/cognitive/verifiers/ground_truth.py`)

**Acceptance**:
- `GroundTruthVerifier(reference: str, mode: Literal["exact", "substring", "word_overlap"] = "substring", threshold: float = 0.5)`
- `verifier_id = "ground_truth"`
- Modes:
  - `exact`: `output.strip() == reference.strip()`, confidence = 1.0 or 0.0
  - `substring`: `reference in output`, confidence = 1.0 or 0.0
  - `word_overlap`: Jaccard similarity of word sets; passed if similarity >= threshold
- `passed` determined by mode; `confidence` = similarity score

**Files**: `ryuu/cognitive/verifiers/ground_truth.py`

---

## P2-T05. VerifierPipeline (`ryuu/cognitive/verifiers/pipeline.py`)

**Acceptance**:
- `class PipelineMode(StrEnum): ALL_PASS = "all_pass"; ANY_PASS = "any_pass"; THRESHOLD = "threshold"`
- `VerifierPipeline(verifiers: list[IVerifier], mode: PipelineMode = ALL_PASS, threshold_count: int = 1)`
- `verifier_id = "pipeline"`
- `verify(output, context)`:
  - Runs all verifiers in order
  - `ALL_PASS`: passed if all passed; confidence = min(confidences)
  - `ANY_PASS`: passed if any passed; confidence = max(confidences)
  - `THRESHOLD`: passed if `sum(results where passed) >= threshold_count`; confidence = mean
  - `feedback` = joined feedbacks of failed verifiers

**Files**: `ryuu/cognitive/verifiers/pipeline.py`

---

## P2-T06. Tests

**Unit tests**:
- `tests/unit/cognitive/test_schema_verifier.py`
- `tests/unit/cognitive/test_llm_judge_verifier.py`
- `tests/unit/cognitive/test_ground_truth_verifier.py`
- `tests/unit/cognitive/test_verifier_pipeline.py`

**Contract test**:
- `tests/contract/test_verifier_contract.py` — parametrized over all 4 verifiers (Schema, LLMJudge, GroundTruth, Pipeline)

**Integration**:
- `tests/integration/test_phase2_smoke.py` — EvaluatorOptimizerStrategy + real VerifierPipeline (Schema + GroundTruth)

---

## P2-T07. CI gate

- [x] `ruff check ryuu/ tests/` → 0 violations (2026-05-07)
- [x] `mypy ryuu/ --ignore-missing-imports` → 0 errors, 39 source files (2026-05-07)
- [x] `pytest --cov=ryuu` → 245 passed, 90.21% coverage (2026-05-07)
- [ ] User review + approve
- [ ] Tag v0.1.0b2

---

## Cross-task gates

- [x] CI gate green
- [x] All 4 verifiers pass contract test
- [x] CHANGELOG v0.1.0b2 entry
- [x] `FakeVerifier` in `_testing/fakes.py` still compatible
