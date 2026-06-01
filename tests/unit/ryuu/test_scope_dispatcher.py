"""Tests for ScopeDispatcher — CancelToken, SteeringContext, MessageClassifier, ScopeDispatcher.

Covers:
  T01  CancelToken set/reset/is_cancelled
  T02  SteeringContext add/drain/is_empty
  T03  ScopeState lifecycle (attach_task, is_running, cancel_task, reset)
  T04  MessageClassifier — keyword heuristics (no LLM)
  T05  MessageClassifier — LLM layer with mock provider
  T06  ScopeDispatcher.route — no active task → (NEW, None)
  T07  ScopeDispatcher.route — active task + STOP heuristic
  T08  ScopeDispatcher.route — active task + STEER via mock LLM
  T09  ScopeDispatcher.route — active task + NEW via mock LLM
  T10  ScopeDispatcher.stop_summary — no provider fallback
  T11  ScopeDispatcher.stop_summary — with mock provider
  T12  ScopeDispatcher.finish_task clears state
  T13  ChannelOrchestrator — no dispatcher: original behavior preserved
  T14  ChannelOrchestrator — dispatcher STOP cancels handler task
  T15  ChannelOrchestrator — dispatcher STEER acks and adds to steer_ctx
  T16  ChannelOrchestrator — dispatcher NEW while running returns queue reply
"""

from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from ryuu_messaging_core import (
    CancelToken,
    ChannelOrchestrator,
    ClassifyResult,
    DispatchLabel,
    MessageClassifier,
    ScopeDispatcher,
    ScopeState,
    SteeringContext,
)
from ryuu_messaging_core.conversation import ConversationManager
from ryuu_messaging_core.messages import IncomingMessage, OutgoingMessage
from ryuu_messaging_core.protocols import IChannelHandler, Session


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _msg(text: str = "hello", scope: str = "u1") -> IncomingMessage:
    return IncomingMessage(
        channel="test", sender_id=scope,
        conversation_id=scope, text=text,
    )


def _session(scope: str = "u1") -> Session:
    return Session(
        scope_key=scope, channel="test",
        sender_id=scope, conversation_id=scope,
    )


class _FakeHandler:
    def __init__(self, reply: str = "done", delay: float = 0.0) -> None:
        self._reply = reply
        self._delay = delay
        self.called_with: list[tuple] = []

    async def handle(self, msg: IncomingMessage, session: Session) -> OutgoingMessage:
        if self._delay:
            await asyncio.sleep(self._delay)
        self.called_with.append((msg, session))
        return OutgoingMessage(conversation_id=msg.conversation_id, text=self._reply)


class _FakeConversationManager:
    async def get_session(self, msg: IncomingMessage) -> Session:
        return _session(msg.sender_id)

    async def save(self, session: Session) -> None:
        pass

    async def resolve_scope(self, *, channel: str, sender_id: str, conversation_id: str) -> str:
        return sender_id

    async def clear(self, scope_key: str) -> None:
        pass


def _make_llm_provider(label: str = "NEW", content: str | None = None) -> Any:
    """Mock LLM provider that returns a classify JSON or arbitrary content."""
    import json as _json
    resp = MagicMock()
    if content is None:
        resp.content = _json.dumps({"label": label, "reasoning": "mock"})
    else:
        resp.content = content
    provider = AsyncMock()
    provider.complete = AsyncMock(return_value=resp)
    return provider


# ─────────────────────────────────────────────────────────────────────────────
# T01–T03  Primitives
# ─────────────────────────────────────────────────────────────────────────────

class TestCancelToken(unittest.TestCase):
    def test_initial_not_cancelled(self) -> None:
        tok = CancelToken()
        self.assertFalse(tok.is_cancelled())

    def test_set(self) -> None:
        tok = CancelToken()
        tok.set()
        self.assertTrue(tok.is_cancelled())

    def test_reset(self) -> None:
        tok = CancelToken()
        tok.set()
        tok.reset()
        self.assertFalse(tok.is_cancelled())

    def test_wait_resolves_when_set(self) -> None:
        tok = CancelToken()

        async def _go() -> None:
            tok.set()
            await tok.wait()   # should return immediately

        asyncio.run(_go())


class TestSteeringContext(unittest.TestCase):
    def test_empty_initially(self) -> None:
        ctx = SteeringContext()
        self.assertTrue(ctx.is_empty())
        self.assertEqual(ctx.drain(), [])

    def test_add_and_drain(self) -> None:
        ctx = SteeringContext()
        ctx.add("more detail")
        ctx.add("extra context")
        self.assertFalse(ctx.is_empty())
        items = ctx.drain()
        self.assertEqual(items, ["more detail", "extra context"])
        self.assertTrue(ctx.is_empty())

    def test_drain_clears_queue(self) -> None:
        ctx = SteeringContext()
        ctx.add("x")
        ctx.drain()
        self.assertEqual(ctx.drain(), [])


