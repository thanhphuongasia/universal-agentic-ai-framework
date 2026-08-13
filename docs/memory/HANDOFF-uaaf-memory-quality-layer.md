# Handoff — UAAF Memory Quality Layer

> **Cho:** Claude Code
> **Mục tiêu:** Thêm 3 thành phần còn thiếu vào UAAF Knowledge Tier:
> 1. `MemoryProcessor` — extraction/dedup/conflict trước khi ghi episodic
> 2. `DreamingConsolidator` — offline consolidation episodic → semantic + eviction
> 3. `SelfLearningStore` — behavior hints từ patterns, inject vào prompt
>
> Kèm theo: hướng dẫn tích hợp với Agent SDK bot qua Telegram.
> **Ngày:** 2026-05-31
> **Scope:** Additive — không đổi interface hiện tại, không break existing code.

---

## 1. Bối cảnh & vấn đề

### 1.1 Gap hiện tại

UAAF `MemoryBackbone` hiện có `write(observation, scope_key, metadata)` nhưng:

- **Không filter noise:** "Thanks", "Let me think" được ghi như mọi thứ khác.
- **Không dedup:** cùng fact ghi nhiều lần → retrieval noise.
- **Không resolve conflict:** "dùng PostgreSQL" rồi "switch sang MongoDB" — cả hai tồn tại, AI bị confused.
- **Episodic không bao giờ dọn:** phình vô hạn → assemble_context() chậm dần.
- **SelfLearningStore:** tên có trong class diagram, không có implementation.
- **SemanticMemoryStore:** nhắc qua, không có spec.
- **Không có dreaming:** episodic không bao giờ được consolidate thành semantic.

### 1.2 Quyết định thiết kế

| # | Quyết định | Lý do |
|---|---|---|
| D1 | `IMemoryProcessor` là Protocol, default = `PassthroughProcessor` | Backward compat — code cũ không thay đổi behavior |
| D2 | Working memory KHÔNG qua processor | Tốc độ ưu tiên, noise OK trong session ngắn |
| D3 | Episodic write async task + processor | Không chặn response |
| D4 | Dreaming chạy post-session, không cần cron | Personal use — trigger khi session kết thúc |
| D5 | Eviction dùng importance-weighted decay, không TTL thuần | TTL thuần xóa nhầm preference cũ còn giá trị |
| D6 | Archive trước khi delete (30 ngày grace period) | Tránh mất data do threshold sai |
| D7 | SelfLearning = behavior hints trong Postgres, inject vào system prompt | Không fine-tune model, chỉ prompt augmentation |
| D8 | Agent SDK integration = inject `AssembledContext` vào prompt trước `query()` | Agent SDK stateless — memory phải inject từ ngoài |

### 1.3 Ngoài scope

- ❌ Semantic memory full-text search (chỉ vector similarity cho MVP)
- ❌ Distributed/multi-process memory sync
- ❌ Fine-tuning hay training từ patterns
- ❌ Đổi `IKnowledgeBackbone` interface hiện tại
- ❌ Dreaming distributed job scheduler (asyncio.create_task là đủ)

---

## 2. File structure — những gì cần tạo/sửa

```
uaaf/knowledge/
├── memory/
│   ├── store.py           MODIFY — thêm fields vào MemoryEntry
│   ├── working.py         KHÔNG đổi
│   ├── episodic.py        MODIFY — thêm get_unconsolidated, mark_consolidated, archive, eviction
│   ├── semantic.py        NEW    — SemanticMemoryStore (hiện rỗng/stub)
│   ├── self_learning.py   NEW    — SelfLearningStore (hiện rỗng/stub)
│   └── backbone.py        MODIFY — inject processor vào write(), trigger dreaming
│
├── processor/             NEW directory
│   ├── __init__.py
│   ├── protocol.py        IMemoryProcessor Protocol + ProcessResult
│   ├── passthrough.py     PassthroughProcessor (default, no-op)
│   ├── extractor.py       ExtractionFilter — signal vs noise
│   ├── deduplicator.py    DuplicateDetector — embedding cosine
│   └── conflict.py        ConflictResolver — LLM judgment
│
└── consolidator/          NEW directory
    ├── __init__.py
    ├── dreaming.py         DreamingConsolidator — episodic → semantic
    └── eviction.py         EvictionJob — lifecycle management

# Integration
bots/agent_sdk_bot/
└── memory_middleware.py   NEW — helper tích hợp backbone với Agent SDK
```

---

## 3. Data model — MemoryEntry (extend)

Verify file hiện tại: `grep -n "class MemoryEntry" uaaf/knowledge/memory/store.py`

