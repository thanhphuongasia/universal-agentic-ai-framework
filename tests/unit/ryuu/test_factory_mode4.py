"""Mode 4 prompt API: `prompt="project:version:name"` YAML registry reference.

Phase 10.2 — 6 cases. Expected RED until T2 implementation.

```python
agent = Agent(
    model="gpt-4o",
    prompt="todo_app:v1:analyze",          # "project:version:prompt_name"
    prompt_registry=PromptRegistry(...),    # optional, default auto-detect
)
```

Loads system + user template from YAML. Tools handled separately (Mode A passing
callables) or via Mode D in Phase 10.3.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ryuu import Agent
from ryuu._testing.fakes import FakeLLMProvider
from ryuu.prompts.registry import PromptRegistry


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


@pytest.fixture
def yaml_fixture(tmp_path: Path) -> Path:
    """Create minimal prompts/test_proj/v1.yaml for tests."""
    project_dir = tmp_path / "test_proj"
    project_dir.mkdir()
    (project_dir / "v1.yaml").write_text("""
version: "1.0"
description: "Test project for Mode 4"
model: "gpt-4o-mini"
temperature: 0.2
max_tokens: 256

prompts:
  analyze:
    system: |
      You are a test analyzer.
    user: "Analyze: {query}"

  summarize:
    system: "You are a summarizer."
    user: "Summarize: {text}"
""")
    return tmp_path


async def test_mode4_loads_system_from_yaml(yaml_fixture: Path) -> None:
    """`prompt="proj:v1:name"` loads system from YAML template."""
    registry = PromptRegistry(prompts_root=yaml_fixture)
    agent = Agent(
        model="gpt-4o-mini",
        prompt="test_proj:v1:analyze",
        prompt_registry=registry,
    )
    agent._agent.llm = FakeLLMProvider()  # type: ignore[attr-defined]

    await agent.run(query="data point")
    msgs = list(agent._agent.llm.last_request.messages)  # type: ignore[attr-defined]
    assert msgs[0].role == "system"
    assert "test analyzer" in msgs[0].content.lower()


async def test_mode4_loads_user_template_from_yaml(yaml_fixture: Path) -> None:
    """User template from YAML is substituted with kwargs."""
    registry = PromptRegistry(prompts_root=yaml_fixture)
    agent = Agent(
        model="gpt-4o-mini",
        prompt="test_proj:v1:summarize",
        prompt_registry=registry,
    )
    agent._agent.llm = FakeLLMProvider()  # type: ignore[attr-defined]

    await agent.run(text="long article")
    msgs = list(agent._agent.llm.last_request.messages)  # type: ignore[attr-defined]
    user_msg = next(m for m in msgs if m.role == "user")
    assert user_msg.content == "Summarize: long article"


def test_mode4_validation_mutual_exclusion_with_instructions(yaml_fixture: Path) -> None:
    """`prompt=` + `instructions=` → ValueError."""
    registry = PromptRegistry(prompts_root=yaml_fixture)
    with pytest.raises(ValueError, match="prompt.*instructions|instructions.*prompt"):
        Agent(
            model="gpt-4o-mini",
            prompt="test_proj:v1:analyze",
            prompt_registry=registry,
            instructions="Override",
        )


def test_mode4_validation_mutual_exclusion_with_system(yaml_fixture: Path) -> None:
    """`prompt=` + `system=` → ValueError."""
    registry = PromptRegistry(prompts_root=yaml_fixture)
    with pytest.raises(ValueError, match="prompt.*system|system.*prompt"):
        Agent(
            model="gpt-4o-mini",
            prompt="test_proj:v1:analyze",
            prompt_registry=registry,
            system="Override",
        )


def test_mode4_validation_invalid_format() -> None:
    """`prompt` not in 'project:version:name' format → ValueError."""
    with pytest.raises(ValueError, match="project:version:name"):
        Agent(
            model="gpt-4o-mini",
            prompt="not_three_parts",
        )


def test_mode4_validation_missing_prompt_name(yaml_fixture: Path) -> None:
    """Reference to non-existent prompt name in YAML → KeyError."""
    registry = PromptRegistry(prompts_root=yaml_fixture)
    with pytest.raises(KeyError, match="does_not_exist"):
        Agent(
            model="gpt-4o-mini",
            prompt="test_proj:v1:does_not_exist",
            prompt_registry=registry,
        )
