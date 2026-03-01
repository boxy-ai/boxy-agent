# boxy-agent

`boxy-agent` is the SDK, compiler, and runtime for Boxy agents.

It supports two public agent types:
- `automation`
- `data_mining`

## Architecture

Source lives in `src/boxy_agent/` and is split into four layers:

- `sdk/`: namespaced helper APIs agent authors call (`llm`, `data_queries`, `boxy_tools`, `memory`, `events`, `tracing`, `control`) plus execution context and `@agent_main` contracts.
- `compiler/`: reads `pyproject.toml`, validates metadata/capabilities, resolves entrypoint, emits compiled manifest, packages wheel.
- `runtime/`: discovers installed agents, enforces capabilities/schemas at call time, runs one invocation per trigger event, records traces, and manages event queue/memory through providers.

Shared models and capability catalogs are in:
- `models.py`
- `types.py`
- `capabilities.py`

## Compile + Package Flow

1. Agent metadata is loaded from `pyproject.toml` (`tool.boxy_agent.*`).
2. Declared capabilities are validated against the active capability catalog.
3. Entrypoint is located statically by scanning for exactly one `@agent_main` function.
4. A compiled manifest (`*.compiled.json`) is emitted.
5. Packaging injects that manifest into the wheel as `boxy_agent_compiled_manifest.py`.

## Runtime Flow

1. Runtime loads discovered installed agents from registry records.
2. It builds an execution context with runtime-bound SDK bindings.
3. Capability calls are checked twice at runtime (allowlist enforcement and JSON Schema input/output validation).
4. The agent handler returns `AgentResult` (or JSON-compatible output).
5. Runtime applies memory updates, emits traces/events, and returns a `RunReport`.

## Design Choices

- Compile-time + runtime validation:
  compile catches bad declarations early; runtime still validates live inputs/outputs.
- Strict JSON boundaries:
  all event payloads, memory values, trace payloads, and tool/data IO are JSON-compatible.
- Provider abstraction:
  runtime depends on `AgentSdkProvider` so integrations can inject either core-backed providers (`CoreAgentSdkProvider`) or custom test providers.
- Static compilation:
  compiler uses AST analysis instead of importing agent modules, avoiding import-time side effects.
- Explicit event orchestration:
  runtime invocation is single-step per event.

## CLI

Main commands:
- `boxy-agent compile --project-dir <dir> --output-dir <dir> --capability-catalog <catalog.toml>`
- `boxy-agent package --project-dir <dir> --output-dir <dir> --capability-catalog <catalog.toml>`
- `boxy-agent list-agents --registry-file <file> --capability-catalog <catalog.toml>`
- `boxy-agent run --agent <name> --registry-file <file> --capability-catalog <catalog.toml> --event-json '<json>'`
- `boxy-agent create-agent <operation|data-mining> --project-dir <dir>`

`boxy-agent package` requires packaging dependencies. Install with the `packaging` extra.