Thêm fields mới vào `MemoryEntry` — tất cả có default để không break code cũ:

```python
@dataclass
class MemoryEntry:
    # ── Fields hiện tại (GIỮ NGUYÊN) ──
    id:         str
    content:    str
    scope_key:  str
    created_at: datetime
    metadata:   dict

    # ── Fields mới (additive, có default) ──
    embedding:        list[float] | None = None
    importance:       str = "medium"          # "high" | "medium" | "low"
    status:           str = "active"          # "active" | "consolidated" | "archived" | "deleted"
    last_accessed:    datetime = field(default_factory=datetime.utcnow)
    access_count:     int = 0
    was_corrected:    bool = False            # True nếu user đã correct agent
    superseded_by:    str | None = None       # id của entry mới hơn nếu conflict resolved
    consolidated_at:  datetime | None = None  # khi nào được đưa lên semantic
```

> ⚠️ Verify schema DB nếu EpisodicMemoryStore đang persist Postgres — cần migration additive.

---

## 4. IMemoryProcessor Protocol

```python
# uaaf/knowledge/processor/protocol.py

from typing import Protocol
from dataclasses import dataclass
from enum import StrEnum
from uaaf.knowledge.memory.store import MemoryEntry


class MemoryAction(StrEnum):
    ADD              = "add"
    SKIP             = "skip"            # noise hoặc duplicate
    CONFLICT_RESOLVED = "conflict_resolved"  # fact mới thắng, cần archive old


@dataclass(frozen=True)
class ProcessResult:
    should_store:       bool
    content:            str              # có thể đã được normalize
    action:             MemoryAction
    importance:         str = "medium"   # "high" | "medium" | "low"
    conflict_entry_id:  str | None = None  # id entry cũ cần archive


class IMemoryProcessor(Protocol):
    async def process(
        self,
        observation:  str,
        scope_key:    str,
        existing:     list[MemoryEntry],  # top-k entries đã retrieve để check
    ) -> ProcessResult: ...
```

---

## 5. MemoryProcessor implementations

### 5.1 PassthroughProcessor (default — backward compat)

```python
# uaaf/knowledge/processor/passthrough.py

class PassthroughProcessor:
    """No-op processor — behavior giống UAAF hiện tại.
    Dùng làm default khi không inject processor thật.
    """
    async def process(self, observation, scope_key, existing) -> ProcessResult:
        return ProcessResult(
            should_store=True,
            content=observation,
            action=MemoryAction.ADD,
            importance="medium",
        )
```

### 5.2 ExtractionFilter

```python
# uaaf/knowledge/processor/extractor.py

EXTRACTION_SYSTEM = """
Đánh giá observation sau có chứa thông tin đáng nhớ lâu dài không.

SIGNAL (ghi nhớ):
- Facts cụ thể: "API rate limit là 100 req/min"
- Preferences: "User thích dark mode", "prefer code trước giải thích sau"
- Decisions: "Team quyết định dùng GraphQL"
- Goals: "Target launch tháng 8"
- Expertise: "User là senior Python developer"

NOISE (bỏ qua):
- Chào hỏi: "Hello", "Thanks", "OK"
- Filler: "Hmm", "Let me think", "Good question"
- Xác nhận: "Got it", "Understood"
- Thinking aloud không có kết luận

IMPORTANCE:
- high:   preferences, expertise, identity, long-term goals
- medium: current projects, recent decisions, active context
- low:    one-off mentions, temporary states

Trả về JSON chính xác, không markdown:
{"is_signal": bool, "extracted_fact": "string|null", "importance": "high|medium|low"}
"""

class ExtractionFilter:
    def __init__(self, llm_provider):
        # Dùng model rẻ — Haiku hoặc equivalent
        self._llm = llm_provider

    async def process(self, observation, scope_key, existing) -> ProcessResult:
        response = await self._llm.complete(CompletionRequest(
            model="claude-haiku-4-5-20251001",  # VERIFY model string
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM},
                {"role": "user",   "content": f'Observation: "{observation}"'},
            ],
            max_tokens=100,
            temperature=0,
        ))

        try:
            parsed = json.loads(response.content)
        except json.JSONDecodeError:
            # Fallback: store anyway
            return ProcessResult(should_store=True, content=observation,
                                 action=MemoryAction.ADD)

        if not parsed.get("is_signal"):
            return ProcessResult(should_store=False, content=observation,
                                 action=MemoryAction.SKIP)

        return ProcessResult(
            should_store=True,
            content=parsed.get("extracted_fact") or observation,
            action=MemoryAction.ADD,
            importance=parsed.get("importance", "medium"),
        )
```

### 5.3 DuplicateDetector

