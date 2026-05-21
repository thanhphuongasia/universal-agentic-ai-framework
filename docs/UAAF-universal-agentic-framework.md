# Universal Agentic AI Framework (RYUU)
## Phân tích pattern + Software Design Document

> **Mục tiêu**: Trích xuất các pattern chung từ ba hệ thống đã thiết kế (MAAF Per-Domain, Personal AI Assistant, AI Code Analysis), từ đó propose một framework lõi reusable cho cả conversational AI và batch processing, ở bất kỳ domain nào.
>
> **Triết lý**: *Không phải framework nào abstract nhiều cũng tốt. Framework tốt là framework abstract đúng chỗ — chỗ thực sự lặp lại, không phải chỗ "có thể" lặp lại.*

**Version**: 1.0  
**Status**: Design proposal  
**Last Updated**: 2026-05-07

---

## Phần I — Phân tích so sánh & Pattern Extraction

### 1. Ba hệ thống nguồn

| | MAAF Per-Domain | Personal AI Assistant | AI Code Analysis |
|---|---|---|---|
| **Mode chính** | Conversational, agentic | Conversational, persistent memory | Hybrid: batch ingestion + conversational analysis |
| **Domain pin** | Cứng từ khởi tạo | Cá nhân hóa cross-platform | Code/repo |
| **Dữ liệu spine** | Memory layers | Memory layers | Graph (Neo4j) + memory phụ |
| **Output style** | Action + answer | Answer | Answer + diagram + finding |
| **Trust level** | Tùy domain (low→high) | Medium | Medium-high (compliance) |
| **Cost sensitivity** | Tùy domain | High | High |

Ba hệ thống thoạt nhìn rất khác nhau: một cái là chatbot cá nhân, một cái là chatbot enterprise multi-app, một cái là batch parser code. Nhưng khi đào sâu, **80% các kiến trúc lặp lại**. Đây là cơ sở để framework hóa.

### 2. Bảy pattern chung — đây là **xương sống của framework**

#### Pattern 1: Cognitive Layer — kỹ thuật làm AI nghĩ tốt hơn

Cả ba hệ thống đều có nhu cầu này, dù gọi tên khác nhau:

- **MAAF**: ReAct loop, max iterations, prompt building hierarchical.
- **AI Assistant**: section 11 "Cognitive Layer" với extended thinking, self-consistency, best-of-N, ToT, Reflexion, Evaluator-Optimizer, Architect-Editor split.
- **Code Analysis**: ReAct cho impact analysis, multi-agent verification (generator + critic), confidence scoring.

**Bản chất chung**: Mỗi LLM call đơn lẻ là *autocomplete*. Để có *reasoning*, cần một layer điều phối nhiều LLM call với strategy phù hợp với complexity. Đây không phải "feature riêng của AI Assistant" — đây là requirement của **mọi** system muốn output đáng tin.

**Pattern hóa được**: Strategy selector dựa vào (intent, complexity, trust_level) → chọn cognitive strategy phù hợp. Strategies là plugin: Direct, ReAct, Best-of-N, ToT, Self-Consistency, Evaluator-Optimizer.

#### Pattern 2: Intent Understanding — phân tích user input thông minh

Ba hệ thống đều có một bước "hiểu user muốn gì trước khi làm":

- **MAAF**: `IntentAnalyzer` — classify intent type, extract entities, detect ambiguity → trigger clarification.
- **AI Assistant**: classify intent → quyết định model routing.
- **Code Analysis**: classify câu hỏi user (impact analysis vs explain vs diagram) → chọn ReAct strategy và tools.

**Bản chất chung**: Input của user **luôn dưới optimal** so với cái họ muốn. Vai trò của intent layer là *amplifier* — biến "câu hỏi mơ hồ" thành "structured task" mà phần sau xử lý được.

**Pattern hóa được**: 
- `IntentAnalyzer` là một module pluggable (LLM-based hoặc rule-based hoặc hybrid).
- Output là `StructuredIntent` — một schema chung gồm: `intent_type`, `action`, `entities`, `complexity`, `confidence`, `ambiguous`, `clarification_needed`.
- Khi `confidence < threshold` hoặc `ambiguous = true` → trigger clarification flow tự động.

#### Pattern 3: Memory Hierarchy — bộ nhớ nhiều tầng

Cả ba có structure giống nhau đến đáng ngạc nhiên:

| Tầng | MAAF | AI Assistant | Code Analysis |
|---|---|---|---|
| **Working** | Per session, scratchpad | Per session, recent N turns | Per query, ReAct trace |
| **Episodic** | Past sessions, vector | Past conversations, vector | Past Q&A, vector |
| **Semantic** | User profile, domain knowledge | User profile, preferences | Repo metadata, framework rules |
| **Self-learning** | Feedback → patterns → prompt perf | (chưa explicit) | Verification feedback |

Ngoài ra, MAAF và AI Assistant đều có khái niệm tương tự "thought signatures" — capture *quá trình nghĩ*, không chỉ *kết quả*.

**Bản chất chung**: Bộ nhớ AI không phải là một database. Là *bốn database khác bản chất*: ngắn hạn / sự kiện / kiến thức / phản hồi. Mỗi tầng có lifecycle, retrieval strategy, và write trigger riêng.

**Pattern hóa được**: 
- Interface `IMemoryStore` chung cho 4 tầng.
- `MemoryContextBuilder` assembly từ 4 tầng theo token budget — đây là logic phức tạp nhưng giống nhau giữa các hệ thống.
- Bi-temporal versioning (từ AI Assistant) — pattern advanced cho memory cần track validity over time.

#### Pattern 4: Tool Execution với Permission Boundary

Ba hệ thống đều có:

