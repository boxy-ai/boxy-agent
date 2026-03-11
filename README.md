# boxy-agent

`boxy-agent` is the standalone SDK + CLI for Boxy agents. The source of truth remains this monorepo; `boxy-agent/` is mirrored to a read-only public GitHub repo for external consumption and PyPI releases.

The public alpha contract is agent authoring:
- SDK helpers under `boxy_agent.sdk`
- author-facing models and `@agent_main`
- packaged capability catalog
- compile/package helpers and packaging CLI

Lower-level runtime/provider/discovery modules remain available, but they are experimental host-integration surfaces rather than the primary author-facing contract.

## Public Surfaces

Supported public agent types:
- `automation`
- `data_mining`

Public-but-unconfigured-by-default surfaces:
- `boxy_agent.sdk.llm.chat_complete`
- built-in `web_search`

Those interfaces stay public because real Boxy environments provide them. In a standalone SDK runtime they fail explicitly until a host/runtime provider is configured.

## Packaged Capability Catalog

The CLI and public compile/package APIs always load the packaged capability catalog from `src/boxy_agent/capability_catalog.toml`.

That file is generated from monorepo code, not edited by hand:
- built-in capability definitions come from `src/boxy_agent/builtin_capability.toml`
- connector data queries and Boxy tools come from the shipping `boxy-desktop` connector set
- current shipping connector profile: `local_files`, `whatsapp`, `wechat`

Regenerate the tracked artifacts with:

```bash
mise run agent:catalog-sync
```

This keeps:
- `boxy-desktop/connector_capability.toml`
- `boxy-agent/src/boxy_agent/capability_catalog.toml`

in sync from one generator path.

## Examples

Reference example projects live in the repo, not inside the installed package:
- `examples/automation`
- `examples/data_mining`

They declare an explicit `boxy-agent` dependency and are intended to stay representative of the published authoring flow.

## CLI

Main commands:
- `boxy-agent create-agent <automation|data-mining> --project-dir <dir>`
- `boxy-agent package --project-dir <dir> --output-dir <dir>`
- `boxy-agent list-agents --registry-file <file>`
- `boxy-agent run --agent <name> --registry-file <file> --event-json '<json>'`

`boxy-agent package` performs validation and packaging in one step. It requires packaging dependencies in the invoking environment.

## Local Validation

Use the same tasks locally that CI and release flows use:

```bash
mise run agent:catalog-sync
mise run agent:build
mise run agent:package-check
mise run agent:release-check
```

`agent:package-check` builds a clean virtual environment, installs the built wheel, verifies the packaged catalog, packages and runs standalone agents, and checks that unconfigured `llm.chat_complete` and `web_search` fail with explicit errors.

## Roadmap

TODO: add an optional BYOK provider for local SDK testing backed by OpenRouter for LLM chat completions and Brave for `web_search`.

TODO: add a mock connector provider with mock data queries and tool implementations so agent authors can simulate full end-to-end flows without a live Boxy Desktop runtime.