```python
# uaaf/knowledge/processor/deduplicator.py

DUPLICATE_THRESHOLD = 0.92  # tune theo use case

class DuplicateDetector:
    def __init__(self, embedder):
        self._embedder = embedder

    async def process(self, observation, scope_key, existing) -> ProcessResult:
        if not existing:
            return ProcessResult(should_store=True, content=observation,
                                 action=MemoryAction.ADD)

        new_emb = await self._embedder.embed(observation)

        for entry in existing:
            if entry.embedding is None:
                continue
            sim = cosine_similarity(new_emb, entry.embedding)
            if sim > DUPLICATE_THRESHOLD:
                return ProcessResult(should_store=False, content=observation,
                                     action=MemoryAction.SKIP)

        return ProcessResult(should_store=True, content=observation,
                             action=MemoryAction.ADD)
```

### 5.4 ConflictResolver

```python
# uaaf/knowledge/processor/conflict.py

CONFLICT_SYSTEM = """
Kiểm tra xem hai facts có contradicts nhau không.

Contradiction: cùng chủ đề nhưng khác nhau về trạng thái/giá trị/quyết định.
  VD: "dùng PostgreSQL" vs "đã switch sang MongoDB" → contradiction
  VD: "dùng PostgreSQL" vs "thêm Redis cache" → KHÔNG contradiction

Trả JSON: {"is_conflict": bool, "winner": "new|old|both_valid", "reason": "string"}
"""

class ConflictResolver:
    def __init__(self, llm_provider, store):
        self._llm   = llm_provider
        self._store = store

    async def process(self, observation, scope_key, existing) -> ProcessResult:
        if not existing:
            return ProcessResult(should_store=True, content=observation,
                                 action=MemoryAction.ADD)

        # Chỉ check conflict với entries importance >= medium
        candidates = [e for e in existing if e.importance in ("high", "medium")]
        if not candidates:
            return ProcessResult(should_store=True, content=observation,
                                 action=MemoryAction.ADD)

        # Check từng candidate (giới hạn 3 để tiết kiệm token)
        for entry in candidates[:3]:
            response = await self._llm.complete(CompletionRequest(
                model="claude-haiku-4-5-20251001",
                messages=[
                    {"role": "system", "content": CONFLICT_SYSTEM},
                    {"role": "user", "content":
                        f'Fact cũ: "{entry.content}"\nFact mới: "{observation}"'},
                ],
                max_tokens=80, temperature=0,
            ))
            try:
                parsed = json.loads(response.content)
            except Exception:
                continue

            if parsed.get("is_conflict") and parsed.get("winner") == "new":
                return ProcessResult(
                    should_store=True,
                    content=observation,
                    action=MemoryAction.CONFLICT_RESOLVED,
                    conflict_entry_id=entry.id,
                )

        return ProcessResult(should_store=True, content=observation,
                             action=MemoryAction.ADD)
```

### 5.5 CompositeProcessor (chain các processor)

```python
# uaaf/knowledge/processor/__init__.py

class CompositeProcessor:
    """Chain: Extraction → Dedup → Conflict.
    Dừng ngay khi bất kỳ bước nào trả should_store=False.
    """
    def __init__(self, processors: list[IMemoryProcessor]):
        self._processors = processors

    async def process(self, observation, scope_key, existing) -> ProcessResult:
        current_content = observation
        for processor in self._processors:
            result = await processor.process(current_content, scope_key, existing)
            if not result.should_store:
                return result  # dừng chain
            current_content = result.content  # pass cleaned content xuống
        return result

# Factory function — convenience
def build_quality_processor(llm, embedder, store) -> CompositeProcessor:
    return CompositeProcessor([
        ExtractionFilter(llm),
        DuplicateDetector(embedder),
        ConflictResolver(llm, store),
    ])
```

---

## 6. MemoryBackbone — inject processor

Modify `backbone.py` để support processor:

```python
# uaaf/knowledge/memory/backbone.py — MODIFY

class MemoryBackbone:
    def __init__(
        self,
        layers: dict,
        processor: IMemoryProcessor | None = None,   # NEW — optional
        embedder = None,                              # NEW — optional, cho dedup
        dreaming_consolidator = None,                 # NEW — optional
    ):
        self._layers    = layers
        self._processor = processor or PassthroughProcessor()
        self._embedder  = embedder
        self._dreamer   = dreaming_consolidator

    async def write(self, observation: str, scope_key: str, metadata: dict):
        layer = metadata.get("layer", "working")

        if layer == "working":
            # KHÔNG qua processor — tốc độ ưu tiên
            await self._layers["working"].store(observation, scope_key, metadata)

        elif layer == "episodic":
            # Async task — không chặn response
            asyncio.create_task(
                self._process_and_store_episodic(observation, scope_key, metadata)
            )

    async def _process_and_store_episodic(self, observation, scope_key, metadata):
        # Lấy top-k existing để check dedup/conflict
        existing = await self._layers["episodic"].retrieve(
            query=observation, scope_key=scope_key, top_k=5
        )

        result = await self._processor.process(observation, scope_key, existing)

        if not result.should_store:
            return  # noise hoặc duplicate — bỏ qua

        if result.action == MemoryAction.CONFLICT_RESOLVED and result.conflict_entry_id:
            # Archive entry cũ
            await self._layers["episodic"].archive(result.conflict_entry_id)

        # Store với importance từ processor
        enriched_metadata = {
            **metadata,
            "importance": result.importance,
            "status": "active",
        }

        # Embed nếu có embedder
        embedding = None
        if self._embedder:
            embedding = await self._embedder.embed(result.content)

        await self._layers["episodic"].store(
            result.content, scope_key,
            {**enriched_metadata, "embedding": embedding}
        )

    async def end_session(self, scope_key: str):
        """Gọi khi user disconnect/session kết thúc.
        Trigger dreaming + eviction async.
        """
        if self._dreamer:
            user_id = scope_key.split(":")[0]  # extract user_id từ scope
            asyncio.create_task(self._dreamer.run_cycle(user_id))
```

---

## 7. DreamingConsolidator

```python
# uaaf/knowledge/consolidator/dreaming.py

SUMMARIZE_CLUSTER_SYSTEM = """
Bạn nhận một nhóm memory entries liên quan nhau.
Tóm tắt thành một fact duy nhất, súc tích, dưới 2 câu.
Giữ thông tin quan trọng nhất, bỏ chi tiết thừa.
Trả về chỉ text của fact, không markdown, không giải thích.
"""

class DreamingConsolidator:
    def __init__(self, episodic_store, semantic_store, llm_provider, embedder):
        self._episodic  = episodic_store
        self._semantic  = semantic_store
        self._llm       = llm_provider
        self._embedder  = embedder
        self._eviction  = EvictionJob(episodic_store)

    async def run_cycle(self, user_id: str):
        """Entry point — chạy sau khi session kết thúc."""

        # 1. Dọn dẹp trước (eviction)
        await self._eviction.run(user_id)

        # 2. Lấy entries chưa consolidated
        pending = await self._episodic.get_unconsolidated(
            user_id, limit=50
        )
        if not pending:
            return

        # 3. Cluster theo chủ đề
        clusters = await self._cluster_by_topic(pending)

        for cluster in clusters:
            if len(cluster) < 2:
                # Entry đơn lẻ — consolidate thẳng nếu importance cao
                if cluster[0].importance == "high":
                    await self._consolidate_single(cluster[0], user_id)
                continue

            # 4. Summarize cluster → một semantic fact
            summary = await self._summarize(cluster)
            if not summary:
                continue

            # 5. Check duplicate trong semantic
            existing_semantic = await self._semantic.retrieve(
                query=summary, scope_key=user_id, top_k=3
            )
            emb = await self._embedder.embed(summary)
            is_dup = any(
                cosine_similarity(emb, e.embedding) > 0.92
                for e in existing_semantic if e.embedding
            )
            if is_dup:
                # Mark processed nhưng không store
                await self._episodic.mark_consolidated(
                    [e.id for e in cluster]
                )
                continue

            # 6. Ghi vào semantic
            await self._semantic.store(
                summary,
                scope_key=user_id,
                metadata={
                    "importance": "high",
                    "source_entry_ids": [e.id for e in cluster],
                    "embedding": emb,
                }
            )

            # 7. Mark episodic entries đã consolidated
            await self._episodic.mark_consolidated(
                [e.id for e in cluster]
            )

        # 8. SelfLearning update
        corrections = [e for e in pending if e.was_corrected]
        if corrections:
            await self._update_behavior_hints(corrections, user_id)

    async def _cluster_by_topic(
        self, entries: list[MemoryEntry]
    ) -> list[list[MemoryEntry]]:
        """Simple embedding clustering — k-means hoặc greedy merge.

        Greedy merge (đơn giản hơn cho personal scale):
        - Entry đầu tiên tạo cluster mới
        - Entry tiếp theo: nếu sim > 0.75 với centroid → merge, ngược lại cluster mới
        """
        if not entries:
            return []

        clusters: list[list[MemoryEntry]] = []
        centroids: list[list[float]] = []

        for entry in entries:
            emb = entry.embedding
            if emb is None and self._embedder:
                emb = await self._embedder.embed(entry.content)

            placed = False
            if emb:
                for i, centroid in enumerate(centroids):
                    if cosine_similarity(emb, centroid) > 0.75:
                        clusters[i].append(entry)
                        # Update centroid (running average)
                        n = len(clusters[i])
                        centroids[i] = [(c*(n-1) + e)/n
                                        for c, e in zip(centroid, emb)]
                        placed = True
                        break

            if not placed:
                clusters.append([entry])
                centroids.append(emb or [])

        return clusters

    async def _summarize(self, cluster: list[MemoryEntry]) -> str | None:
        combined = "\n".join(f"- {e.content}" for e in cluster)
        response = await self._llm.complete(CompletionRequest(
            model="claude-haiku-4-5-20251001",
            messages=[
                {"role": "system", "content": SUMMARIZE_CLUSTER_SYSTEM},
                {"role": "user",   "content": combined},
            ],
            max_tokens=150, temperature=0,
        ))
        return response.content.strip() or None

    async def _update_behavior_hints(
        self, corrections: list[MemoryEntry], user_id: str
    ):
        """Phân tích corrections → extract behavior hints → SelfLearningStore."""
        # Implement ở SelfLearningStore section (mục 9)
        pass
```

