"""Command-line interface for boxy-agent SDK and runtime."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from boxy_agent.capabilities import CapabilityCatalog, load_capability_catalog
from boxy_agent.compiler import compile_agent, package_agent
from boxy_agent.runtime import AgentRuntime
from boxy_agent.runtime.discovery import discover_registered_agents
from boxy_agent.scaffold import create_agent_project
from boxy_agent.types import JsonValue


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        capability_catalog: CapabilityCatalog | None = None
        if hasattr(args, "capability_catalog"):
            capability_catalog = _load_capability_catalog_arg(args.capability_catalog)

        if args.command == "compile":
            if capability_catalog is None:
                raise ValueError("capability_catalog is required")
            compiled = compile_agent(
                project_dir=Path(args.project_dir),
                output_dir=Path(args.output_dir),
                capability_catalog=capability_catalog,
            )
            print(compiled.manifest_path)
            return 0

        if args.command == "package":
            if capability_catalog is None:
                raise ValueError("capability_catalog is required")
            packaged = package_agent(
                project_dir=Path(args.project_dir),
                output_dir=Path(args.output_dir),
                capability_catalog=capability_catalog,
            )
            print(packaged.wheel_path)
            return 0

        if args.command == "list-agents":
            if capability_catalog is None:
                raise ValueError("capability_catalog is required")
            runtime, close_runtime_resources = _runtime_from_args(
                args, capability_catalog=capability_catalog
            )
            try:
                agents = runtime.list_installed_agents()
            finally:
                close_runtime_resources()
            if args.json:
                agent_payload: list[dict[str, object]] = []
                for agent in agents:
                    agent_payload.append(
                        {
                            "name": agent.name,
                            "description": agent.description,
                            "version": agent.version,
                            "type": agent.agent_type,
                            "expected_event_types": list(agent.expected_event_types),
                            "capabilities": {
                                "data_queries": sorted(agent.capabilities.data_queries),
                                "boxy_tools": sorted(agent.capabilities.boxy_tools),
                                "builtin_tools": sorted(agent.capabilities.builtin_tools),
                                "event_emitters": sorted(agent.capabilities.event_emitters),
                            },
                        }
                    )
                print(json.dumps(agent_payload, indent=2, sort_keys=True))
            else:
                for agent in agents:
                    print(f"{agent.name}\t{agent.version}\t{agent.agent_type}\t{agent.description}")
            return 0

        if args.command == "run":
            if capability_catalog is None:
                raise ValueError("capability_catalog is required")
            runtime, close_runtime_resources = _runtime_from_args(
                args, capability_catalog=capability_catalog
            )
            try:
                event = _load_event_from_args(args)
                report = runtime.run(agent_name=args.agent, event=event)
            finally:
                close_runtime_resources()
            payload: dict[str, JsonValue] = {
                "session_id": report.session_id,
                "status": report.status,
                "last_output": report.last_output,
                "traces": [
                    {
                        "session_id": trace.session_id,
                        "agent_name": trace.agent_name,
                        "event_type": trace.event_type,
                        "expected_event_types": list(trace.expected_event_types),
                        "matched_expected_event_type": trace.matched_expected_event_type,
                        "trace_name": trace.trace_name,
                        "payload": trace.payload,
                    }
                    for trace in report.traces
                ],
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0

        if args.command == "create-agent":
            created = create_agent_project(
                project_dir=Path(args.project_dir),
                requested_type=args.agent_type,
                name=args.name,
                description=args.description,
            )
            print(created.project_dir)
            return 0

    except Exception as exc:  # noqa: BLE001
        parser.exit(status=1, message=f"error: {exc}\n")

    parser.error("Unknown command")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="boxy-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    compile_parser = subparsers.add_parser("compile", help="Compile agent metadata and entrypoint")
    compile_parser.add_argument("--project-dir", required=True)
    compile_parser.add_argument("--output-dir", required=True)
    compile_parser.add_argument("--capability-catalog", required=True)

    package_parser = subparsers.add_parser("package", help="Build an installable wheel")
    package_parser.add_argument("--project-dir", required=True)
    package_parser.add_argument("--output-dir", required=True)
    package_parser.add_argument("--capability-catalog", required=True)

    list_agents_parser = subparsers.add_parser("list-agents", help="List installed agents")
    list_agents_parser.add_argument("--json", action="store_true")
    list_agents_parser.add_argument("--registry-file")
    list_agents_parser.add_argument("--capability-catalog", required=True)

    run_parser = subparsers.add_parser("run", help="Run an installed agent")
    run_parser.add_argument("--agent", required=True)
    run_parser.add_argument("--registry-file")
    run_parser.add_argument("--capability-catalog", required=True)
    event_group = run_parser.add_mutually_exclusive_group(required=True)
    event_group.add_argument("--event-json")
    event_group.add_argument("--event-file")

    create_parser = subparsers.add_parser("create-agent", help="Create a new agent project")
    create_parser.add_argument("agent_type", help="Agent type: operation or data-mining")
    create_parser.add_argument("--project-dir", required=True)
    create_parser.add_argument("--name")
    create_parser.add_argument("--description")

    return parser


def _load_event_from_args(args: argparse.Namespace) -> dict[str, object]:
    if args.event_json is not None:
        raw = json.loads(args.event_json)
    else:
        event_path = Path(args.event_file)
        raw = json.loads(event_path.read_text(encoding="utf-8"))

    if not isinstance(raw, dict):
        raise ValueError("Event input must decode to a JSON object")

    event_type = raw.get("type")
    if not isinstance(event_type, str) or not event_type.strip():
        raise ValueError("Event JSON object requires non-empty 'type' field")

    description = raw.get("description", "")
    if not isinstance(description, str):
        raise ValueError("Event field 'description' must be a string")

    payload = raw.get("payload", {})
    if not isinstance(payload, dict):
        raise ValueError("Event field 'payload' must be an object")

    return {
        "type": event_type.strip(),
        "description": description,
        "payload": payload,
    }


def _load_capability_catalog_arg(path: str) -> CapabilityCatalog:
    return load_capability_catalog(Path(path))


def _runtime_from_args(
    args: argparse.Namespace,
    *,
    capability_catalog: CapabilityCatalog,
) -> tuple[AgentRuntime, Callable[[], None]]:
    close_runtime_resources = _noop_close

    if args.registry_file is None:
        runtime = AgentRuntime(capability_catalog=capability_catalog)
        return runtime, close_runtime_resources

    records = _load_registry_records(Path(args.registry_file))
    runtime = AgentRuntime(
        capability_catalog=capability_catalog,
        agent_registry_loader=lambda: discover_registered_agents(records),
    )
    return runtime, close_runtime_resources


def _noop_close() -> None:
    pass


def _load_registry_records(path: Path) -> list[Mapping[str, object]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Registry file must decode to a JSON array")

    records: list[Mapping[str, object]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Registry records must be JSON objects")
        records.append(item)
    return records


if __name__ == "__main__":
    raise SystemExit(main())
