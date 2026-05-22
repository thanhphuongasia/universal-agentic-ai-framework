# ryuu-providers-core

LLM provider Protocols, value types, and middleware. **No SDK dependencies** — install a concrete adapter package for actual API calls.

## What's inside

- `ILLMProvider` — the Protocol every adapter satisfies
- `CompletionRequest`, `Message`, `Response`, `StreamChunk`, `TokenUsage`, `Embedding` — value types
- `calculate_usd`, `PRICING`, `CONTEXT_WINDOW` — token-to-USD pricing tables (loaded from `pricing.yaml`)
- `ModelRouter` — dispatch by `ModelTier` (CHEAP/STANDARD/POWERFUL)
- `CircuitBreaker` — per-provider failure circuit
- `ProviderFallbackChain` — try providers in order

## Concrete adapters

| Adapter | External dep |
|---------|--------------|
| `ryuu-providers-openai` | `openai>=1.0` |
| `ryuu-providers-anthropic` | `anthropic>=0.30` |

Install only what you need:

```bash
pip install ryuu-providers-openai      # → installs openai SDK + this core
pip install ryuu-providers-anthropic   # → installs anthropic SDK + this core
pip install ryuu-providers             # → metapackage: pulls core only; use [openai] / [anthropic] / [all] extras
```