---

## 8. EvictionJob

```python
# uaaf/knowledge/consolidator/eviction.py

DECAY_RATE      = 0.95   # giảm 5% mỗi ngày không access
LOW_THRESHOLD   = 0.10   # dưới 10% → candidate archive
ARCHIVE_TTL_DAYS = 30    # giữ trong archive 30 ngày rồi xóa

class EvictionJob:
    def __init__(self, episodic_store):
        self._store = episodic_store

    async def run(self, user_id: str):
        entries = await self._store.get_all_active(user_id)
        now = datetime.utcnow()

        for entry in entries:
            # High importance → không bao giờ evict
            if entry.importance == "high":
                continue

            days_idle = (now - entry.last_accessed).days
            base_score = {"medium": 0.6, "low": 0.3}.get(entry.importance, 0.3)
            decayed = base_score * (DECAY_RATE ** days_idle)

            if decayed < LOW_THRESHOLD:
                if entry.status == "consolidated":
                    # Đã lên semantic + decay thấp → xóa
                    await self._store.delete(entry.id)
                else:
                    # Chưa consolidated → archive, giữ 30 ngày
                    await self._store.archive(entry.id, ttl_days=ARCHIVE_TTL_DAYS)

            # Dọn archive hết hạn
            await self._store.delete_expired_archives(user_id)
```

### EpisodicMemoryStore — methods cần thêm

Verify interface hiện tại rồi thêm các methods sau:

```python
# uaaf/knowledge/memory/episodic.py — MODIFY, thêm methods:

async def get_unconsolidated(
    self, user_id: str, limit: int = 50
) -> list[MemoryEntry]:
    """Lấy entries status='active' chưa được mark consolidated."""
    ...

async def mark_consolidated(self, entry_ids: list[str]) -> None:
    """Set status='consolidated', consolidated_at=now() cho các entries."""
    ...

async def archive(self, entry_id: str, ttl_days: int = 30) -> None:
    """Set status='archived', tính archived_until = now() + ttl_days."""
    ...

async def delete_expired_archives(self, user_id: str) -> None:
    """Xóa entries status='archived' đã qua archived_until."""
    ...

async def get_all_active(self, user_id: str) -> list[MemoryEntry]:
    """Lấy tất cả entries status='active' của user."""
    ...

async def update_last_accessed(self, entry_id: str) -> None:
    """Gọi mỗi khi entry được retrieve — cập nhật last_accessed, access_count."""
    ...
```

---

## 9. SemanticMemoryStore

```python
# uaaf/knowledge/memory/semantic.py — NEW

class SemanticMemoryStore:
    """Long-term consolidated knowledge.
    
    Nguồn: DreamingConsolidator ghi vào.
    Đặc điểm:
      - Ít entries hơn episodic nhưng chất lượng cao hơn
      - Vector search chính (embedding cosine)
      - Không bao giờ tự expire (manual only)
      - Mỗi entry = một distilled fact
    """

    async def store(
        self, content: str, scope_key: str, metadata: dict
    ) -> None: ...

    async def retrieve(
        self, query: str, scope_key: str, top_k: int = 5
    ) -> list[MemoryEntry]: ...

    async def update(self, entry_id: str, new_content: str) -> None:
        """Dùng khi ConflictResolver tìm thấy fact cũ cần update."""
        ...
```

---

## 10. SelfLearningStore

