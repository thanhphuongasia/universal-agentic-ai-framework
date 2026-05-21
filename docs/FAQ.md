# RYUU FAQ

> Câu hỏi thường gặp khi thiết kế hệ thống với RYUU. Mỗi entry trả lời ngắn ở đầu, chi tiết bên dưới.

## Mục Lục

- [Guardrail & Reasoning: Riêng hay Kết Hợp với Hook?](#guardrail--reasoning-riêng-hay-kết-hợp-với-hook)

---

## Guardrail & Reasoning: Riêng hay Kết Hợp với Hook?

**Trả lời ngắn:** Cả hai. Có **default standalone tier**, nhưng có thể **wrap/extend qua hook** khi muốn custom.

### 1. Standalone (Default) — Khuyến nghị

Mỗi cái có vị trí cố định trong request flow, chạy tự động:

```
User input
    ↓
[Hook: pre_execute]            ← user hooks fire
    ↓
[Guardrail: Input check]       ← standalone tier (Phase 2)
    │  BLOCK → return ngay, không tới LLM
    ↓
[Hook: pre_llm]                ← user hooks fire
    ↓
LLM call
    ↓
[Hook: post_llm]
    ↓
[Verifier Pipeline]            ← standalone tier
    Schema → LLMJudge → GroundTruth → Reasoning(Z3)
    │  FAIL → EvaluatorStrategy refine + retry
    ↓
[Guardrail: Output check]      ← standalone tier
    │  BLOCK/REDACT
    ↓
[Hook: post_execute]
    ↓
Response
```

**Lý do tách riêng:**
- **Guardrail** có semantic `action: PASS|BLOCK|REDACT|WARN` — hook chỉ có raise/return
- **Reasoning verifier** có retry loop qua `EvaluatorStrategy` — hook không có
- Người không hiểu hook vẫn dùng được (chỉ pass config)

### 2. Kết Hợp Hook (Advanced) — Khi Cần Custom

Hook là **escape hatch** khi standalone không đủ:

#### Case A: Custom guardrail logic không có sẵn

```python
async def custom_brand_guard(ctx: PostLLMContext) -> None:
    """Block nếu output mention đối thủ."""
    if "competitor_X" in ctx.response.content.lower():
        raise GuardrailBlockedError("Brand policy violation")

agent = Agent(
    model="gpt-4o",
    # Standalone guardrail vẫn chạy (PII, injection)
    guardrails=["pii", "injection"],
    # + custom logic qua hook
    hooks={"post_llm": [custom_brand_guard]},
)
```

#### Case B: Inject reasoning vào điểm khác (không phải verifier tier)

Mặc định reasoning chạy ở verifier tier (sau Cognitive). Nếu muốn check **trước** tool execution:

```python
async def pre_tool_z3_check(ctx: PreToolContext) -> None:
    """Check Z3 constraint trước khi gọi tool buy()."""
    if ctx.tool_name == "buy":
        result = await z3_verify(ctx.args, constraints)
        if not result.passed:
            raise ConstraintViolation(result.counterexample)

agent = Agent(
    model="gpt-4o",
    tools=[buy, sell],
    hooks={"pre_tool": [pre_tool_z3_check]},  # reasoning AT TOOL CALL, not after LLM
)
```

#### Case C: Hook fires → log guardrail/reasoning result vào metric

```python
async def metric_collector(ctx: OnGuardrailContext) -> None:
    """Hook on_guardrail_blocked → emit Prometheus counter."""
    prometheus.counter("guardrail_blocks").labels(reason=ctx.reason).inc()

agent = Agent(
    model="gpt-4o",
    guardrails=["pii", "topic"],
    hooks={"on_guardrail_blocked": [metric_collector]},  # parallel mode, fire-and-forget
)
```

### 3. Decision Matrix — Khi Nào Dùng Gì

| Tình huống | Dùng gì |
|---|---|
| PII/injection/topic filter chuẩn | Standalone `guardrails=[...]` |
| Z3 constraint sau LLM output | Standalone `verifiers=["formal"]` |
| Custom block logic (brand, domain-specific rule) | **Hook** `post_llm` hoặc `post_execute` |
| Inject reasoning ở giữa tool call | **Hook** `pre_tool` |
| Log/metric khi guardrail trigger | **Hook** `on_guardrail_blocked` (parallel mode) |
| Approval workflow trước action quan trọng | **Hook** `pre_tool` (raise PendingApproval) |
| Multi-stage verification (LLM judge + Z3 + custom) | Standalone `verifiers=[...]` (pipeline tự compose) |

### 4. Quy Tắc Vàng

```
Standalone tier = "default behavior, config-driven"
Hook            = "custom behavior, code-driven"

Nếu bạn cần ghi config → standalone
Nếu bạn cần viết Python → hook
```

**Tránh nhầm lẫn:** Đừng implement guardrail/reasoning **chỉ bằng hook** — sẽ mất semantic (retry loop, action enum, confidence). Hook **bổ sung**, không **thay thế**.

### Liên Quan

- Hook system: `docs/guides/hooks.md`, kiến trúc §7.5
- Guardrail tier: kiến trúc §6
- Reasoning tier (Z3/Prolog): kiến trúc §7.8
- Verifier pipeline: kiến trúc §5 (Cognitive Tier)

---

*Khi gặp câu hỏi tương tự, thêm entry mới phía dưới. Mỗi entry: tóm tắt 1 câu → chi tiết → references.*
