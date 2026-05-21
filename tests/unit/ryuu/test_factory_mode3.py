"""Mode 3 prompt API: load `system` / `user_template` from file path.

Phase 10.2 — 4 cases. Expected RED until T1 implementation.

```python
agent = Agent(
    model="gpt-4o",
    system=Path("prompts/personas/analyst.md"),
    user_template=Path("prompts/templates/analyze.txt"),
)
```

File content is read at __post_init__ and stored as str.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ryuu import Agent
from ryuu._testing.fakes import FakeLLMProvider


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


async def test_system_from_file_path(tmp_path: Path) -> None:
    """`system=Path(...)` reads file content as system prompt."""
    system_file = tmp_path / "persona.md"
    system_file.write_text("You are a senior data analyst.")

    agent = Agent(model="gpt-4o-mini", system=system_file)
    agent._agent.llm = FakeLLMProvider()  # type: ignore[attr-defined]

    await agent.run("Hello")
    msgs = list(agent._agent.llm.last_request.messages)  # type: ignore[attr-defined]
    assert msgs[0].role == "system"
    assert msgs[0].content == "You are a senior data analyst."


async def test_user_template_from_file_path(tmp_path: Path) -> None:
    """`user_template=Path(...)` reads file content as template."""
    tmpl_file = tmp_path / "analyze.txt"
    tmpl_file.write_text("Analyze this data: {payload}")

    agent = Agent(model="gpt-4o-mini", user_template=tmpl_file)
    agent._agent.llm = FakeLLMProvider()  # type: ignore[attr-defined]

    await agent.run(payload="sales report Q1")
    msgs = list(agent._agent.llm.last_request.messages)  # type: ignore[attr-defined]
    user_msg = next(m for m in msgs if m.role == "user")
    assert user_msg.content == "Analyze this data: sales report Q1"


def test_system_file_not_found_raises(tmp_path: Path) -> None:
    """Missing file → FileNotFoundError (informative)."""
    missing = tmp_path / "does_not_exist.md"
    with pytest.raises(FileNotFoundError, match="does_not_exist"):
        Agent(model="gpt-4o-mini", system=missing)


async def test_combined_file_system_and_file_user_template(tmp_path: Path) -> None:
    """Both system + user_template can be file paths simultaneously."""
    (tmp_path / "sys.md").write_text("You are a translator.")
    (tmp_path / "user.txt").write_text("Translate to {lang}: {text}")

    agent = Agent(
        model="gpt-4o-mini",
        system=tmp_path / "sys.md",
        user_template=tmp_path / "user.txt",
    )
    agent._agent.llm = FakeLLMProvider()  # type: ignore[attr-defined]

    await agent.run(lang="VN", text="Hello")
    msgs = list(agent._agent.llm.last_request.messages)  # type: ignore[attr-defined]
    assert msgs[0].content == "You are a translator."
    user_msg = next(m for m in msgs if m.role == "user")
    assert user_msg.content == "Translate to VN: Hello"