- **MAAF**: `ToolExecutor` check tool whitelist từ `DomainConfig`, validate args, sandboxed execution (sandbox cho code domain), audit log.
- **AI Assistant**: Tool calls qua adapter pattern, each provider has its tool API.
- **Code Analysis**: Tools = graph_query, file_read, semgrep_invoke. Critical action (delete, modify) **không** trong tool registry của analysis agent (chỉ ingestion có).

**Bản chất chung**: Tool là *attack surface*. Cùng một LLM, nếu cho thêm tool `execute_trade` thì rủi ro hoàn toàn khác. Permission boundary phải ở *framework level*, không phải agent-level — vì agent có thể bị prompt injection override.

**Pattern hóa được**:
- `ToolRegistry` per-context (domain/agent), whitelist explicit.
- `ToolExecutor` enforce permission **trước** khi gọi tool, không sau.
- Schema validation, timeout, retry, output sanitization là cross-cutting — không phải mỗi tool tự lo.

#### Pattern 5: Multi-Agent Orchestration với Verification

- **MAAF**: Orchestrator decompose goal → TaskDAG → parallel/sequential agents → aggregate.
- **AI Assistant**: Mostly single-agent, nhưng có Evaluator-Optimizer (2 vai trò).
- **Code Analysis**: Generator agent + Verifier agent, multi-stage state machine cho ingestion.

**Bản chất chung**: Một agent đơn lẻ không đủ tin cậy cho task phức tạp. Pattern lặp lại: **decompose → execute (có thể parallel) → verify → aggregate**. Verifier có thể là LLM (LLM-as-judge) hoặc deterministic (test suite, schema validation, ground truth comparison).

**Pattern hóa được**:
- `Orchestrator` interface với pattern decompose/dispatch/aggregate.
- Verifier là first-class concept, không phải optional bolt-on.
- Workflow state machine với checkpoint cho long-running batch.

#### Pattern 6: Cross-Cutting Concerns — bắt buộc, không phải optional

Cả ba đều list ra cùng một bộ:

| Concern | MAAF | AI Assistant | Code Analysis |
|---|---|---|---|
| Cost tracking | Có, với budget enforcement | Có, per-user budget | Có, hard cap per repo |
| Rate limiting | Có | Có | Có (qua model router) |
| Audit log | Có (compliance cho stock) | Có (GDPR) | Có (trace LLM output → source) |
| Distributed tracing | Có (correlation_id) | Có | Có |
| Error handling | Tiered: retryable/degraded/fatal | Circuit breaker + fallback chain | Layered verification |

**Bản chất chung**: Cross-cutting không phải decorator thêm vào sau. Phải ở base class, agent không thể opt-out. Đây là điều phân biệt prototype với production.

**Pattern hóa được**: `BaseAgent` inject sẵn cost tracker, rate limiter, tracer, audit logger. Mọi `BaseAgent` subclass tự động được instrument.

#### Pattern 7: Provider Abstraction — tránh vendor lock-in

- **MAAF**: `ILLMClient` interface, multi-provider.
- **AI Assistant**: `IModelProvider` với ModelRouter, fallback chain explicit.
- **Code Analysis**: Model router theo complexity, cheap → mid → top tier; fallback nếu provider down.

**Bản chất chung**: LLM provider là *commodity*. Hôm nay Claude tốt nhất, mai có thể là model khác. Lock-in vào một provider = fragile + đắt.

**Pattern hóa được**: 
- Provider interface chung (`complete`, `stream`, `embed`, `estimate_cost`).
- Model router với routing matrix (intent × complexity → model).
- Circuit breaker per provider.
- Fallback chain configurable.

### 3. Ba điểm khác biệt — chỗ framework KHÔNG nên ép

Quan trọng không kém phần chung là phần *khác*. Framework ép chuẩn hóa chỗ này = sai.

**Khác biệt 1: Spine của data**

- Conversational systems (MAAF, AI Assistant): spine là **memory layers**. Mọi context build quanh memory.
- Code Analysis: spine là **graph**. Memory chỉ là layer phụ. AI là *enhancer* của graph.

**Implication**: Framework không được giả định "memory là spine". Phải có khái niệm **Knowledge Backbone** — pluggable, có thể là memory hierarchy, graph, vector index, hoặc combo.

**Khác biệt 2: Operation mode**

- Conversational: request-response, latency-sensitive, stateless API tier.
- Batch (ingestion): long-running, throughput-sensitive, stateful với checkpoint.

**Implication**: Framework phải hỗ trợ cả hai mode. `Workflow` abstraction (state machine + checkpoint) cần coexist với `RequestHandler` abstraction (stateless, fast).

**Khác biệt 3: Trust và verification level**

- Todo app: low trust, không cần verify nặng.
- Stock trading: compliance, audit 7 năm, multi-layer verification.
- Code analysis: medium-high, ground truth comparison.

**Implication**: Verification là *config*, không phải *hardcoded*. `TrustLevel` quyết định verification stack được activate.

### 4. Anti-pattern cần tránh khi framework hóa

Đây là phần thường thiếu trong design doc, nhưng cực quan trọng — *biết cái gì không nên abstract*:

- **Đừng abstract domain logic**. Domain agent code phải ở phía product, không phải framework. Framework chỉ cung cấp `BaseAgent`. Cám dỗ "thêm `TaskCreationAgent` vào framework cho dùng chung" → fail vì hai apps "todo-like" sẽ có nhu cầu khác nhau.
- **Đừng abstract prompt content**. Framework cung cấp `PromptRegistry` và versioning, không cung cấp prompt template chung. Prompt là tài sản của domain.
- **Đừng abstract storage schema**. Framework cung cấp interface `IMemoryStore`, không định schema bảng. Memory schema của Stock Trading khác Code Analysis.
- **Đừng force một orchestration pattern**. Hỗ trợ ReAct, Plan-Execute, Multi-Agent debate, Single-call. Không ép tất cả phải ReAct.

