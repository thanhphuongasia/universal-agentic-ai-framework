# Cookbook: Flashcard System

> **Validates**: `EpisodicMemoryStore` + spaced repetition pattern
> **Complexity**: Intermediate — cần schedule + scoring nhưng không cần sandbox.

---

## Use Case

Hệ thống flashcard dạy ngôn ngữ / lập trình:
- User tạo card (question + answer)
- Agent review card theo thuật toán spaced repetition (SM-2 simplified)
- Agent score câu trả lời và điều chỉnh khoảng cách review tiếp theo

---

## Architecture

```
StudySession
  └─→ FlashcardAgent._execute()
        ├─→ EpisodicMemoryStore.retrieve()  # tìm card due for review
        ├─→ ILLMProvider.complete()          # generate hint hoặc evaluate answer
        ├─→ GroundTruthVerifier.verify()     # so sánh với correct answer
        └─→ EpisodicMemoryStore.store()      # update card với score mới
```

---

## Card Storage Pattern

UAAF không cung cấp sẵn card schema — product tự define. Pattern đề xuất: lưu card dưới dạng JSON string vào `EpisodicMemoryStore`, dùng `metadata` để track scheduling info.

```python
import json
from uaaf.knowledge.memory.episodic import EpisodicMemoryStore
from uaaf.runtime.context import ContextScope, ExecutionContext

store = EpisodicMemoryStore(max_entries=500)

async def add_card(store: EpisodicMemoryStore, user_id: str, card: dict) -> None:
    content = json.dumps({"q": card["question"], "a": card["answer"]})
    await store.store(
        key=f"card:{card['id']}",
        content=content,
        metadata={"due_date": card.get("due_date", ""), "ease": 2.5, "interval": 1},
    )
```

---

## Spaced Repetition Score Update

SM-2 simplified — tính interval tiếp theo dựa trên quality (0–5):

```python
def compute_next_interval(current_interval: float, ease: float, quality: int) -> tuple[float, float]:
    if quality < 3:
        # Failed — reset
        return 1.0, max(1.3, ease - 0.2)
    new_ease = ease + 0.1 - (5 - quality) * 0.08
    new_interval = current_interval * max(1.3, new_ease)
    return new_interval, new_ease
```

---

## Answer Evaluation với GroundTruthVerifier

```python
from uaaf.cognitive.verifiers.ground_truth import GroundTruthVerifier

verifier = GroundTruthVerifier(mode="word_overlap", threshold=0.6)

async def evaluate_answer(user_answer: str, correct_answer: str) -> bool:
    from uaaf.runtime.context import ContextScope, ExecutionContext
    ctx = ExecutionContext(
        scope=ContextScope(user_id="u1", session_id="s1", domain="flashcard"),
        correlation_id="c1",
    )
    result = await verifier.verify(
        output=user_answer,
        context=ctx,
        metadata={"reference": correct_answer},
    )
    return result.passed
```

`word_overlap` mode với threshold=0.6 nghĩa là: answer đúng nếu ≥60% keywords của correct answer xuất hiện trong user answer. Phù hợp cho open-ended recall (không cần exact match).

---

## FlashcardAgent

```python
import json
from dataclasses import dataclass, field

from uaaf._testing.fakes import FakeLLMProvider
from uaaf.execution.agent import AgentResult, BaseAgent, Task
from uaaf.knowledge.memory.episodic import EpisodicMemoryStore
from uaaf.observability.audit import AuditLogger
from uaaf.observability.cost import Cost, CostPolicy, CostTracker
from uaaf.observability.rate_limit import RateLimiter, RatePolicy
from uaaf.observability.tracer import Tracer
from uaaf.providers.llm import CompletionRequest, Message
from uaaf.runtime.context import ContextScope, ExecutionContext


@dataclass
class FlashcardAgent(BaseAgent):
    llm: FakeLLMProvider = field(default_factory=FakeLLMProvider)
    memory: EpisodicMemoryStore = field(default_factory=EpisodicMemoryStore)

    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        mode = task.payload.get("mode", "quiz")
        scope_key = context.scope.user_id

        if mode == "add":
            card = task.payload.get("card", {})
            content = json.dumps({"q": card.get("question", ""), "a": card.get("answer", "")})
            await self.memory.store(
                key=f"card:{card.get('id', 'unknown')}",
                content=content,
                metadata={"ease": 2.5, "interval": 1, "due_date": ""},
            )
            return AgentResult(
                task_id=task.task_id,
                output="Card added.",
                cost=Cost(input_tokens=0, output_tokens=0, usd=0.0, provider="fake", model="fake"),
            )

        # Quiz mode: find due cards, ask LLM to generate hint
        entries = await self.memory.retrieve(query="card", scope_key=scope_key, top_k=5)
        if not entries:
            return AgentResult(
                task_id=task.task_id,
                output="No cards due for review.",
                cost=Cost(input_tokens=0, output_tokens=0, usd=0.0, provider="fake", model="fake"),
            )

        card_data = json.loads(entries[0].content)
        req = CompletionRequest(
            messages=[
                Message(
                    role="system",
                    content="You are a flashcard tutor. Give a hint without revealing the answer.",
                ),
                Message(role="user", content=f"Question: {card_data['q']}"),
            ],
            model="gpt-4o-mini",
        )
        response = await self.llm.complete(req)
        return AgentResult(
            task_id=task.task_id,
            output=response.content,
            cost=Cost(input_tokens=30, output_tokens=15, usd=0.0, provider="fake", model="fake"),
        )
```

---

## Scheduled Batch Review

UAAF không có built-in scheduler — dùng cron job hoặc task queue của product:

```python
# Ví dụ: chạy mỗi ngày lúc 8 giờ sáng (APScheduler, Celery, hoặc cron)
# scheduler.add_job(daily_review, trigger="cron", hour=8)

async def daily_review(user_ids: list) -> None:
    for user_id in user_ids:
        scope = ContextScope(user_id=user_id, session_id="daily-review", domain="flashcard")
        ctx = ExecutionContext(scope=scope, correlation_id=f"review-{user_id}")
        agent = FlashcardAgent(
            agent_id="flashcard",
            cost_tracker=CostTracker(CostPolicy()),
            tracer=Tracer(),
            audit_logger=AuditLogger(),
            rate_limiter=RateLimiter(RatePolicy()),
        )
        task = Task(task_id=f"review-{user_id}", payload={"mode": "quiz"})
        result = await agent.execute(task, ctx)
        # send result to user via email/push notification
        print(f"User {user_id}: {result.output}")
```

---

## Production Checklist

- [ ] Persist `EpisodicMemoryStore` entries vào PostgreSQL/Redis giữa các sessions
- [ ] Implement proper SM-2 scheduling với `due_date` field trong metadata
- [ ] Batch process due cards với async concurrency (asyncio.gather)
- [ ] Add `LLMJudgeVerifier` cho subjective answers (code, essay) thay vì `word_overlap`
- [ ] Rate limit per user để tránh abuse: `RatePolicy(requests_per_minute=30)`
