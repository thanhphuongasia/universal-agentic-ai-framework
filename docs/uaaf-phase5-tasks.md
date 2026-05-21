# RYUU Phase 5 — Integration Guide + Cookbook

**Goal**: Viết tài liệu hướng dẫn tích hợp RYUU vào product, thay thế example apps trong repo.

**Scope change**: Theo quyết định của team, Phase 5 bỏ `examples/` app code và thay bằng:
- `docs/guides/` — getting started + migration
- `docs/cookbook/` — use-case recipes cho từng product

**Lý do**: Product code nên nằm trong repo riêng của product, không trong framework repo.
Framework repo chỉ nên chứa `docs/` (intent + patterns + code snippets) cho từng use case.

---

## Task Breakdown

| ID | Task | Acceptance Criteria | Status |
|---|---|---|---|
| P5-T01 | Task breakdown doc | File này | ✅ |
| P5-T02 | Doc snippet validator | `tests/docs/test_doc_snippets.py` pass: all Python code blocks trong `docs/` compile + import paths valid | ✅ |
| P5-T03 | Getting Started guide | `docs/guides/getting-started.md` — install, setup ILLMProvider, first DirectStrategy call, <5 min to working agent | ✅ |
| P5-T04 | Cookbook: Todo App | `docs/cookbook/01-todo-app.md` — MemoryBackbone + DirectStrategy, full wiring diagram, runnable snippet | ✅ |
| P5-T05 | Cookbook: Flashcard | `docs/cookbook/02-flashcard-system.md` — EpisodicMemoryStore + spaced repetition pattern | ✅ |
| P5-T06 | Cookbook: Coding Practice | `docs/cookbook/03-coding-practice.md` — SandboxManager + tool registration | ✅ |
| P5-T07 | Cookbook: Stock Trading | `docs/cookbook/04-stock-trading.md` — AuditLogger + GroundTruthVerifier + trust=HIGH patterns | ✅ |
| P5-T08 | Migration Guide | `docs/guides/migration.md` — strangler pattern, feature flag, rollback < 5 min | ✅ |
| P5-T09 | README update | `README.md` — link to guides section | ✅ |
| P5-T10 | CHANGELOG + memory | v0.1.0b5 entry, memory updated | ✅ |

---

## Doc Validation Approach

Thay vì unit test code, dùng **doc snippet validator**:
- Parse tất cả `docs/**/*.md`
- Extract Python code blocks (` ```python ... ``` `)
- `compile()` từng snippet → SyntaxError = fail
- Import check: validate `from ryuu.X import Y` paths tồn tại trong package

Test file: `tests/docs/test_doc_snippets.py`

---

## Deliverables

```
docs/
  guides/
    getting-started.md    ← install → first agent in <5 min
    migration.md          ← strangler pattern + feature flag
  cookbook/
    01-todo-app.md
    02-flashcard-system.md
    03-coding-practice.md
    04-stock-trading.md
tests/
  docs/
    test_doc_snippets.py  ← validates all code snippets compile
```
