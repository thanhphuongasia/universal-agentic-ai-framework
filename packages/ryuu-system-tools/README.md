# ryuu-system-tools

Pluggable system / host ITools for any Ryuu agent.

## What's bundled

| Tool | Description |
|------|-------------|
| `get_current_datetime` | Authoritative date/time anchor (accepts IANA timezone) |

LLMs hallucinate dates badly — agents should call this whenever they need a real-world time reference.

## Usage

```python
from ryuu_system_tools import SystemToolset

toolset = SystemToolset.from_layered()
agent = Agent(model="gpt-4o", tools=[*toolset.tools, ...])
```

## Four ways to add a tool (none require touching this package)

### A) Declarative YAML — no code at all (recommended for HTTP / shell tools)

Drop `~/.ryuu/system_tools/<name>.yml`:

```yaml
name: get_weather
description: Returns current weather for a city
parameters:
  city:
    type: string
    description: City name
    required: true
exec:
  type: http
  url: https://api.weatherapi.com/v1/current.json?key=${WEATHER_KEY}&q={{city}}
  method: GET
```

`{{var}}` = tool-call argument. `${ENV}` = process env. Restart bot → tool live.

`exec.type` options:
- **`http`** — REST call. Returns `{ok, status, data|text}`. Supports `headers`, `query`, `body`, `timeout`.
- **`shell`** — runs `command` (string → sh -c, or argv list). Returns `{ok, exit_code, stdout, stderr}`.
- **`static`** — returns constant `value` (templated). Useful for stubs / fixtures.

### B) Pip-installable plugin via entry-points (best for sharable tools)

Create a separate package, say `ryuu-system-tools-weather`:

```toml
# pyproject.toml of your plugin package
[project]
name = "ryuu-system-tools-weather"

[project.entry-points."ryuu_system_tools.plugins"]
weather = "weather_plugin:register"
```

```python
# weather_plugin.py
def register():
    return [GetWeatherTool()]
```

`pip install ryuu-system-tools-weather` on any machine — `SystemToolset.from_layered()` auto-picks it up. No code edits to `ryuu-system-tools` or to the host app. This is how `pytest`, `mkdocs`, etc. extend themselves.

### B) Drop-file (best for one-off / per-machine tools)

Drop a Python file into `~/.ryuu/system_tools/<name>.py`:

```python
TOOLS = [MyTool()]
```

…or a `def register() -> list[ITool]:`. Restart bot — auto-registered.

### C) Per-project tools

Pass `extra_dirs=[...]` to `from_layered`:

```python
toolset = SystemToolset.from_layered(extra_dirs=["./my_app/tools"])
```

## Lookup order (later wins on tool_id collision)

1. Bundled defaults shipped with this package
2. Entry-points (group: `ryuu_system_tools.plugins`)
3. `$RYUU_SYSTEM_TOOLS_DIR` env (colon-separated paths)
4. `~/.ryuu/system_tools/*.py`
5. Any `extra_dirs` argument

## Conventions

- Filename must not start with `_` (private files are skipped)
- Each tool must implement the ITool protocol: `tool_id`, `schema` property, async `execute(args)` method
- Module exposes either `TOOLS: list[ITool]` or `def register() -> list[ITool]`
- Errors during import of one module never crash the toolset — broken plugins are logged and skipped
