# Contributing to RYUU

## Development setup

```bash
git clone <repo>
cd ryuu-framework
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Running checks

```bash
pytest                              # all tests
pytest tests/unit                   # unit only
pytest --cov=ryuu --cov-report=html # coverage
ruff check ryuu/ tests/
mypy ryuu/
```

## Code rules

- All agent classes must extend `BaseAgent` — never bypass cross-cutting.
- All LLM calls go through `ILLMProvider` — never call SDK directly in domain code.
- All errors must be typed (`RetryableError` / `DegradedError` / `FatalError`). No `except Exception: pass`.
- Use `anyio` primitives — never `asyncio` directly in `ryuu/` code.
- Add a contract test when adding a new Protocol implementation.
- Update `CHANGELOG.md` on any public API change.

## Commit style

`type(scope): description` — e.g. `feat(agent): add retry budget to BaseAgent`.
