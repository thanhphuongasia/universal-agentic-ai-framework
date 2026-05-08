# Tổng quan: 5 Design Patterns trong UAAF

UAAF triển khai 5 pattern thiết kế AI agent cổ điển. Mỗi pattern giải quyết một bài toán cụ thể
về cách tổ chức luồng xử lý LLM.

## Bảng so sánh

| # | Pattern | Điều kiện kích hoạt | Class chính | Use case tiêu biểu |
|---|---------|---------------------|-------------|-------------------|
| 1 | **Prompt Chaining** | `complexity >= MEDIUM` | `ReActStrategy` | Stock research nhiều bước; gỡ lỗi code |
| 2 | **Routing** | Mọi request | `StrategySelector` + `ModelRouter` | Todo Pro phân loại request; chọn model rẻ/mạnh |
| 3 | **Parallelization** | N task độc lập | `AgentPool.fan_out()` | Scan nhiều file Python; lấy giá 50 ticker |
| 4 | **Orchestrator-Worker** | `complexity=HIGH` + `len(entities)>1` | `ParallelFanoutStrategy` | Phân tích toàn codebase; generate flashcard nhiều chương |
| 5 | **Evaluator-Optimizer** | `complexity=HIGH` + chất lượng cao | `EvaluatorOptimizerStrategy` | Sinh flashcard có verify; trading signal đủ risk params |

## Import ngắn gọn

Hầu hết ví dụ chỉ cần 2 import:

```python
# Các type hay dùng nhất — đã export sẵn từ uaaf
from uaaf import (
    AgentPool, BaseAgent, AgentResult, Task,
    ExecutionContext, ContextScope, Cost,
    StructuredIntent, ComplexityLevel, ModelTier,
)

# Strategy cụ thể — import từ module tương ứng
from uaaf.cognitive.strategies.react import ReActStrategy
from uaaf.cognitive.strategies import ParallelFanoutStrategy, EvaluatorOptimizerStrategy
```

## Luồng dữ liệu tổng quát

```
User message
    │
    ▼
IIntentAnalyzer.analyze()
    │  → StructuredIntent(complexity, entities, suggested_strategy, suggested_model_tier)
    ▼
StrategySelector.select()          ← Pattern 2: Routing (chọn strategy)
    │  → ICognitiveStrategy
    │
    ├── ModelRouter.route(tier)    ← Pattern 2: Routing (chọn LLM)
    │  → ILLMProvider
    ▼
Strategy.execute(intent, context, agent_pool, verifier)
    ├── DirectStrategy             ← single-pass (baseline, LOW complexity)
    ├── ReActStrategy              ← Pattern 1: Prompt Chaining (MEDIUM+)
    ├── ParallelFanoutStrategy     ← Pattern 4: Orchestrator-Worker (HIGH + nhiều entity)
    └── EvaluatorOptimizerStrategy ← Pattern 5: Evaluator-Optimizer (HIGH, chất lượng cao)
    │
    │   (cả 3 và 4 dùng chung primitive)
    │   AgentPool.fan_out()        ← Pattern 3: Parallelization
    ▼
CognitiveResult(content, confidence, strategy_id)
```

## Quan hệ giữa các pattern

- **Routing** (Pattern 2) bao ngoài tất cả — `StrategySelector` quyết định pattern nào được gọi.
- **Prompt Chaining** (Pattern 1) là vòng lặp **tuần tự** — phù hợp khi bước sau cần bước trước.
- **Parallelization** (Pattern 3) là primitive cấp thấp — `AgentPool.fan_out()`.
- **Orchestrator-Worker** (Pattern 4) dùng Pattern 3 ở tầng trên — thêm phân rã và tổng hợp.
- **Evaluator-Optimizer** (Pattern 5) là vòng lặp **chất lượng** — generate → verify → refine, không song song.

## Chọn pattern nào?

```
Request đến
    │
    ├── Có nhiều entity độc lập cần xử lý song song?
    │   ├── Cần orchestrate + tổng hợp? → Pattern 4 (Orchestrator-Worker)
    │   └── Chỉ thuần fan_out?          → Pattern 3 (Parallelization)
    │
    ├── Output cần đạt chất lượng cao + có thể verify tự động?
    │   └── → Pattern 5 (Evaluator-Optimizer)
    │
    ├── Bước sau phụ thuộc bước trước (không song song được)?
    │   └── → Pattern 1 (Prompt Chaining)
    │
    └── Request đơn giản, 1 lần gọi LLM là đủ?
        └── → DirectStrategy (Pattern 2 tự chọn)
```

## File tham khảo nhanh

| Class | File |
|-------|------|
| `ReActStrategy` | `uaaf/cognitive/strategies/react.py` |
| `StrategySelector` | `uaaf/intent/selector.py` |
| `ModelRouter` | `uaaf/providers/router.py` |
| `AgentPool` | `uaaf/execution/pool.py` |
| `ParallelFanoutStrategy` | `uaaf/cognitive/strategies/parallel.py` |
| `ISubtaskBuilder` / `EntitySubtaskBuilder` | `uaaf/cognitive/strategies/parallel.py` |
| `EvaluatorOptimizerStrategy` | `uaaf/cognitive/strategies/evaluator_optimizer.py` |
| `VerifierPipeline` | `uaaf/cognitive/verifiers/pipeline.py` |
| `BaseAgent` / `AgentResult` / `Task` | `uaaf/execution/agent.py` (re-exported từ `uaaf`) |
| `ExecutionContext` / `ContextScope` | `uaaf/runtime/context.py` (re-exported từ `uaaf`) |
