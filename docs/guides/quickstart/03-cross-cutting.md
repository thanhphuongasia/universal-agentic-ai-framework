# Cross-Cutting — Observability / Hooks / Reasoning

← [Quickstart Index](README.md) | [All guides](../)

> Bật/tắt cost tracker, audit log, tracer, rate limiter, hooks, reasoning verifier. Default OFF (NullObject), opt-in qua kwarg.

---

## 3. Cross-cutting Features — Bật/Tắt

Tất cả 3 mục dưới đây áp dụng cho **cả Factory và Class-based**. Factory dùng kwarg đơn giản, class-based inject constructor.

### 3.1 Observability — Default OFF, Opt-in

NullObject pattern: không khai báo = không log, không track, không trace, không rate-limit. Zero overhead.

**Factory (🔲 planned):**

```python
from ryuu import Agent

# Hoàn toàn OFF — chỉ chat, không observability
agent = Agent(model="gpt-4o-mini")

# Bật từng cái khi cần
agent = Agent(
    model="gpt-4o-mini",
    budget_usd=1.0,        # ON: CostTracker enforce $1/session
    rate_limit_rps=10,     # ON: TokenBucketRateLimiter
    audit=True,            # ON: AuditLogger ghi JSONL hash chain
    trace=True,            # ON: OTel Tracer spans
)
```

**Class-based (✅ available now):**

```python
from ryuu_execution.agent import BaseAgent
from ryuu_observability.cost import RealCostTracker, CostPolicy
from ryuu_observability.audit import FileAuditLogger
from ryuu_observability.tracer import OTelTracer
from ryuu_observability.rate_limit import TokenBucketRateLimiter

# Hoàn toàn OFF
agent = MyAgent(agent_id="lean")    # 4 NullObject defaults

# Bật từng cái
agent = MyAgent(
    agent_id="prod",
    cost_tracker=RealCostTracker(CostPolicy(max_usd_per_session=1.0)),
    audit_logger=FileAuditLogger(path="./audit.jsonl"),
    tracer=OTelTracer(),
    rate_limiter=TokenBucketRateLimiter(rps=10),
)
```

**Async guarantee (🔲 Phase 8.8):** Tất cả 4 cross-cutting đảm bảo non-blocking dưới 10k QPS. Verify qua stress test (xem architecture §7.6).

---

### 3.2 Hooks — Dynamic Lifecycle Injection (🔲 Phase 9)

Hook = inject Python callable vào event lifecycle mà không cần subclass. Lấy cảm hứng từ Claude Agent SDK.

**Lifecycle events:**

```
pre_execute → pre_llm → post_llm → pre_tool → post_tool → post_execute → on_complete
                                                                          (+ on_error,
                                                                           on_budget_exceeded,
                                                                           on_rate_limited)
```

**Ví dụ — PII scrub trước tool call (🔲 Phase 9):**

```
from ryuu import Agent
from ryuu.hooks import PreToolContext

async def pii_scrub(ctx: PreToolContext) -> PreToolContext:
    """Replace email/SSN trong args trước khi gửi tool."""
    return ctx.replace(args=scrub_pii(ctx.args))

agent = Agent(
    model="gpt-4o",
    tools=[lookup_customer],
    hooks={"pre_tool": [pii_scrub]},
)
```

**Ví dụ — block refund > $1000:**

```python
async def refund_guard(ctx: PostToolContext) -> None:
    if ctx.tool_name == "process_refund" and ctx.result["amount"] > 1000:
        raise PermissionError(f"Refund ${ctx.result['amount']} cần approval thủ công")

agent = Agent(model="gpt-4o", tools=[process_refund], hooks={"post_tool": [refund_guard]})
```

**Modes:**
- `sequential` (default): handler chạy nối tiếp, raise → block lifecycle
- `parallel`: fire-and-forget, swallow exception (cho metrics)

📖 Chi tiết: [hooks.md](hooks.md) — 7 cookbook recipes, registration styles.

**So sánh Hook vs Verifier vs Guardrail:**

| Cơ chế | Khi nào | Có retry loop? |
|---|---|---|
| Hook | Bất cứ event nào | Không |
| Verifier | Sau LLM output | Có (EvaluatorStrategy refines) |
| Guardrail | Input + Output | Không (BLOCK ngay) |

---

### 3.3 Reasoning — Formal Verifier (🔲 Phase 14)

Khi LLM output cần **proof** thay vì "có vẻ đúng". Plug vào VerifierPipeline như tier thứ 4.

**Use case:**

```
from ryuu import Agent

# Trading bot — constraint formal hoá được
agent = Agent(
    model="gpt-4o",
    tools=[buy, sell],
    verifiers=["schema", "formal"],     # thêm "formal" → kéo ryuu-reasoning
    reasoning={
        "z3_constraints": """
            (assert (<= position_size 10000))
            (assert (>= cash_reserve 5000))
            (assert (<= correlation 0.5))
        """,
    },
)

result = await agent.run("Buy 100 AAPL at $150")
# Z3 check: 100 * 150 = $15000 > $10000 limit → fail
# EvaluatorStrategy refine: "Reduce to 60 shares ($9000)"
```

**Khi nào dùng:**
- ✅ High-stakes: trading, medical, legal, compliance
- ✅ Constraint formal hoá được (số, rule, pattern)
- ❌ Free-form output (essay, code) → dùng LLMJudge

**Cognitive ≠ Reasoning:**

| | `ryuu-cognitive` (ReAct/CoT) | `ryuu-reasoning` (Z3/Prolog) |
|---|---|---|
| Vai trò | LLM *generate* decision | Solver *verify* decision |
| Logic | Soft (probabilistic) | Hard (mathematical proof) |
| Khi nào | Lúc agent đang nghĩ | Sau khi agent ra quyết định |

Reasoning chạy **sau** Cognitive, không thay thế.

📖 Chi tiết: [Architecture §7.8](../architecture/uaaf-v2-architecture.md#78-reasoning-tier--ryuu-reasoning-rev-3-phase-14).

---

