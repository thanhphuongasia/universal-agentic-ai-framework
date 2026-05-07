# Cookbook: Stock Trading System

> **Validates**: `AuditLogger` + `GroundTruthVerifier` + trust=HIGH patterns
> **Complexity**: Advanced — use case có impact tài chính, cần audit trail + verifier pipeline bắt buộc.

---

## Use Case

Hệ thống trading signal analysis (paper trading mode):
- Nhận market data / news
- AI phân tích và generate trade signal (BUY/SELL/HOLD)
- **Verify signal** trước khi execute (KHÔNG execute dựa trên raw LLM output)
- Log tất cả quyết định vào audit trail (7-year retention requirement)

> ⚠️ **Paper trading only**: Cookbook này không bao gồm `place_order()` thật.
> Integrate với broker API là responsibility của product team.

---

## Architecture

```
MarketData / News
  └─→ TradingAgent._execute()
        ├─→ GraphBackbone.write()          # lưu market context vào knowledge graph
        ├─→ ContextAssembler.assemble()    # lấy relevant context
        ├─→ ILLMProvider.complete()        # generate trade signal
        ├─→ VerifierPipeline.verify()      # validate signal (schema + ground truth)
        ├─→ AuditLogger.log()              # log decision (automatic via BaseAgent)
        └─→ Return signal (NOT execute)
```

---

## trust=HIGH: Mandatory Verifier Pipeline

Với trading system, **không bao giờ skip verifier**. Ít nhất phải có:

```python
from uaaf.cognitive.verifiers.pipeline import PipelineMode, VerifierPipeline
from uaaf.cognitive.verifiers.schema import SchemaVerifier
from uaaf.cognitive.verifiers.ground_truth import GroundTruthVerifier

signal_verifier = VerifierPipeline(
    verifiers=[
        # 1. Output phải có đúng format JSON
        SchemaVerifier(
            required_keys=["signal", "confidence", "reasoning"],
            output_must_be_json=True,
        ),
        # 2. Signal chỉ được là một trong 3 giá trị hợp lệ
        GroundTruthVerifier(mode="substring", threshold=0.0),
    ],
    mode=PipelineMode.ALL_PASS,  # CẢ HAI phải pass
)
```

---

## AuditLogger — 7-Year Retention

`AuditLogger` dùng SHA-256 hash chain JSONL backend — mỗi entry hash của entry trước, tamper-detectable. `BaseAgent` tự gọi `audit_logger.log()` ở mỗi `execute()` — không cần gọi thủ công.

```python
from uaaf.observability.audit import AuditLogger

# Default: in-memory (cho testing)
audit = AuditLogger()

# Production: trỏ tới append-only storage
# audit = AuditLogger(log_path="/var/log/uaaf/trading-audit.jsonl")
```

Để đảm bảo 7-year retention:
- Mount `log_path` vào immutable object storage (S3 với Object Lock, GCS với retention policy)
- Không bao giờ delete/overwrite JSONL files
- Backup daily, verify hash chain integrity monthly

---

## TradingAgent

