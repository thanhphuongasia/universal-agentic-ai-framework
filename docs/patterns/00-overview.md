# Tổng quan: 5 Design Patterns trong UAAF

UAAF (Universal Agentic AI Framework) triển khai 5 pattern thiết kế AI agent cổ điển.
Mỗi pattern giải quyết một bài toán cụ thể về cách tổ chức luồng xử lý LLM.

## Bảng so sánh

| # | Pattern | Điều kiện kích hoạt | Class chính | Ví dụ use case |
|---|---------|---------------------|-------------|----------------|
| 1 | **Prompt Chaining** | `complexity >= MEDIUM` | `ReActStrategy` | Debugging nhiều bước, tìm kiếm thông tin cần suy luận |
| 2 | **Routing** | Mọi request | `StrategySelector` + `ModelRouter` | Phân loại request → chọn strategy phù hợp + LLM tiết kiệm |
| 3 | **Parallelization** | Nhiều task độc lập | `AgentPool.fan_out()` | Xử lý đồng thời nhiều file/entity/query |
| 4 | **Orchestrator-Worker** | `complexity=HIGH` AND `len(entities) > 1` | `ParallelFanoutStrategy` + `AgentPool` | Phân tích nhiều tài liệu song song, tổng hợp kết quả |
| 5 | **Evaluator-Optimizer** | `complexity=HIGH` | `EvaluatorOptimizerStrategy` + `VerifierPipeline` | Sinh code/văn bản chất lượng cao, tự động refinement |

## Luồng dữ liệu tổng quát

```
User message
    │
    ▼
IIntentAnalyzer.analyze()
    │  → StructuredIntent(complexity, entities, suggested_strategy)
    ▼
StrategySelector.select()          ← Pattern 2: Routing
    │  → ICognitiveStrategy
    ▼
Strategy.execute(intent, context, agent_pool, verifier)
    ├── DirectStrategy             ← single-pass (baseline)
    ├── ReActStrategy              ← Pattern 1: Prompt Chaining
    ├── ParallelFanoutStrategy     ← Pattern 3+4: Parallelization / Orchestrator-Worker
    └── EvaluatorOptimizerStrategy ← Pattern 5: Evaluator-Optimizer
    │
    ▼
CognitiveResult(content, confidence, strategy_id)
```

## Quan hệ giữa các pattern

- **Routing** (Pattern 2) là lớp điều phối bao ngoài tất cả pattern còn lại — `StrategySelector` quyết định pattern nào được gọi.
- **Prompt Chaining** (Pattern 1) là vòng lặp tuần tự — phù hợp khi bước sau cần kết quả bước trước.
- **Parallelization** (Pattern 3) là primitive cấp thấp — `AgentPool.fan_out()` dùng anyio task group.
- **Orchestrator-Worker** (Pattern 4) dùng Pattern 3 ở tầng trên — `ParallelFanoutStrategy` điều phối nhiều worker qua `fan_out()`.
- **Evaluator-Optimizer** (Pattern 5) là vòng lặp chất lượng — generate → verify → refine, không song song.

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
| `ICognitiveStrategy` | `uaaf/cognitive/strategy.py` |
| `StructuredIntent` / `ComplexityLevel` / `ModelTier` | `uaaf/intent/models.py` |
