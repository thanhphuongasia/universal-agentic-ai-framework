"""Mode 2 prompt API: tách `system` + `user_template` + `examples`.

Phase 10.1 — 8 cases. Expected RED until T3 implementation.

Mode 2 cho phép:
  - `system=str` — full system prompt (thay `instructions` shorthand)
  - `user_template=str` — template với `{variables}`, fill qua .run(**kwargs)
  - `examples=[{"user": ..., "assistant": ...}]` — few-shot interleave

Validation: cannot mix `instructions` (Mode 1) và `system` (Mode 2) cùng lúc.
"""

from __future__ import annotations

import pytest

from ryuu import Agent
from ryuu._testing.fakes import FakeLLMProvider


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


def _captured_messages(agent: Agent) -> list:
    """Extract messages from last CompletionRequest sent to fake LLM."""
    fake = agent._agent.llm  # type: ignore[attr-defined]
    assert isinstance(fake, FakeLLMProvider)
    assert fake.last_request is not None
    return list(fake.last_request.messages)


# ── system field replaces instructions ──────────────────────────────────────


async def test_system_field_becomes_system_message() -> None:
    """`system=` field flows into system message."""
    agent = Agent(model="gpt-4o-mini", system="You are a translator.")
    agent._agent.llm = FakeLLMProvider()  # type: ignore[attr-defined]

    await agent.run("Hello")
    msgs = _captured_messages(agent)
    assert msgs[0].role == "system"
    assert msgs[0].content == "You are a translator."


# ── user_template substitution ──────────────────────────────────────────────


async def test_user_template_substitutes_kwargs() -> None:
    """`user_template` filled với template vars qua .run(**kwargs)."""
    agent = Agent(
        model="gpt-4o-mini",
        system="You are a translator.",
        user_template="Translate to {lang}: {text}",
    )
    agent._agent.llm = FakeLLMProvider()  # type: ignore[attr-defined]

    await agent.run(lang="VN", text="Good morning")
    msgs = _captured_messages(agent)
    user_msg = next(m for m in msgs if m.role == "user")
    assert user_msg.content == "Translate to VN: Good morning"


# ── examples interleave as user/assistant pairs ─────────────────────────────


async def test_examples_interleave_before_real_user() -> None:
    """`examples` thành user/assistant messages, đặt trước real user query."""
    agent = Agent(
        model="gpt-4o-mini",
        system="You are a translator.",
        examples=[
            {"user": "Hello", "assistant": "Xin chào"},
            {"user": "Thanks", "assistant": "Cảm ơn"},
        ],
    )
    agent._agent.llm = FakeLLMProvider()  # type: ignore[attr-defined]

    await agent.run("Good morning")
    msgs = _captured_messages(agent)
    # Order: system, ex1_user, ex1_asst, ex2_user, ex2_asst, real_user
    assert [m.role for m in msgs] == [
        "system", "user", "assistant", "user", "assistant", "user",
    ]
    assert msgs[1].content == "Hello"
    assert msgs[2].content == "Xin chào"
    assert msgs[5].content == "Good morning"


# ── .run() splits reserved scope keys vs template vars ──────────────────────


async def test_run_separates_scope_kwargs_from_template_vars() -> None:
    """user_id/session_id/domain → ContextScope. Other kwargs → template vars."""
    agent = Agent(
        model="gpt-4o-mini",
        user_template="Hello {name}",
    )
    agent._agent.llm = FakeLLMProvider()  # type: ignore[attr-defined]

    # `name` is template var, `user_id` is scope kwarg
    result = await agent.run(name="World", user_id="u-42")
    msgs = _captured_messages(agent)
    user_msg = next(m for m in msgs if m.role == "user")
    assert user_msg.content == "Hello World"
    # Scope kwarg should NOT appear in template substitution
    assert "u-42" not in user_msg.content
    assert result is not None


# ── Validation: cannot mix Mode 1 and Mode 2 ────────────────────────────────


def test_validation_cannot_mix_instructions_and_system() -> None:
    """`instructions` (Mode 1) + `system` (Mode 2) → ValueError."""
    with pytest.raises(ValueError, match="instructions.*system|system.*instructions"):
        Agent(
            model="gpt-4o-mini",
            instructions="You are A",
            system="You are B",
        )


# ── Validation: malformed examples ──────────────────────────────────────────


def test_validation_example_missing_user_key() -> None:
    """Example item without `user` key → ValueError."""
    with pytest.raises(ValueError, match="example"):
        Agent(
            model="gpt-4o-mini",
            examples=[{"assistant": "Hi"}],  # missing "user"
        )


# ── Validation: .run() needs either message or template ─────────────────────


async def test_run_without_message_or_template_raises() -> None:
    """`.run()` no positional message + no user_template → ValueError."""
    agent = Agent(model="gpt-4o-mini", system="You are A")
    with pytest.raises(ValueError, match="message|user_template"):
        await agent.run()


# ── system optional with user_template ──────────────────────────────────────


async def test_user_template_without_system_works() -> None:
    """`user_template` set, no `system` → only user message in request."""
    agent = Agent(
        model="gpt-4o-mini",
        user_template="Echo: {text}",
    )
    agent._agent.llm = FakeLLMProvider()  # type: ignore[attr-defined]

    await agent.run(text="hi")
    msgs = _captured_messages(agent)
    # No system message
    assert all(m.role != "system" for m in msgs)
    user_msg = next(m for m in msgs if m.role == "user")
    assert user_msg.content == "Echo: hi"