---

## Phần II — RYUU Software Design Document

### 5. Goals & Non-Goals

#### Goals

| Goal | Mô tả |
|---|---|
| **G1: Multi-mode** | Hỗ trợ cả conversational (interactive) và batch (long-running) workloads từ cùng một core |
| **G2: Multi-domain** | Một product team config domain, không sửa core |
| **G3: Multi-knowledge-backbone** | Memory layers / Graph / Vector — đều là plugin |
| **G4: Cognitive flexibility** | Cognitive strategy là plugin, chọn theo intent×complexity |
| **G5: Observability built-in** | Cost / Trace / Audit không phải opt-in |
| **G6: Provider-agnostic** | Đổi LLM provider không sửa product code |
| **G7: Verification as first-class** | Verifier là khái niệm chính thức, không phải bolt-on |

#### Non-Goals

- **Không** là LLM provider.
- **Không** là vector DB / graph DB — tích hợp thứ có sẵn.
- **Không** cung cấp domain-specific agents (đó là việc của product).
- **Không** cung cấp prompt templates ngoài tooling support cho versioning.
- **Không** force opinion về deployment (kubernetes vs serverless vs bare metal).

### 6. Functional Requirements

#### FR-1 (Core)
- **FR-1.1**: Khởi tạo framework với `RuntimeConfig` (domain pin hoặc multi-domain registry, knowledge backbone, providers).
- **FR-1.2**: Xử lý cả `InteractiveRequest` (user → response) và `BatchWorkflow` (long-running, checkpointed).
- **FR-1.3**: Pluggable cognitive strategies — chọn theo intent + complexity.
- **FR-1.4**: Pluggable knowledge backbone — memory hierarchy, graph, hybrid.

#### FR-2 (Intent & Routing)
- **FR-2.1**: Intent analyzer modular (LLM/rule/hybrid).
- **FR-2.2**: Output `StructuredIntent` với confidence và ambiguity flag.
- **FR-2.3**: Auto-trigger clarification khi confidence thấp hoặc ambiguous.
- **FR-2.4**: Complexity estimator để route đến cognitive strategy phù hợp.

#### FR-3 (Memory & Knowledge)
- **FR-3.1**: Memory hierarchy 4 tầng với interface chung.
- **FR-3.2**: Bi-temporal support (optional per memory type).
- **FR-3.3**: `MemoryContextBuilder` assembly có token budget.
- **FR-3.4**: Knowledge backbone alternative (graph spine cho hệ thống không memory-centric).

#### FR-4 (Tools & Execution)
- **FR-4.1**: ToolRegistry per context (domain / agent), whitelist explicit.
- **FR-4.2**: ToolExecutor enforce permission, schema validation, timeout, retry.
- **FR-4.3**: Sandbox support cho tool có rủi ro cao.

#### FR-5 (Orchestration)
- **FR-5.1**: Multiple orchestration patterns: ReAct, Plan-Execute, Multi-Agent, Single-Call.
- **FR-5.2**: Workflow state machine với checkpoint cho batch.
- **FR-5.3**: Verification step là first-class trong orchestration graph.

#### FR-6 (Cross-Cutting)
- **FR-6.1**: Cost tracking với budget enforcement (per user / per task / per domain).
- **FR-6.2**: Rate limiting per user / per domain / per provider.
- **FR-6.3**: Distributed tracing với correlation ID.
- **FR-6.4**: Audit log cho compliance.
- **FR-6.5**: Error handling tiered (retryable/degraded/fatal).

#### FR-7 (Provider Layer)
- **FR-7.1**: LLM provider abstraction (`complete`, `stream`, `embed`, `estimate_cost`).
- **FR-7.2**: Model router theo intent × complexity.
- **FR-7.3**: Circuit breaker + fallback chain.

### 7. Non-Functional Requirements

| Metric | Target | Lý do |
|---|---|---|
| Framework overhead | <50ms per request | Framework không được trở thành bottleneck |
| Cold start | <2s | Khởi tạo plugin pipeline phải nhanh |
| Memory footprint base | <200MB | Để run được trên small instances |
| Plugin contract stability | Semver, breaking change ≤ 1 lần/năm | Product team plan được upgrade |
| Test coverage core | >85% | Framework là foundation, regression tốn kém |
| Documentation coverage | 100% public API | Framework không doc = framework chết |

### 8. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          PRODUCT LAYER                                  │
│  Todo App │ Stock App │ Code Analysis │ Personal AI │ ...new domain     │
│  (mỗi product config RYUU với plugin riêng)                            │
└────────────────────────────┬────────────────────────────────────────────┘
                             │ uses