```python
# uaaf/knowledge/memory/self_learning.py — NEW

BEHAVIOR_HINT_SYSTEM = """
Phân tích các lần agent bị user correct. Tìm PATTERN chung.

Input: list corrections (nội dung agent nói sai và user đã sửa).
Output: behavior hints ngắn gọn — những điều agent nên nhớ để không lặp lỗi.

Format JSON: {"hints": ["hint 1", "hint 2", ...]}
Tối đa 5 hints, mỗi hint dưới 20 words.
"""

class SelfLearningStore:
    """
    Lưu behavior hints — inject vào system prompt để agent học từ mistakes.
    Không fine-tune model. Chỉ là prompt augmentation.
    
    Ví dụ hints:
      "When explaining Python, show code example first, then theory"
      "User prefers bullet points over prose paragraphs"
      "Double-check async/await patterns before responding"
    """

    def __init__(self, store, llm_provider):
        self._store = store
        self._llm   = llm_provider

    async def update_from_corrections(
        self,
        corrections: list[MemoryEntry],
        user_id: str,
    ) -> None:
        if not corrections:
            return

        combined = "\n".join(
            f"- Agent said: {e.metadata.get('agent_output', '')[:100]}"
            f" | User corrected: {e.content[:100]}"
            for e in corrections
        )

        response = await self._llm.complete(CompletionRequest(
            model="claude-haiku-4-5-20251001",
            messages=[
                {"role": "system", "content": BEHAVIOR_HINT_SYSTEM},
                {"role": "user",   "content": combined},
            ],
            max_tokens=200, temperature=0,
        ))

        try:
            parsed = json.loads(response.content)
            hints = parsed.get("hints", [])
        except Exception:
            return

        await self._store_hints(user_id, hints)

    async def get_hints(self, user_id: str) -> list[str]:
        """Lấy hints để inject vào system prompt."""
        return await self._store.get_hints(user_id)

    async def format_for_prompt(self, user_id: str) -> str:
        hints = await self.get_hints(user_id)
        if not hints:
            return ""
        bullet_list = "\n".join(f"- {h}" for h in hints)
        return f"Learned preferences for this user:\n{bullet_list}"
```

---

## 11. Agent SDK Integration

Đây là mục đích cuối — tích hợp memory vào Telegram bot dùng Agent SDK.

### 11.1 Vấn đề cốt lõi

Agent SDK `query()` là **stateless** — mỗi call là một agent loop độc lập, không nhớ gì từ call trước. Memory phải inject từ ngoài vào `system_prompt` của `ClaudeAgentOptions`.

### 11.2 MemoryMiddleware helper

```python
# bots/agent_sdk_bot/memory_middleware.py

from uaaf.knowledge.memory.backbone import MemoryBackbone
from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, ResultMessage


class MemoryMiddleware:
    """
    Wrapper quanh Agent SDK query().
    Tự động:
      1. Recall memory trước khi gọi query()
      2. Inject vào system_prompt
      3. Write-back sau khi xong
      4. Trigger dreaming khi session kết thúc
    """

    def __init__(self, backbone: MemoryBackbone, self_learning_store=None):
        self._backbone       = backbone
        self._self_learning  = self_learning_store

    async def query_with_memory(
        self,
        user_message:  str,
        user_id:       str,
        domain:        str,
        base_system:   str = "",
        allowed_tools: list[str] = None,
        mcp_servers:   list[dict] = None,
        max_turns:     int = 8,
        on_chunk=None,
    ) -> str:
        scope_session = f"{user_id}:{domain}"
        scope_user    = user_id

        # ── 1. Recall memory ──────────────────────────────────
        # Working: conversation history gần đây (session scope)
        working_ctx = await self._backbone.assemble_context(
            query=user_message,
            scope_key=scope_session,
            budget_tokens=300,
        )

        # Episodic + Semantic: cross-session knowledge (user scope)
        long_term_ctx = await self._backbone.assemble_context(
            query=user_message,
            scope_key=scope_user,
            budget_tokens=300,
        )

        # SelfLearning hints
        hints_text = ""
        if self._self_learning:
            hints_text = await self._self_learning.format_for_prompt(user_id)

        # ── 2. Build system prompt ────────────────────────────
        system_parts = [p for p in [
            base_system,
            working_ctx.text   and f"Recent conversation:\n{working_ctx.text}",
            long_term_ctx.text and f"What I know about you:\n{long_term_ctx.text}",
            hints_text,
        ] if p]
        system_prompt = "\n\n".join(system_parts)

        # ── 3. Stream query() ─────────────────────────────────
        chunks: list[str] = []
        cost_usd = 0.0

        async for msg in query(
            prompt=user_message,
            options=ClaudeAgentOptions(
                system_prompt=system_prompt or None,
                allowed_tools=allowed_tools or [],
                mcp_servers=mcp_servers or [],
                permission_mode="dontAsk",
                max_turns=max_turns,
            ),
        ):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if hasattr(block, "text") and block.text:
                        chunks.append(block.text)
                        if on_chunk:
                            await on_chunk(block.text)
            elif isinstance(msg, ResultMessage):
                cost_usd = msg.total_cost_usd or 0.0

        result = "".join(chunks)

        # ── 4. Write-back ─────────────────────────────────────
        turn = f"User: {user_message[:300]}\nAssistant: {result[:500]}"

        # Working sync — cần cho turn tiếp theo
        await self._backbone.write(turn, scope_session, {"layer": "working"})

        # Episodic async — nếu message đủ dài (heuristic: có nội dung)
        if len(user_message) > 30:
            await self._backbone.write(
                user_message,
                scope_key=scope_user,
                metadata={
                    "layer":    "episodic",
                    "domain":   domain,
                    "cost_usd": cost_usd,
                }
            )

        return result

    async def end_session(self, user_id: str, domain: str):
        """Gọi khi user disconnect — trigger dreaming."""
        scope = f"{user_id}:{domain}"
        await self._backbone.end_session(scope)
```

