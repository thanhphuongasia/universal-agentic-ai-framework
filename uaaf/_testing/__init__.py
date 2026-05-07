"""Public test utilities — import from here in product-side tests.

Usage::

    from uaaf._testing import FakeLLMProvider, fake_runtime
    from uaaf._testing.fixtures import tracer_fixture, cost_tracker_fixture
"""

from uaaf._testing.fakes import FakeKnowledgeBackbone, FakeLLMProvider

__all__ = ["FakeLLMProvider", "FakeKnowledgeBackbone"]