┌────────────────────────────▼────────────────────────────────────────────┐
│                         RYUU RUNTIME                                    │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    INTERACTION TIER                              │  │
│  │  ┌────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │  │
│  │  │ Request    │  │ Workflow     │  │ Stream Manager            │ │  │
│  │  │ Handler    │  │ Engine       │  │ (SSE / WebSocket)         │ │  │
│  │  │ (sync)     │  │ (batch)      │  │                           │ │  │
│  │  └────────────┘  └──────────────┘  └──────────────────────────┘ │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    INTENT & ROUTING TIER                         │  │
│  │  Intent Analyzer │ Complexity Estimator │ Strategy Selector       │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    COGNITIVE TIER                                │  │
│  │  Strategies (plugin):                                            │  │
│  │  ┌────────┐ ┌──────┐ ┌────────────┐ ┌─────────────────┐ ┌────┐  │  │
│  │  │Direct  │ │ReAct │ │Best-of-N   │ │Tree-of-Thoughts │ │... │  │  │
│  │  └────────┘ └──────┘ └────────────┘ └─────────────────┘ └────┘  │  │
│  │                                                                  │  │
│  │  Verifier Pipeline (plugin):                                     │  │
│  │  Schema Check → LLM-as-Judge → Ground Truth → Human-in-Loop      │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    EXECUTION TIER                                │  │
│  │  Agent Pool │ Tool Executor │ Sandbox Manager                    │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    KNOWLEDGE TIER (pluggable backbone)           │  │
│  │  ┌────────────────────────┐    ┌────────────────────────────┐    │  │
│  │  │ Memory Backbone:       │ OR │ Graph Backbone:            │    │  │
│  │  │ Working/Episodic/      │    │ Code Graph / Domain Graph  │    │  │
│  │  │ Semantic/SelfLearning  │    │ + Vector index             │    │  │
│  │  └────────────────────────┘    └────────────────────────────┘    │  │
│  │  Context Assembler (token budget management)                     │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    PROVIDER TIER                                 │  │
│  │  Model Router │ Provider Adapters │ Circuit Breaker │ Fallback   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │              CROSS-CUTTING (every tier observed)                 │  │
│  │  Cost Tracker │ Rate Limiter │ Tracer │ Audit │ Error Handler    │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

**Tại sao chia thành tier này, không phải kiểu khác?**

Mỗi tier có **một loại trách nhiệm thuần**:
- Interaction tier: vào/ra với thế giới ngoài.
- Intent tier: hiểu user muốn gì.
- Cognitive tier: nghĩ.
- Execution tier: làm.
- Knowledge tier: nhớ và biết.
- Provider tier: nói với LLM.
- Cross-cutting: quan sát mọi thứ.

Giả sử bạn muốn thêm cognitive strategy mới (vd "Debate"). Bạn chỉ chạm vào Cognitive tier, không cần biết Intent tier hay Provider tier hoạt động ra sao. Đây là *separation of concerns thực sự*, không phải chia layer cho có.

### 9. Low-Level Design — Core Abstractions

#### 9.1. RuntimeConfig — entry point

```python
@dataclass
class RuntimeConfig:
    runtime_id: str
    mode: RuntimeMode  # SINGLE_DOMAIN | MULTI_DOMAIN | BATCH_ONLY | HYBRID
    
    # Domain registry (single hoặc multi)
    domains: Dict[str, DomainConfig]
    
    # Backbone configuration
    knowledge_backbone: KnowledgeBackboneConfig  # MemoryBased | GraphBased | Hybrid
    
    # Provider configuration  
    providers: List[ProviderConfig]
    routing_matrix: RoutingMatrix
    fallback_chain: List[ProviderId]
    
    # Cognitive strategies registered
    cognitive_strategies: Dict[StrategyId, StrategyConfig]
    
    # Cross-cutting
    cost_policy: CostPolicy
    rate_policy: RatePolicy
    audit_config: AuditConfig
    trust_default: TrustLevel
```

**Tại sao có `mode`?**

Một runtime có thể chạy thuần conversational (Personal AI), thuần batch (Code ingestion), hoặc hybrid (Code analysis = ingestion batch + Q&A interactive). Mode quyết định component nào được khởi tạo, tránh load không cần thiết.

#### 9.2. StructuredIntent — output của Intent tier

```python
@dataclass
class StructuredIntent:
    intent_type: str           # domain-specific: "create_task" / "explain_class" / "buy_recommendation"
    action: str                # generic verb: create/read/update/delete/explain/recommend
    entities: Dict[str, Any]   # extracted entities
    
    complexity: ComplexityLevel    # LOW | MEDIUM | HIGH
    estimated_iterations: int      # cho cognitive layer biết budget
    
    confidence: float              # 0-1
    ambiguous: bool
    clarification_questions: List[str]  # auto-generated nếu ambiguous
    
    suggested_strategy: StrategyId  # gợi ý cho strategy selector (không bắt buộc theo)
    suggested_model_tier: ModelTier
    
    metadata: Dict[str, Any]   # domain-specific
```

#### 9.3. CognitiveStrategy — interface plugin

```python
class ICognitiveStrategy(Protocol):
    strategy_id: str
    
    # Strategy có phù hợp với intent này không?
    def applicable(self, intent: StructuredIntent, context: ExecutionContext) -> bool: ...
    
    # Estimate cost trước khi run
    def estimate_cost(self, intent, context) -> CostEstimate: ...
    
    # Main execution
    async def execute(
        self,
        intent: StructuredIntent,
        context: ExecutionContext,
        agent_pool: AgentPool,
        verifier: Verifier,
    ) -> CognitiveResult: ...
```

**Strategy implementations**:

- `DirectStrategy`: 1 LLM call, không loop. Cho LOW complexity.
- `ReActStrategy`: reason→act→observe loop với max_iterations.
- `BestOfNStrategy`: generate N → verifier chọn best.
- `TreeOfThoughtsStrategy`: explore branches, evaluate, prune.
- `SelfConsistencyStrategy`: N samples → majority vote.
- `EvaluatorOptimizerStrategy`: generator + evaluator loop.
- `ArchitectEditorStrategy`: top-tier model design + cheap model implement.

**Quan trọng**: framework không cố hỗ trợ tất cả từ đầu. Bắt đầu với 3 (`Direct`, `ReAct`, `EvaluatorOptimizer`) và thêm dần qua plugin contract.

#### 9.4. KnowledgeBackbone — abstraction kép

Đây là điểm sáng tạo nhất so với MAAF — generalize spine của data:

```python
class IKnowledgeBackbone(Protocol):
    backbone_type: BackboneType  # MEMORY | GRAPH | HYBRID
    
    async def assemble_context(
        self,
        intent: StructuredIntent,
        scope: ContextScope,  # user_id, session_id, domain, tenant_id...
        token_budget: int,
    ) -> AssembledContext: ...
    
    async def write(self, observation: Observation, scope: ContextScope) -> None: ...
    
    async def query(self, query: Query, scope: ContextScope) -> QueryResult: ...

class MemoryBackbone(IKnowledgeBackbone):
    """4-layer hierarchy: Working/Episodic/Semantic/SelfLearning"""
    layers: Dict[MemoryLayer, IMemoryStore]

class GraphBackbone(IKnowledgeBackbone):
    """Graph DB primary, vector phụ trợ"""
    graph: IGraphStore
    vector_index: IVectorStore  # optional augment

class HybridBackbone(IKnowledgeBackbone):
    """Code Analysis style: graph spine + memory phụ"""
    primary: IGraphStore
    secondary_memory: MemoryBackbone
```

**Điểm tinh tế**: dù backbone là gì, interface với phần còn lại của framework là `assemble_context() → AssembledContext`. Cognitive tier không cần biết spine là memory hay graph — chỉ thấy "context có sẵn, dùng đi".

#### 9.5. Verifier Pipeline — first-class

```python
class IVerifier(Protocol):
    verifier_id: str
    
    async def verify(self, output: AgentOutput, context: ExecutionContext) -> VerificationResult: ...

@dataclass
class VerificationResult:
    passed: bool
    confidence: float
    issues: List[Issue]
    suggested_action: Action  # ACCEPT | REGENERATE | ESCALATE_HUMAN | REJECT
```

**Verifier implementations**:

- `SchemaVerifier`: output có match JSON schema không.
- `LLMJudgeVerifier`: dùng LLM khác (cheap model thường) để judge.
- `GroundTruthVerifier`: so sánh với deterministic source (vd graph traversal cho code analysis).
- `MultiAgentDebateVerifier`: N agents debate, consensus quyết định.
- `HumanReviewVerifier`: queue cho human review (dùng cho output critical, async).

**Verifier pipeline = chain**: SchemaVerifier → LLMJudge → GroundTruth → (nếu còn doubt) HumanReview.

Trong Code Analysis blog đã propose 4-layer verification — đây là instance của pattern chung này.

#### 9.6. BaseAgent — instrumentation built-in

```python
class BaseAgent(ABC):
    """
    Mọi agent (LLM-based hoặc deterministic) đều extend class này.
    Cross-cutting concerns inject sẵn — agent không thể opt-out.
    """
    agent_id: str
    
    # Injected by framework — not optional
    cost_tracker: CostTracker
    rate_limiter: RateLimiter
    tracer: Tracer
    audit_logger: AuditLogger
    
    @abstractmethod
    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult: ...
    
    async def execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        # Template method — instrumentation tự động
        with self.tracer.span(self.agent_id, task.task_id):
            await self.rate_limiter.acquire(context.user_id, self.agent_id)
            self.audit_logger.log_start(task, context)
            
            try:
                result = await self._execute(task, context)
                self.cost_tracker.record(result.cost)
                self.audit_logger.log_complete(task, result)
                return result
            except Exception as e:
                self.audit_logger.log_error(task, e)
                raise
```

**Tại sao template method?** Để cross-cutting **không thể bị forget**. Agent developer chỉ implement `_execute`, framework lo phần còn lại.

#### 9.7. Workflow Engine — cho batch mode

```python
class WorkflowEngine:
    """
    State machine với checkpoint, dùng cho long-running batch (vd Code ingestion).
    """
    
    state_machine: StateMachine
    checkpoint_store: ICheckpointStore
    
    async def run(self, workflow: Workflow, input: WorkflowInput) -> WorkflowResult:
        state = workflow.initial_state
        while not state.is_terminal:
            try:
                next_state, output = await state.execute(input, self.context)
                await self.checkpoint_store.save(workflow.id, next_state, output)
                state = next_state
            except RetryableError:
                # exponential backoff + retry
                pass
            except FatalError:
                state = workflow.error_state
        return state.result
    
    async def resume(self, workflow_id: str) -> WorkflowResult:
        checkpoint = await self.checkpoint_store.latest(workflow_id)
        return await self._continue_from(checkpoint)
```

**Đây là gì so với MAAF orchestrator?** MAAF có TaskDAG cho conversational agentic. WorkflowEngine cho batch — long-running, đa-stage, có thể die và resume sau nhiều giờ. Hai abstractions tồn tại song song, không thay thế nhau.

### 10. Class Diagram

