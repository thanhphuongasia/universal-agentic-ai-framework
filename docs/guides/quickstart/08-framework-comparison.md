# So Sánh Với Framework Khác

← [Quickstart Index](README.md) | [All guides](../)

> RYUU Factory + Class vs Pydantic AI / OpenAI Agents SDK / Claude Agent SDK / CrewAI / LangChain / AutoGen.

---

## 7. So sánh với các framework khác

| Framework | API style | Observability | Tool loop | RYUU equivalent |
|---|---|---|---|---|
| **Pydantic AI** | `Agent('openai:gpt-4o', system_prompt=..., tools=[...])` | Logfire (paid) | Auto | Factory |
| **OpenAI Agents SDK** | `Agent(name, instructions, model, tools=[...])` | Traces (paid) | Auto via Runner | Factory |
| **Claude Agent SDK** | `client.messages.create(model, tools=[...])` | None | Manual | Raw OpenAI/Anthropic SDK |
| **CrewAI** | `Agent(role, goal, backstory, tools=[...])` | Custom | Auto | Class (multi-agent) |
| **LangChain** | `Chain(llm, tools, memory).invoke(...)` | LangSmith | Auto, brittle | Class (heavy abstractions) |
| **AutoGen** | `AssistantAgent(name, llm_config, tools=[...])` | None | Auto | Class (multi-agent) |
| **RYUU Factory** (proposed) | `Agent(model, tools=[...], budget_usd=1.0)` | Built-in (OTel + audit) | Auto | — |
| **RYUU Class** | `BaseAgent` subclass | Built-in | Custom (you control) | — |

**Điểm khác biệt RYUU:**
- Observability **built-in & free** (không bị lock vào paid platform)
- Audit hash chain (compliance use cases)
- Có cả 2 modes: factory cho 90%, class cho 10% advanced

---

## 8. Migration Path

```
Day 1:  Agent() factory                  ← prototype
Day 7:  Agent() + budget_usd + audit     ← production hardening
Day 30: BaseAgent subclass (nếu cần)     ← chuyển khi logic phức tạp
```

Factory và class chia sẻ same underlying primitives (BaseAgent, providers, observability). Chuyển từ factory sang class không phải rewrite — chỉ cần inline cái factory.build() làm.

---

