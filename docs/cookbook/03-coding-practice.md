# Cookbook: AI Coding Practice

> **Validates**: `SandboxManager` + tool registration pattern
> **Complexity**: Advanced — chạy code user trong sandbox isolation.

---

## Use Case

Platform luyện code: user submit solution, hệ thống chạy trong sandbox và evaluate kết quả.

Flow:
1. User nhận đề bài (challenge)
2. User submit code (Python)
3. System chạy code trong sandbox với test cases
4. Agent evaluate output và cho feedback
5. Agent gợi ý improvement nếu cần (`EvaluatorOptimizerStrategy`)

---

## Architecture

```
User submits code
  └─→ CodingAgent._execute()
        ├─→ SandboxManager.run()         # chạy code trong subprocess isolation
        ├─→ SchemaVerifier.verify()       # validate output format
        ├─→ GroundTruthVerifier.verify()  # so sánh với expected output
        └─→ ILLMProvider.complete()       # generate feedback
```

---

## SandboxManager Setup

```python
from uaaf.execution.sandbox import SandboxManager

sandbox = SandboxManager(
    timeout_seconds=10,      # kill nếu code chạy quá 10s
    max_memory_mb=128,       # memory limit
    allowed_modules=["math", "json", "collections", "itertools"],
)
```

`SandboxManager` dùng subprocess với `resource.setrlimit` (Linux/macOS) để enforce limits. Code user không thể import modules ngoài `allowed_modules`, không thể write file, không thể network access.

---

## Run Code Pattern

```python
from uaaf.execution.sandbox import SandboxManager

async def run_user_code(code: str, test_input: str) -> str:
    sandbox = SandboxManager(timeout_seconds=10, max_memory_mb=128)
    result = await sandbox.run(
        code=code,
        stdin=test_input,
    )
    return result.stdout if result.exit_code == 0 else f"Error: {result.stderr}"
```

---

## CodingAgent

```python
from dataclasses import dataclass, field

from uaaf._testing.fakes import FakeLLMProvider
from uaaf.cognitive.verifiers.ground_truth import GroundTruthVerifier
from uaaf.cognitive.verifiers.schema import SchemaVerifier
from uaaf.execution.agent import AgentResult, BaseAgent, Task
from uaaf.execution.sandbox import SandboxManager
from uaaf.observability.audit import AuditLogger
from uaaf.observability.cost import Cost, CostPolicy, CostTracker
from uaaf.observability.rate_limit import RateLimiter, RatePolicy
from uaaf.observability.tracer import Tracer
from uaaf.providers.llm import CompletionRequest, Message
from uaaf_workflow.context import ExecutionContext


@dataclass
class CodingAgent(BaseAgent):
    llm: FakeLLMProvider = field(default_factory=FakeLLMProvider)
    sandbox: SandboxManager = field(default_factory=SandboxManager)

    async def _execute(self, task: Task, context: ExecutionContext) -> AgentResult:
        code = str(task.payload.get("code", ""))
        test_input = str(task.payload.get("input", ""))
        expected_output = str(task.payload.get("expected", ""))

        # 1. Chạy code trong sandbox
        result = await self.sandbox.run(code=code, stdin=test_input)
        actual_output = result.stdout if result.exit_code == 0 else ""
        run_error = result.stderr if result.exit_code != 0 else ""

        # 2. So sánh với expected
        verifier = GroundTruthVerifier(mode="exact")
        verification = await verifier.verify(
            output=actual_output.strip(),
            context=context,
            metadata={"reference": expected_output.strip()},
        )

        # 3. Generate feedback qua LLM
        status = "PASS" if verification.passed else "FAIL"
        code_section = f"Code:\n{code}"
        prompt = (
            f"Code submission result: {status}\n"
            f"{code_section}\n"
            f"Expected: {expected_output}\n"
            f"Got: {actual_output or run_error}\n"
            "Give concise, constructive feedback in 2-3 sentences."
        )
        req = CompletionRequest(
            messages=[Message(role="user", content=prompt)],
            model="gpt-4o-mini",
        )
        feedback_response = await self.llm.complete(req)

        output = f"[{status}]\n{feedback_response.content}"
        return AgentResult(
            task_id=task.task_id,
            output=output,
            cost=Cost(input_tokens=80, output_tokens=30, usd=0.0, provider="fake", model="fake"),
        )
```

---

## Security Considerations

### Không bao giờ chạy code user ngoài sandbox

```python
# NEVER — nguy hiểm
exec(user_code)
eval(user_expression)

# ALWAYS — qua SandboxManager
async def run_safely(sandbox: SandboxManager, user_code: str) -> str:
    result = await sandbox.run(code=user_code)
    return result.stdout
```

### Whitelist modules

```python
from uaaf.execution.sandbox import SandboxManager

# Chỉ cho phép safe standard library
safe_sandbox = SandboxManager(
    allowed_modules=["math", "json", "collections", "itertools", "functools", "string"],
)

# KHÔNG cho phép
# - os, sys, subprocess → filesystem/process access
# - socket, urllib, requests → network access
# - importlib, builtins → escape sandbox
```

### Timeout là bắt buộc

Không set timeout → user có thể chạy infinite loop:

```python
# Minimum recommended
sandbox = SandboxManager(timeout_seconds=5, max_memory_mb=64)
```

---

## EvaluatorOptimizer Pattern (Optional)

Nếu muốn agent tự suggest fixes khi code fail:

```python
from uaaf.cognitive.strategies.evaluator_optimizer import EvaluatorOptimizerStrategy
from uaaf.cognitive.verifiers.ground_truth import GroundTruthVerifier
from uaaf._testing.fakes import FakeLLMProvider, FakeAgentPool, FakeVerifier

strategy = EvaluatorOptimizerStrategy(
    agent_pool=FakeAgentPool(),
    verifier=FakeVerifier(pass_sequence=[False, False, True]),
    max_rounds=3,
)
```

Strategy sẽ generate code → verify → nếu fail → refine → verify lại, tối đa 3 lần.

---

## Production Checklist

- [ ] Dùng Docker container thay subprocess cho sandbox isolation mạnh hơn
- [ ] Set hard timeout ở infrastructure level (process group kill)
- [ ] Log tất cả code submissions vào `AuditLogger` (có thể dùng cho plagiarism detection)
- [ ] Rate limit submissions: `RatePolicy(requests_per_minute=5)` per user
- [ ] Separate worker pool cho sandbox execution — không chạy trên main process
- [ ] Monitor memory/CPU usage của sandbox processes
