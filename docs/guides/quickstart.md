# RYUU Quickstart

> **Đã tách thành multi-file guide.** Vào → **[quickstart/README.md](quickstart/README.md)** để bắt đầu.

---

## Lý do tách

Monolithic 2500-line guide khó tra cứu. Đã chia theo package + chức năng:

| File | Nội dung |
|---|---|
| **[quickstart/README.md](quickstart/README.md)** | Index + status table + TL;DR + quick examples + nav |
| [01-factory.md](quickstart/01-factory.md) | `Agent()` factory (4 prompt modes + 4 tool modes, streaming, fallback) |
| [02-class-based.md](quickstart/02-class-based.md) | `BaseAgent` subclass (advanced) |
| [03-cross-cutting.md](quickstart/03-cross-cutting.md) | Observability / hooks / reasoning verifier toggle |
| [04-multi-agent.md](quickstart/04-multi-agent.md) | 5 patterns + Chain/FanOut/Router/Orchestrator/Evaluator |
| [05-prompt-tool-mgmt.md](quickstart/05-prompt-tool-mgmt.md) | YAML versioning, tool registry với DI, hot-swap version |
| [06-batch.md](quickstart/06-batch.md) | `BatchRunner` (gather + OpenAI Batch API 50% discount) |
| [07-prompt-optimizer.md](quickstart/07-prompt-optimizer.md) | `PromptOptimizer` (auto-tune qua eval) |
| [08-framework-comparison.md](quickstart/08-framework-comparison.md) | So sánh Pydantic AI / OpenAI Agents / Claude SDK / CrewAI / LangChain |
| [09-migration.md](quickstart/09-migration.md) | Day 1 prototype → Day 30 production |

## Reading Order

Cho người mới: **[README](quickstart/README.md) → [01-factory](quickstart/01-factory.md) → [03-cross-cutting](quickstart/03-cross-cutting.md) → [04-multi-agent](quickstart/04-multi-agent.md)**.

Cho người đến từ framework khác: [08-framework-comparison](quickstart/08-framework-comparison.md) trước.

Production migration: [09-migration](quickstart/09-migration.md).