```
                        ┌──────────────────────────┐
                        │      RuntimeConfig       │
                        ├──────────────────────────┤
                        │ + mode                   │
                        │ + domains                │
                        │ + knowledge_backbone     │
                        │ + providers              │
                        │ + cognitive_strategies   │
                        │ + cost_policy            │
                        └────────────┬─────────────┘
                                     │ inject
                        ┌────────────▼─────────────┐
                        │       RYUU Runtime       │
                        │  (entry point)           │
                        ├──────────────────────────┤
                        │ + handle_request()       │
                        │ + run_workflow()         │
                        │ + shutdown()             │
                        └────────────┬─────────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        │                            │                            │
        ▼                            ▼                            ▼
┌──────────────────┐    ┌──────────────────────┐    ┌─────────────────────┐
│  IntentTier      │    │  CognitiveTier       │    │  ExecutionTier      │
├──────────────────┤    ├──────────────────────┤    ├─────────────────────┤
│ - analyzer       │    │ - strategy_selector  │    │ - agent_pool        │
│ - estimator      │    │ - strategies[]       │    │ - tool_executor     │
│ - clarifier      │    │ - verifier_pipeline  │    │ - sandbox_mgr       │
└──────────────────┘    └──────────┬───────────┘    └──────────┬──────────┘
                                   │                            │
                                   │uses                        │uses
                                   ▼                            │
            ┌──────────────────────────────────────┐            │
            │     <<interface>>                    │            │
            │     ICognitiveStrategy               │            │
            ├──────────────────────────────────────┤            │
            │ + applicable(intent, ctx): bool      │            │
            │ + estimate_cost(intent): Cost        │            │
            │ + execute(intent, ctx, pool, ver)    │            │
            └──────────────────┬───────────────────┘            │
                               △                                │
              ┌────────────────┼────────────────┐               │
              │                │                │               │
       ┌──────┴────┐   ┌───────┴─────┐  ┌──────┴───────┐        │
       │DirectStrat│   │ReActStrat   │  │BestOfNStrat  │        │
       └───────────┘   └─────────────┘  └──────────────┘        │
                                                                │
                       ┌────────────────────────────────────────┘
                       ▼
            ┌──────────────────────────┐
            │      <<abstract>>        │
            │      BaseAgent           │
            ├──────────────────────────┤
            │ - cost_tracker           │
            │ - rate_limiter           │
            │ - tracer                 │
            │ - audit_logger           │
            ├──────────────────────────┤
            │ + execute(task,ctx)      │ <-- template method
            │ # _execute(task,ctx)     │ <-- abstract, subclass impl
            └──────────────┬───────────┘
                           △
        ┌──────────────────┼──────────────────────┐
        │                  │                      │
   ┌────┴──────┐   ┌───────┴──────┐    ┌─────────┴─────────┐
   │LLMAgent   │   │Deterministic │    │VerifierAgent      │
   │           │   │Agent         │    │                   │
   │(uses LLM) │   │(parser, etc) │    │(LLM-as-judge etc) │
   └───────────┘   └──────────────┘    └───────────────────┘

           ┌──────────────────────────────────┐
           │   <<interface>>                  │
           │   IKnowledgeBackbone             │
           ├──────────────────────────────────┤
           │ + assemble_context(intent,scope) │
           │ + write(observation, scope)      │
           │ + query(query, scope)            │
           └──────────────┬───────────────────┘
                          △
        ┌─────────────────┼─────────────────────┐
        │                 │                     │
 ┌──────┴────────┐  ┌─────┴──────┐    ┌────────┴────────┐
 │MemoryBackbone │  │GraphBackb. │    │HybridBackbone   │
 │(4 layers)     │  │(graph DB)  │    │(graph + memory) │
 └───────────────┘  └────────────┘    └─────────────────┘

           ┌──────────────────────────────────┐
           │   <<interface>>                  │
           │   IVerifier                      │
           ├──────────────────────────────────┤
           │ + verify(output, ctx): VerResult │
           └──────────────┬───────────────────┘
                          △
        ┌────────────┬────┴──────┬───────────────┐
        │            │           │               │
   ┌────┴───┐  ┌─────┴────┐ ┌───┴──────┐  ┌──────┴────┐
   │Schema  │  │LLMJudge  │ │GroundTr. │  │HumanReview│
   └────────┘  └──────────┘ └──────────┘  └───────────┘

           ┌──────────────────────────────────┐
           │   <<interface>>                  │
           │   ILLMProvider                   │
           ├──────────────────────────────────┤
           │ + complete(prompt): Response     │
           │ + stream(prompt): AsyncIter      │
           │ + embed(text): Vector            │
           │ + estimate_cost(req): Cost       │
           └──────────────────────────────────┘
                          △
        ┌─────────────────┼─────────────────┐
        │                 │                 │
   ┌────┴────┐     ┌──────┴────┐    ┌──────┴─────┐
   │OpenAI   │     │Anthropic  │    │SelfHosted  │
   │Adapter  │     │Adapter    │    │Adapter     │
   └─────────┘     └───────────┘    └────────────┘

   ┌────────────────────────────────────────────────┐
   │            ModelRouter                         │
   ├────────────────────────────────────────────────┤
   │ - providers: Dict[ProviderId, ILLMProvider]   │
   │ - routing_matrix: Matrix[Intent×Complexity]    │
   │ - circuit_breaker: CircuitBreaker              │
   │ - fallback_chain: List[ProviderId]            │
   ├────────────────────────────────────────────────┤
   │ + route(intent, complexity): ILLMProvider     │
   │ + record_failure(provider): void               │
   └────────────────────────────────────────────────┘
```

### 11. Sequence Diagrams

#### 11.1. Conversational request (single-domain mode)

```
Product   RYUU     IntentTier  CognitiveTier  KnowledgeBB  AgentPool  Verifier  Provider
   │       │           │            │             │           │          │         │
   │─req──▶│           │            │             │           │          │         │
   │       │──analyze─▶│            │             │           │          │         │
   │       │           │──LLM───────────────────────────────────────────────────▶ │
   │       │           │◀───StructuredIntent ────────────────────────────────────  │
   │       │◀──intent──│            │             │           │          │         │
   │       │           │            │             │           │          │         │
   │       │           │ [if ambiguous → clarify, return early]                    │
   │       │           │            │             │           │          │         │
   │       │──select strategy──────▶│             │           │          │         │
   │       │◀──ReActStrategy ───────│             │           │          │         │
   │       │           │            │             │           │          │         │
   │       │           │            │──assemble──▶│           │          │         │
   │       │           │            │◀──context───│           │          │         │
   │       │           │            │             │           │          │         │
   │       │           │            │ [ReAct loop iterates]                        │
   │       │           │            │──dispatch task ─────▶│              │        │
   │       │           │            │             │           │─LLM call ──────▶ │
   │       │           │            │             │           │◀─response ─────  │
   │       │           │            │             │           │ tool call         │
   │       │           │            │             │           │ tool result       │
   │       │           │            │◀──result────│           │          │         │
   │       │           │            │             │           │          │         │
   │       │           │            │──verify──────────────────────────▶ │        │
   │       │           │            │◀──VerificationResult──────────────  │        │
   │       │           │            │             │           │          │         │
   │       │           │            │ [if failed → regenerate or escalate]         │
   │       │           │            │             │           │          │         │
   │       │           │            │──write episode─────────▶│           │        │
   │       │◀──result──────────────│             │           │          │         │
   │◀─resp─│           │            │             │           │          │         │
   │       │           │            │             │           │          │         │
   │       │ [ASYNC: cost log, audit log, self-learning update]                    │
```