```python
import json
from dataclasses import dataclass, field

from uaaf._testing.fakes import FakeLLMProvider
from uaaf.cognitive.verifiers.pipeline import PipelineMode, VerifierPipeline
from uaaf.cognitive.verifiers.schema import SchemaVerifier
from uaaf.execution.agent import AgentResult, BaseAgent, Task
from uaaf.knowledge.context_assembler import ContextAssembler
from uaaf.knowledge.graph.backbone import GraphBackbone
from uaaf.observability.audit import AuditLogger
from uaaf.observability.cost import Cost, CostPolicy, CostTracker
from uaaf.observability.rate_limit import RateLimiter, RatePolicy
from uaaf.observability.tracer import Tracer
from uaaf.providers.llm import CompletionRequest, Message
from uaaf.runtime.context import ContextScope, ExecutionContext


@dataclass
class TradingAgent(BaseAgent):
    llm: FakeLLMProvider = field(default_factory=FakeLLMProvider)
    assembler: ContextAssembler = field(
        default_factory=lambda: ContextAssembler(GraphBackbone())
    )
    signal_verifier: VerifierPipeline = field(
        default_factory=lambda: VerifierPipeline(
            verifiers=[SchemaVerifier(required_keys=["signal", "confidence", "reasoning"])],
            mode=PipelineMode.ALL_PASS,
        )
    )

    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        ticker = str(task.payload.get("ticker", "AAPL"))
        market_data = str(task.payload.get("market_data", ""))
        scope_key = f"trading:{ticker}"

        # 1. Lưu market data vào graph knowledge base
        await self.assembler.write(
            observation=f"[{ticker}] {market_data}",
            scope_key=scope_key,
        )

        # 2. Lấy recent context cho ticker này
        assembled = await self.assembler.assemble(
            query=ticker,
            scope_key=scope_key,
            budget_tokens=2000,
        )

        # 3. Generate signal
        system_prompt = """You are a trading signal analyst.
Respond ONLY with valid JSON: {"signal": "BUY|SELL|HOLD", "confidence": 0.0-1.0, "reasoning": "..."}
Do not include any text outside the JSON."""

        req = CompletionRequest(
            messages=[
                Message(role="system", content=system_prompt),
                Message(
                    role="user",
                    content=f"Ticker: {ticker}\nContext:\n{assembled.text}",
                ),
            ],
            model="gpt-4o",  # dùng STANDARD tier cho trading signal
        )
        response = await self.llm.complete(req)

        # 4. Verify signal — BẮTBUỘC
        verification = await self.signal_verifier.verify(
            output=response.content,
            context=context,
        )

        if not verification.passed:
            return AgentResult(
                task_id=task.task_id,
                output=json.dumps({
                    "signal": "HOLD",
                    "confidence": 0.0,
                    "reasoning": f"Signal failed verification: {verification.feedback}",
                    "verified": False,
                }),
                cost=Cost(
                    input_tokens=100, output_tokens=20, usd=0.002, provider="fake", model="fake"
                ),
            )

        # 5. Return verified signal (KHÔNG execute trade ở đây)
        signal_data = json.loads(response.content)
        signal_data["verified"] = True
        return AgentResult(
            task_id=task.task_id,
            output=json.dumps(signal_data),
            cost=Cost(
                input_tokens=100, output_tokens=50, usd=0.003, provider="fake", model="fake"
            ),
        )
```

---

## Signal → Execution Separation

**Framework responsibility**: generate + verify signal.
**Product responsibility**: decide whether to execute.

```python
# Product code (KHÔNG trong framework):
async def process_signal(signal_json: str) -> None:
    signal = json.loads(signal_json)
    if signal["verified"] and signal["confidence"] >= 0.8:
        # Chỉ execute khi confidence cao VÀ đã verified
        # await broker_api.place_order(...)  # paper trading hoặc thật
        pass
```

---

## Cost Budget cho Trading

Trading có thể tốn nhiều token — cần budget chặt chẽ:

```python
from uaaf.observability.cost import CostPolicy, CostTracker

trading_policy = CostPolicy(
    per_user_per_day_usd=5.0,       # mỗi trader tối đa $5/ngày
    per_domain_per_month_usd=500.0, # toàn trading domain tối đa $500/tháng
    global_per_hour_usd=50.0,       # spike protection
)
tracker = CostTracker(trading_policy)
```

---

## Audit Trail Verification

Sau mỗi tháng, verify hash chain integrity:

```python
from uaaf.observability.audit import AuditLogger

async def verify_audit_chain(log_path: str) -> bool:
    audit = AuditLogger(log_path=log_path)
    is_valid = await audit.verify_chain()
    if not is_valid:
        raise RuntimeError(f"AUDIT CHAIN TAMPERED: {log_path}")
    return True
```

---

## Production Checklist

- [ ] `AuditLogger` trỏ tới append-only object storage với retention lock
- [ ] Verify audit chain integrity hàng tháng (cron job)
- [ ] `VerifierPipeline` với `ALL_PASS` — không skip verifier dù timeout
- [ ] Signal execution phân tách khỏi signal generation (separate service)
- [ ] Alerting khi confidence < 0.7 (nhiều HOLD signal liên tiếp = model degraded)
- [ ] `GraphBackbone` backed bởi persistent graph DB (Neo4j) cho historical context
- [ ] Paper trading mode trước khi go live — verify metric equivalence
- [ ] Circuit breaker cho LLM provider: `failure_threshold=2, recovery_timeout=60`