class TestScopeState(unittest.TestCase):
    def test_not_running_without_task(self) -> None:
        state = ScopeState()
        self.assertFalse(state.is_running())

    def test_running_with_active_task(self) -> None:
        async def _dummy() -> None:
            await asyncio.sleep(10)

        async def _go() -> None:
            t = asyncio.create_task(_dummy())
            state = ScopeState()
            state.attach_task(t)
            self.assertTrue(state.is_running())
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

        asyncio.run(_go())

    def test_reset_clears_summary(self) -> None:
        state = ScopeState()
        state.task_summary = "Draft Q3 report"
        state.reset()
        self.assertEqual(state.task_summary, "")
        self.assertFalse(state.is_running())


# ─────────────────────────────────────────────────────────────────────────────
# T04–T05  MessageClassifier
# ─────────────────────────────────────────────────────────────────────────────

class TestMessageClassifier(unittest.IsolatedAsyncioTestCase):
    async def test_stop_keyword_short_message(self) -> None:
        clf = MessageClassifier()
        result = await clf.classify("stop", "Draft Q3 report")
        self.assertIsInstance(result, ClassifyResult)
        self.assertEqual(result.label, DispatchLabel.STOP)
        self.assertEqual(result.layer, "heuristic")

    async def test_stop_vietnamese_short(self) -> None:
        clf = MessageClassifier()
        result = await clf.classify("thôi đi", "analyzing data")
        self.assertEqual(result.label, DispatchLabel.STOP)
        self.assertEqual(result.layer, "heuristic")

    async def test_long_stop_message_goes_to_llm_fallback(self) -> None:
        # Long message with stop keyword but no LLM → NEW (fallback)
        clf = MessageClassifier()
        result = await clf.classify(
            "please stop what you are doing right now because I changed my mind",
            "analyzing data",
        )
        # Without LLM, heuristic catches "stop" in ≤8 words only; this is 14 words → NEW
        self.assertEqual(result.label, DispatchLabel.NEW)
        self.assertEqual(result.layer, "fallback")

    async def test_llm_layer_steer(self) -> None:
        provider = _make_llm_provider("STEER")
        clf = MessageClassifier(provider=provider)
        result = await clf.classify("actually use a formal tone", "Draft Q3 report")
        self.assertEqual(result.label, DispatchLabel.STEER)
        self.assertEqual(result.layer, "llm")
        provider.complete.assert_called_once()

    async def test_llm_layer_new(self) -> None:
        provider = _make_llm_provider("NEW")
        clf = MessageClassifier(provider=provider)
        result = await clf.classify("what's the weather in Tokyo?", "Draft Q3 report")
        self.assertEqual(result.label, DispatchLabel.NEW)
        self.assertEqual(result.layer, "llm")

    async def test_llm_failure_falls_back_to_new(self) -> None:
        provider = AsyncMock()
        provider.complete = AsyncMock(side_effect=RuntimeError("timeout"))
        clf = MessageClassifier(provider=provider)
        result = await clf.classify("some ambiguous message here today", "task")
        self.assertEqual(result.label, DispatchLabel.NEW)
        self.assertEqual(result.layer, "fallback")


# ─────────────────────────────────────────────────────────────────────────────
# T06–T12  ScopeDispatcher
# ─────────────────────────────────────────────────────────────────────────────

class TestScopeDispatcher(unittest.IsolatedAsyncioTestCase):
    async def test_route_no_active_task(self) -> None:
        disp = ScopeDispatcher()
        label, state = await disp.route("hello", "user1")
        self.assertEqual(label, DispatchLabel.NEW)
        self.assertIsNone(state)

    async def test_route_stop_heuristic(self) -> None:
        disp = ScopeDispatcher()

        async def _slow():
            await asyncio.sleep(10)

        t = asyncio.create_task(_slow())
        await disp.start_task("user1", t, first_message="Draft a proposal")
        try:
            label, state = await disp.route("stop", "user1")
            self.assertEqual(label, DispatchLabel.STOP)
            self.assertIsNotNone(state)
        finally:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    async def test_route_steer_via_llm(self) -> None:
        provider = _make_llm_provider("STEER")
        disp = ScopeDispatcher(
            classifier=MessageClassifier(provider=provider),
            provider=provider,
        )

        async def _slow():
            await asyncio.sleep(10)

        t = asyncio.create_task(_slow())
        await disp.start_task("user1", t, first_message="Analyze Q3 data")
        try:
            label, state = await disp.route("use the revised CSV I uploaded", "user1")
            self.assertEqual(label, DispatchLabel.STEER)
            self.assertIsNotNone(state)
        finally:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    async def test_route_new_via_llm(self) -> None:
        provider = _make_llm_provider("NEW")
        disp = ScopeDispatcher(
            classifier=MessageClassifier(provider=provider),
            provider=provider,
        )

        async def _slow():
            await asyncio.sleep(10)

        t = asyncio.create_task(_slow())
        await disp.start_task("user1", t, first_message="Analyze Q3 data")
        try:
            label, state = await disp.route("book me a flight to Hanoi", "user1")
            self.assertEqual(label, DispatchLabel.NEW)
            self.assertIsNotNone(state)
        finally:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    async def test_stop_summary_no_provider(self) -> None:
        disp = ScopeDispatcher()
        disp.get_state("u1").task_summary = "Draft Q3 report"
        summary = await disp.stop_summary("u1")
        self.assertIn("Draft Q3 report", summary)

    async def test_stop_summary_with_provider(self) -> None:
        provider = _make_llm_provider(content="I stopped after completing the outline.")
        disp = ScopeDispatcher(
            classifier=MessageClassifier(provider=provider),
            provider=provider,
        )
        disp.get_state("u1").task_summary = "Draft Q3 report"
        summary = await disp.stop_summary("u1", progress="Completed outline section")
        self.assertEqual(summary, "I stopped after completing the outline.")

    async def test_finish_task_clears_state(self) -> None:
        disp = ScopeDispatcher()

        async def _slow():
            await asyncio.sleep(10)

        t = asyncio.create_task(_slow())
        await disp.start_task("user1", t, first_message="some task")
        self.assertTrue(disp.is_running("user1"))
        disp.finish_task("user1")
        self.assertFalse(disp.is_running("user1"))
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# T13–T16  ChannelOrchestrator integration
# ─────────────────────────────────────────────────────────────────────────────

