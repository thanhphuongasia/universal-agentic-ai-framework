# ryuu-intent

Intent + difficulty classification primitives for the Ryuu framework.

## What's inside

- **`Difficulty`** — `Literal["trivial", "medium", "hard"]` type
- **`normalize_difficulty(raw)`** — map LLM output token to canonical Difficulty (fallback `"medium"`)
- **`DEFAULT_PROMPT`** — back-compat constant; canonical source lives in `prompts/difficulty/v1.yaml`

## Prompt override

Default prompt lives at `prompts/difficulty/v1.yaml` inside this package. To override without redeploying code:

```bash
mkdir -p ~/.ryuu/prompts/difficulty
cp <pkg_path>/prompts/difficulty/v1.yaml ~/.ryuu/prompts/difficulty/v1.yaml
# edit ~/.ryuu/prompts/difficulty/v1.yaml — next process pickup
```

Use with the framework registry:

```python
from ryuu_prompts import make_framework_registry
registry = make_framework_registry(
    user_overrides_root=Path("~/.ryuu/prompts").expanduser(),
)
cfg = registry.load("difficulty", "v1")
```

## Future scope

`ryuu-runtime.LLMIntentAnalyzer` (intent classification, complexity tier) may move here in a later phase to consolidate "intent + difficulty" as one cohesive layer.
