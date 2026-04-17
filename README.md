# boxy-agent

Build Boxy agents as ordinary Python packages.

`boxy-agent` gives you a clean authoring SDK, a packaging flow, and a local runtime contract for agents that wake on events, read context, call tools, emit follow-up events, and return structured results. The same contract powers Boxy's first-party agents.

## Why boxy-agent

- Start from plain Python instead of a custom DSL
- Define exactly what data, tools, and events your agent is allowed to use
- Package agents as installable wheels
- Run agents through a consistent event-driven contract
- Keep the authoring surface small enough to learn quickly, but strict enough to ship reliably

## Quickstart

Install the CLI with `uv`:

```bash
uv tool install "boxy-agent[packaging]"
boxy-agent --help
```

If you prefer not to install it globally, use `uvx`:

```bash
uvx --from "boxy-agent[packaging]" boxy-agent --help
```

Create your first agent:

```bash
boxy-agent create-agent automation --project-dir ./email-ops-agent
cd ./email-ops-agent
uv sync
```

Build a wheel:

```bash
uv run boxy-agent package --project-dir . --output-dir ./dist
```

Install the packaged wheel into the environment where you want to run it, then inspect and execute it:

```bash
uv pip install ./dist/*.whl
uv run boxy-agent list-agents --json
uv run boxy-agent run --agent email-ops-agent --event-json '{"type":"start"}'
```

You can also pass the event as a file:

```bash
uv run boxy-agent run --agent email-ops-agent --event-file ./event.json
```

Event input must decode to a JSON object with:

- `type`: required non-empty string
- `description`: optional string
- `payload`: optional object

`boxy-agent run` prints a JSON report with the run status, last output, and emitted traces.

## What You Build

A Boxy agent project is a normal Python package with Boxy metadata in `pyproject.toml`.

Minimal layout:

```text
my-agent/
  pyproject.toml
  src/
    my_agent/
      __init__.py
      agent.py
```

Minimal metadata:

```toml
[project]
name = "my-agent"
version = "0.1.0"
description = "My Boxy agent"
requires-python = ">=3.12"
dependencies = ["boxy-agent>=0.2.0a6,<0.3.0"]

[build-system]
requires = ["setuptools>=69.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
package-dir = { "" = "src" }

[tool.setuptools.packages.find]
where = ["src"]

[tool.boxy_agent.agent]
name = "my-agent"
description = "My Boxy agent"
version = "0.1.0"
type = "automation"
module = "my_agent.agent"
expected_event_types = ["start"]

[tool.boxy_agent.capabilities]
data_queries = []
boxy_tools = []
builtin_tools = []
event_emitters = []
```

Minimal agent:

```python
from boxy_agent import AgentExecutionContext, AgentResult, agent_main


@agent_main
def handle(exec_ctx: AgentExecutionContext) -> AgentResult:
    return AgentResult(
        output={
            "event_type": exec_ctx.event.type,
            "message": "hello from boxy-agent",
        }
    )
```

Entrypoint rules:

- your configured module must define exactly one function decorated with `@agent_main`
- the entrypoint must be synchronous
- it must accept exactly one positional execution-context argument
- that argument must not have a default

## Two Agent Styles

`boxy-agent` supports two agent types:

- `automation`: event-driven agents that react to triggers and can declare tool access
- `data_mining`: analysis-oriented agents that read data, generate insights, and emit events, and may declare only non-side-effecting `boxy_tools`

Type-specific rules:

- `automation` agents must declare non-empty `expected_event_types`
- `data_mining` agents must not declare `expected_event_types`
- `data_mining` agents must not declare side-effecting `boxy_tools`

The CLI scaffold uses `data-mining` as the command-line name and writes `data_mining` into project metadata.

## Capabilities

Every agent declares the capabilities it needs up front:

- `data_queries`: named read/query interfaces exposed by the host runtime
- `boxy_tools`: named host actions the agent may invoke
- `builtin_tools`: package-provided tools available in the runtime
- `event_emitters`: outbound event types the agent may emit

Declared capabilities are validated against the shipped capability catalog during compile and package time. That means an agent fails fast when it asks for a capability that the target runtime does not expose.

## SDK Features

The main authoring surface includes:

- `agent_main`
- `AgentExecutionContext`, `AgentEvent`, `AgentResult`, `AgentMetadata`, `AgentCapabilities`
- `compile_agent`, `package_agent`
- `query_data`, `list_data_queries`
- `call_boxy_tool`, `list_boxy_tools`
- `call_builtin_tool`, `list_builtin_tools`
- `emit_event`
- `memory_get`, `memory_set`, `memory_delete`
- `trace`
- `terminate`
- `llm_chat_complete`

Typical usage patterns:

- use `query_data` to pull context from Boxy-connected sources
- use `call_boxy_tool` for host runtime actions; data-mining agents may only declare read-only tools where `side_effect == false`
- use `call_builtin_tool` for package-provided tools
- use memory helpers for session or persistent state
- use `emit_event` to schedule downstream work
- use `trace` for structured diagnostics

Some SDK surfaces are public but intentionally unconfigured in the standalone runtime by default:

- `boxy_agent.sdk.llm.chat_complete`
- built-in `web_search`

They stay public because Boxy runtimes can provide them. In a standalone SDK runtime they fail explicitly until a host/runtime provider is configured.

## CLI

Main commands:

- `boxy-agent create-agent <automation|data-mining> --project-dir <dir>`
- `boxy-agent package --project-dir <dir> --output-dir <dir>`
- `boxy-agent list-agents [--json] [--registry-file <file>]`
- `boxy-agent run --agent <name> [--registry-file <file>] (--event-json '<json>' | --event-file <file>)`

Use `--registry-file` when you want runtime discovery to come from explicit packaged-agent registry records instead of only the current Python environment.

## Examples

Reference example projects live in this repository:

- `examples/automation`
- `examples/data_mining`

They are meant to stay representative of the published authoring flow.

## Develop From Source

If you cloned the `boxy-agent` source repository:

```bash
uv sync --all-extras --dev
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
```

Run the CLI directly from the checkout:

```bash
uv run boxy-agent --help
```

## Capability Catalog

The CLI and compile/package APIs load the packaged capability catalog from `src/boxy_agent/capability_catalog.json`.

Treat that catalog as the shipped contract for discoverable data queries, Boxy tools, and built-in tools. It is generated data and should not be edited by hand.