### 11.3 Telegram bot sử dụng MemoryMiddleware

```python
# bots/agent_sdk_bot/bot.py

from .memory_middleware import MemoryMiddleware

# Setup một lần
backbone   = MemoryBackbone(
    layers=build_layers(),              # VERIFY: cách init layers hiện tại
    processor=build_quality_processor(llm, embedder, episodic_store),
    embedder=embedder,
    dreaming_consolidator=DreamingConsolidator(
        episodic_store, semantic_store, llm, embedder
    ),
)
memory = MemoryMiddleware(backbone, self_learning_store)

# Trong handler
async def handle_message(update, ctx):
    user_id = str(update.effective_user.id)
    text    = update.message.text or ""

    placeholder = await update.message.reply_text("⚙️ Đang xử lý...")
    buffer: list[str] = []

    async def on_chunk(piece: str):
        buffer.append(piece)
        if len(buffer) % 3 == 0:
            try:
                await placeholder.edit_text("".join(buffer))
            except Exception:
                pass

    result = await memory.query_with_memory(
        user_message=text,
        user_id=user_id,
        domain="agent-claude",
        base_system="You are a personal assistant.",
        allowed_tools=["Read", "WebSearch"],
        on_chunk=on_chunk,
    )

    try:
        await placeholder.edit_text("".join(buffer) or result)
    except Exception:
        pass

# Khi session kết thúc (Telegram: user gõ /bye hoặc inactivity timeout)
async def handle_session_end(update, ctx):
    user_id = str(update.effective_user.id)
    await memory.end_session(user_id, "agent-claude")
    await update.message.reply_text("Session ended. Memory consolidated.")
```

---

## 12. Wiring — setup đầy đủ

```python
# Ví dụ setup cho personal use (Ryuu Sensei + agent-claude)

from uaaf.knowledge.memory.working  import WorkingMemoryStore
from uaaf.knowledge.memory.episodic import EpisodicMemoryStore
from uaaf.knowledge.memory.semantic import SemanticMemoryStore
from uaaf.knowledge.memory.self_learning import SelfLearningStore
from uaaf.knowledge.memory.backbone import MemoryBackbone
from uaaf.knowledge.processor      import build_quality_processor
from uaaf.knowledge.consolidator.dreaming import DreamingConsolidator

# Stores — implement IMemoryStore với Postgres backend
episodic_store  = EpisodicMemoryStore(store=PostgresMemoryStore(...))
semantic_store  = SemanticMemoryStore(store=PostgresMemoryStore(...))

# Processor chain
processor = build_quality_processor(
    llm=anthropic_provider,
    embedder=embedder,
    store=episodic_store,
)

# Dreaming
dreamer = DreamingConsolidator(
    episodic_store=episodic_store,
    semantic_store=semantic_store,
    llm_provider=anthropic_provider,
    embedder=embedder,
)

# Backbone — shared giữa Ryuu và agent-claude
shared_backbone = MemoryBackbone(
    layers={
        "working":  WorkingMemoryStore(),
        "episodic": episodic_store,
        "semantic": semantic_store,
    },
    processor=processor,
    embedder=embedder,
    dreaming_consolidator=dreamer,
)

# Self-learning
self_learning = SelfLearningStore(
    store=PostgresHintStore(...),
    llm_provider=anthropic_provider,
)
```

---

## 13. Acceptance criteria

