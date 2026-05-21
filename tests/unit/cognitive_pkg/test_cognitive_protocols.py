"""RED tests — ryuu_cognitive protocols and strategies (import-only smoke tests)."""
import pytest


def test_iverifier_importable() -> None:
    from ryuu_cognitive.verifier import IVerifier, VerificationResult  # noqa: F401


def test_icognitivestrategy_importable() -> None:
    from ryuu_cognitive.strategy import IAgentPool, ICognitiveStrategy  # noqa: F401


def test_verification_result_fields() -> None:
    from ryuu_cognitive.verifier import VerificationResult

    r = VerificationResult(passed=True, confidence=0.9)
    assert r.passed is True
    assert r.confidence == 0.9
    assert r.feedback == ""


def test_direct_strategy_importable() -> None:
    from ryuu_cognitive.strategies import DirectStrategy  # noqa: F401


def test_react_strategy_importable() -> None:
    from ryuu_cognitive.strategies import ReActStrategy  # noqa: F401


def test_evaluator_optimizer_strategy_importable() -> None:
    from ryuu_cognitive.strategies import EvaluatorOptimizerStrategy  # noqa: F401


def test_parallel_fanout_strategy_importable() -> None:
    from ryuu_cognitive.strategies import ParallelFanoutStrategy, ISubtaskBuilder  # noqa: F401


def test_verifiers_importable() -> None:
    from ryuu_cognitive.verifiers import (  # noqa: F401
        GroundTruthVerifier,
        SchemaVerifier,
        LLMJudgeVerifier,
        VerifierPipeline,
        PipelineMode,
    )


def test_pipeline_mode_values() -> None:
    from ryuu_cognitive.verifiers import PipelineMode

    assert PipelineMode.ALL_PASS
    assert PipelineMode.ANY_PASS
    assert PipelineMode.THRESHOLD


def test_ground_truth_verifier_construct() -> None:
    from ryuu_cognitive.verifiers import GroundTruthVerifier

    v = GroundTruthVerifier(reference="hello world", mode="substring")
    assert v is not None


def test_schema_verifier_construct() -> None:
    from ryuu_cognitive.verifiers import SchemaVerifier

    v = SchemaVerifier(required_keys=["name", "age"])
    assert v is not None


def test_verifier_pipeline_construct() -> None:
    from ryuu_cognitive.verifiers import VerifierPipeline, PipelineMode

    p = VerifierPipeline(verifiers=[], mode=PipelineMode.ALL_PASS)
    assert p is not None


def test_direct_strategy_is_catch_all() -> None:
    from ryuu_cognitive.strategies import DirectStrategy

    s = DirectStrategy()
    assert s.strategy_id == "direct"


def test_react_strategy_default_max_steps() -> None:
    from ryuu_cognitive.strategies import ReActStrategy

    s = ReActStrategy()
    assert s.max_steps == 6