**Điểm tinh tế**: verifier nằm **trước** memory write. Output không pass verification thì không được lưu — tránh memory bị poisoned bởi hallucination.

#### 11.2. Batch workflow (Code ingestion mode)

```
Trigger    Workflow    StateMachine  CheckpointStore  AgentPool  KnowledgeBB
   │          │             │              │             │           │
   │──start──▶│             │              │             │           │
   │          │─init state─▶│              │             │           │
   │          │             │              │             │           │
   │          │ [State: FETCHING]                                     │
   │          │             │              │             │           │
   │          │──exec──────▶│              │             │           │
   │          │             │──fetch source──────────────▶│           │
   │          │             │◀──files─────────────────────│           │
   │          │             │──save checkpoint──▶│        │           │
   │          │◀──next state│              │             │           │
   │          │             │              │             │           │
   │          │ [State: PARSING — has crashed mid-way previously]     │
   │          │──resume from checkpoint──▶│             │             │
   │          │◀──checkpoint data─────────│             │             │
   │          │             │              │             │             │
   │          │ [State: ENHANCING — calls LLM for semantic enrich]    │
   │          │──exec──────▶│              │             │             │
   │          │             │──dispatch───────────────▶  │             │
   │          │             │              │      LLM call             │
   │          │             │◀──enriched nodes────────  │             │
   │          │             │──verify (LLMJudge + GroundTruth)         │
   │          │             │──save checkpoint──▶│        │             │
   │          │             │              │             │             │
   │          │ [State: INDEXING]                                       │
   │          │             │──write to graph────────────────────────▶│
   │          │             │              │             │             │
   │          │ [State: COMPLETE]                                       │
```

### 12. ERD — Cross-cutting & Framework Tables

```
┌─────────────────────────────┐    ┌─────────────────────────────┐
│       runtime_instances     │    │      domain_configs         │
├─────────────────────────────┤    ├─────────────────────────────┤
│ id (PK)                     │1  *│ id (PK)                     │
│ runtime_id                  │────│ runtime_id (FK)             │
│ mode                        │    │ domain_name                 │
│ started_at                  │    │ trust_level                 │
│ version                     │    │ allowed_tools (jsonb)       │
└─────────────────────────────┘    │ cost_budget_daily           │
                                   │ max_iterations              │
                                   └─────────────────────────────┘

┌─────────────────────────────┐    ┌─────────────────────────────┐
│      execution_traces       │    │      cognitive_traces       │
├─────────────────────────────┤    ├─────────────────────────────┤
│ correlation_id (PK)         │1  1│ correlation_id (FK)         │
│ runtime_id                  │────│ strategy_used               │
│ user_id                     │    │ iterations                  │
│ domain                      │    │ thinking_tokens             │
│ intent_type                 │    │ verifier_passes             │
│ complexity                  │    │ verifier_failures           │
│ started_at                  │    │ alternatives_explored       │
│ completed_at                │    │ final_confidence            │
│ status                      │    └─────────────────────────────┘
│ total_cost_usd              │
└──────────────┬──────────────┘
               │ 1
               │ *
┌──────────────▼──────────────┐    ┌─────────────────────────────┐
│        llm_calls            │    │        tool_calls           │
├─────────────────────────────┤    ├─────────────────────────────┤
│ id (PK)                     │    │ id (PK)                     │
│ correlation_id (FK)         │    │ correlation_id (FK)         │
│ provider                    │    │ tool_name                   │
│ model                       │    │ args_hash                   │
│ input_tokens                │    │ result_hash                 │
│ output_tokens               │    │ duration_ms                 │
│ cost_usd                    │    │ success                     │
│ latency_ms                  │    │ retry_count                 │
│ purpose                     │    └─────────────────────────────┘
│ (intent/cognitive/verify)   │
└─────────────────────────────┘

┌─────────────────────────────┐    ┌─────────────────────────────┐
│      verification_records   │    │      cost_budgets           │
├─────────────────────────────┤    ├─────────────────────────────┤
│ id (PK)                     │    │ id (PK)                     │
│ correlation_id (FK)         │    │ scope                       │
│ verifier_id                 │    │ scope_id                    │
│ output_hash                 │    │ period                      │
│ passed                      │    │ limit_usd                   │
│ confidence                  │    │ used_usd                    │
│ issues (jsonb)              │    │ period_start, period_end    │
│ action_taken                │    └─────────────────────────────┘
└─────────────────────────────┘

┌─────────────────────────────┐
│      workflow_states        │   ← cho batch mode
├─────────────────────────────┤
│ workflow_id (PK)            │
│ runtime_id                  │
│ current_state               │
│ checkpoint_data (jsonb)     │
│ updated_at                  │
│ retry_count                 │
└─────────────────────────────┘

(Domain-specific tables như tasks, portfolios, code_graph nodes
 ở trong product layer, không trong framework)
```

