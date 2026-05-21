# RYUU — Phase 3 (Knowledge Backbone) — Task Breakdown

> Phase 3 goal: `IKnowledgeBackbone` Protocol + `MemoryBackbone` (working + episodic layers) + `GraphBackbone` (in-memory graph store) + `HybridBackbone` + `ContextAssembler` (token-budget assembly). `FakeKnowledgeBackbone` upgraded to satisfy the Protocol.

**Status**: Complete
**Last Updated**: 2026-05-07
**Predecessors**: Phase 2 complete (v0.1.0b2)

---

## Task graph

```
P3-T01 IKnowledgeBackbone Protocol + models (backbone.py)
         │
         ├──→ P3-T02 IMemoryStore Protocol + MemoryEntry (memory/store.py)
         │         │
         │         ├──→ P3-T03 WorkingMemoryStore (memory/working.py)
         │         ├──→ P3-T04 EpisodicMemoryStore (memory/episodic.py)
         │         └──→ P3-T05 MemoryBackbone (memory/backbone.py)
         │
         ├──→ P3-T06 IGraphStore Protocol + Node/Edge (graph/store.py)
         │         │
         │         ├──→ P3-T07 InMemoryGraphStore (graph/in_memory.py)
         │         └──→ P3-T08 GraphBackbone (graph/backbone.py)
         │
         ├──→ P3-T09 HybridBackbone (hybrid.py)
         │
         └──→ P3-T10 ContextAssembler (context_assembler.py)
                  │
               P3-T11 FakeKnowledgeBackbone upgrade (_testing/fakes.py)
                  │
               P3-T12 Tests (unit + contract + integration)
                  │
               P3-T13 CI gate
```

---

## P3-T01. IKnowledgeBackbone Protocol (`ryuu/knowledge/backbone.py`)

**Acceptance**:
- `BackboneType(StrEnum)`: `MEMORY = "memory"`, `GRAPH = "graph"`, `HYBRID = "hybrid"`
- `QueryResult` frozen dataclass: `results: list[str]`, `scores: list[float]`, `metadata: dict[str, Any]`
- `AssembledContext` frozen dataclass: `text: str`, `token_count: int`, `source_ids: list[str]`
- `IKnowledgeBackbone` `@runtime_checkable` Protocol:
  - `backbone_type: BackboneType`
  - `async def write(observation: str, scope_key: str, metadata: dict | None) -> None`
  - `async def query(query: str, scope_key: str, top_k: int = 5) -> QueryResult`
  - `async def assemble_context(query: str, scope_key: str, budget_tokens: int = 2000) -> AssembledContext`

**Files**: `ryuu/knowledge/__init__.py`, `ryuu/knowledge/backbone.py`

---

## P3-T02. IMemoryStore Protocol (`ryuu/knowledge/memory/store.py`)

**Acceptance**:
- `MemoryLayer(StrEnum)`: `WORKING = "working"`, `EPISODIC = "episodic"`
- `MemoryEntry` frozen dataclass: `content: str`, `score: float = 1.0`, `created_at: float` (unix ts), `metadata: dict[str, Any]`
- `IMemoryStore` `@runtime_checkable` Protocol:
  - `layer: MemoryLayer`
  - `async def store(content: str, scope_key: str, metadata: dict | None) -> None`
  - `async def retrieve(query: str, scope_key: str, top_k: int = 5) -> list[MemoryEntry]`
  - `async def clear(scope_key: str) -> None`

**Files**: `ryuu/knowledge/memory/__init__.py`, `ryuu/knowledge/memory/store.py`

---

## P3-T03. WorkingMemoryStore (`ryuu/knowledge/memory/working.py`)

**Acceptance**:
- `WorkingMemoryStore(max_entries: int = 50)`
- `layer = MemoryLayer.WORKING`
- Stores entries in a bounded FIFO deque per scope_key; oldest evicted when full
- `retrieve()`: returns last `top_k` entries (most-recent-first), score = 1.0 for all

**Files**: `ryuu/knowledge/memory/working.py`

---

## P3-T04. EpisodicMemoryStore (`ryuu/knowledge/memory/episodic.py`)

**Acceptance**:
- `EpisodicMemoryStore(max_entries: int = 500)`
- `layer = MemoryLayer.EPISODIC`
- Stores entries time-ordered; no eviction (up to max_entries)
- `retrieve()`: keyword match (`query` words appear in `content`); score = overlap ratio; returns top_k by score descending

**Files**: `ryuu/knowledge/memory/episodic.py`

---

## P3-T05. MemoryBackbone (`ryuu/knowledge/memory/backbone.py`)

**Acceptance**:
- `MemoryBackbone(layers: list[IMemoryStore] | None = None)`
  - Default: `[WorkingMemoryStore(), EpisodicMemoryStore()]`
- `backbone_type = BackboneType.MEMORY`
- `write(observation, scope_key)` → stores to all layers
- `query(query, scope_key, top_k)` → queries all layers, merges by score desc, dedups content, returns top_k
- `assemble_context(query, scope_key, budget_tokens)`:
  - Calls `query()`, joins results into text until token budget reached
  - Token estimate: `len(text.split())`
  - Returns `AssembledContext`

**Files**: `ryuu/knowledge/memory/backbone.py`

---

## P3-T06. IGraphStore Protocol + models (`ryuu/knowledge/graph/store.py`)