### MemoryProcessor
- [ ] `PassthroughProcessor` hoạt động — behavior giống UAAF cũ, không break test hiện tại
- [ ] `ExtractionFilter`: "Thanks" → `should_store=False`; "User thích dark mode" → `should_store=True, importance='high'`
- [ ] `DuplicateDetector`: entry trùng 95% → skip; entry khác 60% → store
- [ ] `ConflictResolver`: "dùng Postgres" + "switch sang MongoDB" → `CONFLICT_RESOLVED`, conflict_entry_id set
- [ ] `CompositeProcessor`: chain dừng ngay khi bất kỳ bước nào skip
- [ ] Working memory vẫn write sync, không qua processor

### MemoryEntry
- [ ] Fields mới tất cả có default — existing code không break
- [ ] `importance`, `status`, `last_accessed`, `access_count` có thể set qua metadata

### DreamingConsolidator
- [ ] `run_cycle()` chỉ process entries `status='active'`
- [ ] Entries similarity > 0.75 được cluster cùng nhau
- [ ] Cluster được summarize → một semantic fact
- [ ] Semantic fact trùng (cosine > 0.92) → không store thêm
- [ ] `mark_consolidated()` gọi sau khi store semantic thành công
- [ ] Corrections → `update_behavior_hints()` được gọi

### EvictionJob
- [ ] `importance='high'` → không bao giờ archive
- [ ] `importance='medium'`, 60 ngày không access → decayed < 0.10 → archive
- [ ] Entry đã consolidated + decayed < 0.10 → delete
- [ ] Archive hết TTL 30 ngày → delete

### Agent SDK Integration
- [ ] `query_with_memory()` inject memory vào system_prompt trước khi gọi Agent SDK
- [ ] Working write sync sau mỗi turn
- [ ] Episodic write async sau mỗi turn (message > 30 chars)
- [ ] `end_session()` trigger `backbone.end_session()` → dreaming async
- [ ] Streaming chunks forward qua `on_chunk` callback
- [ ] Không có memory → vẫn hoạt động bình thường (system_prompt = base_system)

### Regression
- [ ] `PassthroughProcessor` giữ behavior cũ — tất cả test hiện tại pass
- [ ] Import `from uaaf.knowledge.memory.backbone import MemoryBackbone` vẫn work

---

## 14. Thứ tự triển khai

```
1. MemoryEntry fields mới + PassthroughProcessor
   → Verify không break existing tests

2. EpisodicMemoryStore methods mới
   (get_unconsolidated, mark_consolidated, archive, delete_expired)
   → Unit test từng method

3. ExtractionFilter + test
4. DuplicateDetector + test
5. ConflictResolver + test
6. CompositeProcessor + integration test chain

7. SemanticMemoryStore + test
8. EvictionJob + test

9. DreamingConsolidator + integration test
   (episodic → cluster → summarize → semantic)

10. SelfLearningStore + test

11. MemoryBackbone wiring — inject processor + dreamer
    → Verify PassthroughProcessor behavior unchanged

12. MemoryMiddleware (Agent SDK integration)
    → Integration test với mock Agent SDK

13. Telegram bot integration
    → Smoke test: gửi message → memory ghi → end_session → dreaming chạy
```

---

## 15. Notes quan trọng

**Verify trước khi code:**
```bash
# Kiểm tra MemoryEntry hiện tại có gì
grep -n "class MemoryEntry" uaaf/knowledge/memory/store.py
grep -n "class EpisodicMemoryStore" uaaf/knowledge/memory/episodic.py

# Kiểm tra SemanticMemoryStore và SelfLearningStore đã có gì chưa
cat uaaf/knowledge/memory/semantic.py
cat uaaf/knowledge/memory/self_learning.py

# Kiểm tra MemoryBackbone init signature hiện tại
grep -n "def __init__" uaaf/knowledge/memory/backbone.py

# Verify model string cho Haiku
grep -rn "claude-haiku" uaaf/
```

**LLM calls trong processor:** Dùng model rẻ nhất (Haiku). Extraction + conflict check mỗi cái ~$0.0001. Với 10 messages/ngày = ~$0.002/ngày — không đáng kể.

**Cosine similarity:** Implement đơn giản bằng numpy nếu đã có, hoặc:
```python
def cosine_similarity(a: list[float], b: list[float]) -> float:
    import math
    dot = sum(x*y for x,y in zip(a,b))
    na  = math.sqrt(sum(x*x for x in a))
    nb  = math.sqrt(sum(x*x for x in b))
    return dot / (na * nb) if na and nb else 0.0
```

**Embedding:** Verify UAAF đã có `IEmbedder` hoặc embedder trong providers. Nếu chưa có, dùng Anthropic embeddings API trực tiếp.