### 13. Trade-off Analysis

| # | Decision | Chosen | Trade-off | Alternative & khi nào dùng |
|---|---|---|---|---|
| 1 | Plugin-based vs hardcoded core | Plugin | Complexity cao hơn, khó debug đầu | Hardcoded nếu chỉ 1-2 domain ổn định |
| 2 | Knowledge Backbone abstraction | Có | Thêm interface layer | Bỏ nếu tất cả product đều memory-centric |
| 3 | Cognitive strategy là plugin | Có | Cần document strategy contract | Hardcoded ReAct nếu use case hẹp |
| 4 | Verifier first-class | Có | Buộc product nghĩ về verification | Skip nếu trust level đều LOW |
| 5 | Workflow engine + Request handler song song | Có | 2 abstractions thay vì 1 | Single nếu chỉ một mode |
| 6 | Template method cho instrumentation | Có | Subclass có ít control hơn | Decorator pattern nếu cần linh hoạt hơn |
| 7 | Multi-provider router | Có | Routing matrix cần maintain | Single provider nếu vendor lock-in chấp nhận được |

### 14. Failure Modes & Mitigation

| Failure | Mitigation |
|---|---|
| **Plugin API breaking change** | Semver strict, deprecation cycle ≥ 6 tháng, automated test cho contract |
| **Strategy explosion** (quá nhiều strategy không ai biết dùng cái nào) | Strategy selector có default sane, mỗi strategy có "when to use" doc |
| **Verifier loop** (verifier reject mãi → regenerate vô hạn) | Hard limit retry, escalate human nếu N lần fail |
| **Knowledge backbone migration** | Versioned schema, migration tool, dual-write window |
| **Cost runaway từ cognitive strategy đắt** | Strategy selector check budget trước khi chọn, có default cheap strategy |
| **Cross-cutting bypass** (agent dev quên gọi instrumentation) | Template method pattern + lint rule cấm override `execute()` |
| **Provider all down** | Degraded mode: deterministic fallback (no LLM) — vd code analysis vẫn trả lời được từ graph traversal thuần |

### 15. Migration Path từ existing systems

Đây là phần thực dụng — không ai rebuild from scratch:

**Step 1: Adopt cross-cutting trước**. Cost tracker, audit logger, tracer là drop-in. Lợi ích lớn, rủi ro thấp.

**Step 2: Wrap existing agents trong BaseAgent**. Giữ logic cũ, thêm instrumentation. Backward compatible.

**Step 3: Migrate intent layer**. Replace ad-hoc classifier bằng IntentAnalyzer + StructuredIntent.

**Step 4: Plug-in cognitive strategies**. Bắt đầu với Direct + ReAct (đã có). Thêm verifier khi cần upgrade trust.

**Step 5: Knowledge backbone migration**. Phức tạp nhất. Dual-write trong N tuần, validate consistency, cutover.

Migration không phải all-or-nothing. Mỗi step độc lập có giá trị.

### 16. Anti-pattern alarm — gắn vào doc để team không mắc

- **"Để vào framework cho dùng chung"**: nếu chỉ có 1 product dùng → để ở product. Quy tắc rule of three: chờ 3 product cùng cần mới abstract.
- **"Framework should know about my domain"**: framework không nên có if-else theo domain. Domain logic ở config + plugin.
- **"Tôi cần tính năng X, framework chưa có, sửa core"**: đúng cách là viết plugin. Sửa core khi và chỉ khi bug, hoặc khi pattern đã ổn định 6+ tháng.
- **"Skip verifier cho nhanh"**: trust level LOW vẫn nên có SchemaVerifier ít nhất. Verifier không tốn nhiều, mất uy tín thì tốn nhiều.

---

## Phần III — Tóm tắt sự khác biệt với MAAF gốc

RYUU không phải MAAF v2 — là *sibling* với scope rộng hơn:

| Aspect | MAAF Per-Domain | RYUU |
|---|---|---|
| Scope | Conversational, agentic | Conversational + batch, agentic + deterministic |
| Domain pinning | Pin cứng lúc khởi tạo | Mode-dependent: pin (single) hoặc registry (multi) |
| Knowledge | Memory hierarchy hardcoded | Backbone pluggable (memory/graph/hybrid) |
| Cognitive | ReAct mainly | Strategy plugins (Direct/ReAct/BestN/ToT/EvalOpt/...) |
| Verification | Có nhưng chưa first-class | First-class concept với pipeline |
| Operation | Request-response | Request-response + Workflow batch |

Nếu bạn đang ở MAAF, RYUU là natural evolution khi:
- Cần thêm batch processing pipeline (như code ingestion).
- Cần backbone không phải memory (như graph).
- Cần multiple cognitive strategies cho cùng một product.
- Cần verification rigor hơn.

Nếu không cần những thứ trên, MAAF đủ — đừng over-engineer.

---

## Kết: ba nguyên tắc rút ra

**1. Abstract chỗ thực sự lặp lại, không chỗ "có thể" lặp lại.**
Bảy pattern ở Phần I là *bằng chứng* lặp lại, không phải dự đoán. Đây là lý do framework này có cơ sở.

**2. Khác biệt cũng quan trọng như giống nhau.**
Knowledge backbone, operation mode, trust level — ép giống là sai. Framework phải linh hoạt ở các trục này.

**3. Cross-cutting phải built-in, không opt-in.**
Cost, audit, trace — agent developer không được phép quên. Đây là điều phân biệt enterprise framework với hobby project.

Framework tốt không phải framework abstract nhiều nhất. Là framework abstract đúng — và document rõ những chỗ không abstract, để team biết khi nào nên ra khỏi framework thay vì cố nhét vào.