**Acceptance**:
- `Node` dataclass: `node_id: str`, `labels: list[str]`, `properties: dict[str, Any]`
- `Edge` dataclass: `src_id: str`, `dst_id: str`, `rel_type: str`, `properties: dict[str, Any]`
- `IGraphStore` `@runtime_checkable` Protocol:
  - `async def upsert_node(node: Node) -> None`
  - `async def upsert_edge(edge: Edge) -> None`
  - `async def get_node(node_id: str) -> Node | None`
  - `async def get_neighbors(node_id: str, max_hops: int = 1) -> list[Node]`
  - `async def text_search(query: str, top_k: int = 5) -> list[Node]`

**Files**: `ryuu/knowledge/graph/__init__.py`, `ryuu/knowledge/graph/store.py`

---

## P3-T07. InMemoryGraphStore (`ryuu/knowledge/graph/in_memory.py`)

**Acceptance**:
- `InMemoryGraphStore()`
- Stores nodes in `dict[str, Node]`, edges in `list[Edge]`
- `upsert_node`: insert or replace by `node_id`
- `get_neighbors(node_id, max_hops)`: BFS traversal up to `max_hops` edges (both directions)
- `text_search`: substring match against `node_id` + all string values in `properties`; returns up to `top_k`

**Files**: `ryuu/knowledge/graph/in_memory.py`

---

## P3-T08. GraphBackbone (`ryuu/knowledge/graph/backbone.py`)

**Acceptance**:
- `GraphBackbone(store: IGraphStore | None = None)`
  - Default: `InMemoryGraphStore()`
- `backbone_type = BackboneType.GRAPH`
- `write(observation, scope_key)`: creates a `Node(node_id=uuid4, labels=["observation"], properties={"text": observation, "scope": scope_key})`
- `query(query, scope_key, top_k)`: calls `store.text_search(query, top_k)`; returns `QueryResult`
- `assemble_context(query, scope_key, budget_tokens)`: text_search + get_neighbors for top result; assembles until budget reached

**Files**: `ryuu/knowledge/graph/backbone.py`

---

## P3-T09. HybridBackbone (`ryuu/knowledge/hybrid.py`)

**Acceptance**:
- `HybridBackbone(primary: IKnowledgeBackbone | None, secondary: IKnowledgeBackbone | None)`
  - Defaults: `primary=GraphBackbone()`, `secondary=MemoryBackbone()`
- `backbone_type = BackboneType.HYBRID`
- `write(observation, scope_key)` → writes to both
- `query(query, scope_key, top_k)` → queries both, merges results (dedup), top_k by score
- `assemble_context(query, scope_key, budget_tokens)` → 60% budget to primary, 40% to secondary; merges

**Files**: `ryuu/knowledge/hybrid.py`

---

## P3-T10. ContextAssembler (`ryuu/knowledge/context_assembler.py`)

**Acceptance**:
- `ContextAssembler(backbone: IKnowledgeBackbone)`
- `async def assemble(query: str, scope_key: str, budget_tokens: int = 2000) -> AssembledContext`
  - Delegates to `backbone.assemble_context(query, scope_key, budget_tokens)`
- `async def write(observation: str, scope_key: str, metadata: dict | None = None) -> None`
  - Delegates to `backbone.write(observation, scope_key, metadata)`

**Files**: `ryuu/knowledge/context_assembler.py`

---

## P3-T11. FakeKnowledgeBackbone upgrade

**Acceptance**:
- Implement `IKnowledgeBackbone` Protocol fully:
  - `backbone_type = BackboneType.MEMORY`
  - `async def write(...)`, `async def query(...) -> QueryResult`, `async def assemble_context(...) -> AssembledContext`
- `written: list[dict]` still tracks writes
- `query_responses: list[QueryResult]` pops next response (default empty `QueryResult`)

**Files**: `ryuu/_testing/fakes.py`

---

## P3-T12. Tests

**Unit tests**:
- `tests/unit/knowledge/test_working_memory.py`
- `tests/unit/knowledge/test_episodic_memory.py`
- `tests/unit/knowledge/test_memory_backbone.py`
- `tests/unit/knowledge/test_in_memory_graph.py`
- `tests/unit/knowledge/test_graph_backbone.py`
- `tests/unit/knowledge/test_hybrid_backbone.py`
- `tests/unit/knowledge/test_context_assembler.py`

**Contract test**:
- `tests/contract/test_backbone_contract.py` — parametrized over MemoryBackbone, GraphBackbone, HybridBackbone, FakeKnowledgeBackbone

**Integration**:
- `tests/integration/test_phase3_smoke.py` — EvaluatorOptimizerStrategy + ContextAssembler end-to-end

---

## P3-T13. CI gate

- [x] `ruff check ryuu/ tests/` → 0 violations
- [x] `mypy ryuu/ --ignore-missing-imports` → 0 errors
- [x] `pytest --cov=ryuu` → coverage ≥85%
- [ ] User review + approve
- [ ] Tag v0.1.0b3

---

## Cross-task gates

- [ ] CI gate green
- [ ] All 3 backbone impls + FakeKnowledgeBackbone pass contract test
- [ ] CHANGELOG v0.1.0b3 entry
- [ ] FakeKnowledgeBackbone in `_testing/fakes.py` satisfies `isinstance(fake, IKnowledgeBackbone)`