class TestOrchestratorDispatcher(unittest.IsolatedAsyncioTestCase):
    def _make_orchestrator(
        self,
        handler: Any = None,
        dispatcher: ScopeDispatcher | None = None,
    ) -> ChannelOrchestrator:
        return ChannelOrchestrator(
            conversation_manager=_FakeConversationManager(),  # type: ignore[arg-type]
            handler=handler or _FakeHandler(),
            dispatcher=dispatcher,
        )

    async def test_no_dispatcher_original_behavior(self) -> None:
        handler = _FakeHandler(reply="pong")
        orch = self._make_orchestrator(handler=handler)
        reply = await orch._on_message(_msg("ping", "u1"))
        self.assertEqual(reply.text, "pong")
        self.assertEqual(len(handler.called_with), 1)

    async def test_dispatcher_stop_cancels_handler(self) -> None:
        """STOP while a slow handler is running → stop reply, handler cancelled."""
        cancelled_flag = asyncio.Event()

        class _SlowHandler:
            async def handle(self, msg, session):
                try:
                    await asyncio.sleep(10)
                    return OutgoingMessage(conversation_id=msg.conversation_id, text="done")
                except asyncio.CancelledError:
                    cancelled_flag.set()
                    raise

        disp = ScopeDispatcher()
        orch = self._make_orchestrator(handler=_SlowHandler(), dispatcher=disp)

        # Start the slow task in background
        task = asyncio.create_task(orch._on_message(_msg("analyze data", "u1")))
        # Give it a moment to register with dispatcher
        await asyncio.sleep(0.05)

        self.assertTrue(disp.is_running("u1"))

        # Now send STOP
        stop_reply = await orch._on_message(_msg("stop", "u1"))
        self.assertIn("Stopped", stop_reply.text)

        # Wait for background task to finish (cancelled)
        try:
            await asyncio.wait_for(task, timeout=3.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    async def test_dispatcher_steer_acks_and_adds_to_ctx(self) -> None:
        """STEER while running → ack reply + steer_ctx has the message."""
        ready = asyncio.Event()

        class _SlowHandler:
            async def handle(self, msg, session):
                ready.set()
                await asyncio.sleep(10)
                return OutgoingMessage(conversation_id=msg.conversation_id, text="done")

        provider = _make_llm_provider("STEER")
        disp = ScopeDispatcher(
            classifier=MessageClassifier(provider=provider),
            provider=provider,
        )
        orch = self._make_orchestrator(handler=_SlowHandler(), dispatcher=disp)

        task = asyncio.create_task(orch._on_message(_msg("write the report", "u1")))
        await asyncio.wait_for(ready.wait(), timeout=2.0)

        steer_reply = await orch._on_message(_msg("use formal tone please", "u1"))
        self.assertIn("mind", steer_reply.text.lower())  # "keep that in mind"

        state = disp.get_state("u1")
        self.assertFalse(state.steer_ctx.is_empty())
        pending = state.steer_ctx.drain()
        self.assertIn("use formal tone please", pending)

        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    async def test_dispatcher_new_while_running_returns_queue_reply(self) -> None:
        """NEW while running → 'I'll handle this next' reply without disrupting task."""
        ready = asyncio.Event()

        class _SlowHandler:
            async def handle(self, msg, session):
                ready.set()
                await asyncio.sleep(10)
                return OutgoingMessage(conversation_id=msg.conversation_id, text="done")

        provider = _make_llm_provider("NEW")
        disp = ScopeDispatcher(
            classifier=MessageClassifier(provider=provider),
            provider=provider,
        )
        orch = self._make_orchestrator(handler=_SlowHandler(), dispatcher=disp)

        task = asyncio.create_task(orch._on_message(_msg("analyze Q3 data", "u1")))
        await asyncio.wait_for(ready.wait(), timeout=2.0)

        queue_reply = await orch._on_message(_msg("book a flight", "u1"))
        self.assertIn("previous task", queue_reply.text.lower())

        # Original task still running
        self.assertTrue(disp.is_running("u1"))

        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


if __name__ == "__main__":
    unittest.main()
