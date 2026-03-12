"""Agent runtime implementation."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from jsonschema import Draft202012Validator, FormatChecker, validators
from jsonschema.exceptions import FormatError, ValidationError

from boxy_agent.capabilities import CapabilityCatalog
from boxy_agent.models import (
    AgentCapabilities,
    AgentEvent,
    AgentResult,
    DataQueryDescriptor,
    ToolDescriptor,
)
from boxy_agent.runtime.discovery import DiscoveredAgent
from boxy_agent.runtime.errors import (
    AgentExecutionError,
    AgentNotFoundError,
    AgentRuntimeError,
    CapabilitySchemaError,
    CapabilityViolationError,
    InvalidEventError,
)
from boxy_agent.runtime.models import (
    EventQueueItem,
    InstalledAgent,
    RunReport,
    RunStatus,
    TraceRecord,
)
from boxy_agent.runtime.providers import (
    AgentSdkProvider,
    BuiltinToolClient,
    InMemoryMemoryStore,
    StaticDataQueryClient,
    StaticToolClient,
    UnconfiguredLlmClient,
)
from boxy_agent.sdk.interfaces import (
    AgentExecutionContext,
    AgentMainFunction,
    DataQueryClient,
    LlmClient,
    MemoryStore,
    TerminateCallback,
    ToolClient,
    TraceCallback,
)
from boxy_agent.types import JsonValue, ensure_json_value

type AgentRegistryLoader = Callable[[], dict[str, DiscoveredAgent]]
# Draft 2020-12 treats `format` as annotation by default in this jsonschema version,
# so runtime schema checks must explicitly wire in asserting format behavior.
_FORMAT_CHECKER = FormatChecker()


@_FORMAT_CHECKER.checks("date-time")
def _is_date_time(value: object) -> bool:
    # Type constraints are enforced by JSON Schema `type`; format only validates string shape.
    if not isinstance(value, str):
        return True

    # Accept RFC3339-style `Z` by normalizing to an offset format `fromisoformat` parses.
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    # Require timezone-aware datetimes for compatibility with capability schema expectations.
    return parsed.tzinfo is not None


def _asserting_format_validator(
    validator: Draft202012Validator,
    expected_format: object,
    instance: object,
    _schema: object,
):
    # Custom keyword handlers in jsonschema are generators that yield ValidationError values.
    if not isinstance(expected_format, str):
        return
    if validator.format_checker is None:
        return
    try:
        validator.format_checker.check(instance, expected_format)
    except FormatError as exc:
        yield ValidationError(exc.message)


# Override the `format` keyword so runtime validation fails invalid format values
# instead of silently treating them as annotation-only metadata.
_ASSERTIVE_DRAFT_202012_VALIDATOR = validators.extend(
    Draft202012Validator,
    validators={"format": _asserting_format_validator},
)


def _empty_agent_registry_loader() -> dict[str, DiscoveredAgent]:
    return {}


class _RuntimeDefaultSdkProvider:
    """Neutral in-process provider used when runtime dependencies are not injected."""

    def __init__(self) -> None:
        self._session_memory_by_session_id: dict[str, dict[str, JsonValue]] = {}
        self._persistent_memory_by_agent: dict[str, dict[str, JsonValue]] = {}

    def create_session(self, *, agent_name: str, event: AgentEvent) -> str:
        _ = agent_name, event
        return uuid.uuid4().hex

    def close_session(self, session_id: str) -> None:
        _ = session_id

    def data_query_client(self, catalog: CapabilityCatalog) -> DataQueryClient:
        return StaticDataQueryClient(descriptors=list(catalog.data_queries.values()))

    def boxy_tool_client(self, catalog: CapabilityCatalog) -> ToolClient:
        return StaticToolClient(descriptors=list(catalog.boxy_tools.values()))

    def builtin_tool_client(self, catalog: CapabilityCatalog) -> ToolClient:
        return BuiltinToolClient(descriptors=list(catalog.builtin_tools.values()))

    def llm_client(self, *, agent_name: str, session_id: str) -> LlmClient:
        _ = agent_name, session_id
        return UnconfiguredLlmClient()

    def create_memory_store(self, *, agent_name: str, session_id: str) -> MemoryStore:
        session_memory = self._session_memory_by_session_id.setdefault(session_id, {})
        persistent_memory = self._persistent_memory_by_agent.setdefault(agent_name, {})
        return InMemoryMemoryStore(
            session_backing=session_memory,
            persistent_backing=persistent_memory,
        )

    def publish_event(self, event: EventQueueItem) -> None:
        _ = event

    def record_trace(
        self,
        *,
        agent_name: str,
        session_id: str,
        event: AgentEvent,
        trace_name: str,
        payload: dict[str, JsonValue],
    ) -> None:
        _ = agent_name, session_id, event, trace_name, payload


@dataclass
class _SessionState:
    session_id: str
    traces: list[TraceRecord]
    terminated_by_agent: bool = False
    terminated_by_controller: bool = False


@dataclass(kw_only=True)
class _ContextRuntimeBindings:
    agent_name: str
    session_id: str
    capabilities: AgentCapabilities
    capability_catalog: CapabilityCatalog
    data_client: DataQueryClient
    boxy_tool_client: ToolClient
    builtin_tool_client: ToolClient
    llm_client: LlmClient
    memory_store: MemoryStore
    trace_callback: TraceCallback
    terminate_callback: TerminateCallback
    emit_event_callback: Callable[[AgentEvent], None]

    def llm_chat_complete(self, request: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return self.llm_client.chat_complete(request)

    def list_data_queries(self) -> list[DataQueryDescriptor]:
        return _filter_descriptors(
            allowed=self.capabilities.data_queries,
            catalog=self.capability_catalog.data_queries,
        )

    def query_data(self, name: str, params: dict[str, JsonValue]) -> list[JsonValue]:
        self._ensure_capability(
            name=name, allowed=self.capabilities.data_queries, kind="data query"
        )
        descriptor = self._require_data_query_descriptor(name)
        result = self._call_checked_capability(
            name=name,
            params=params,
            kind="data query",
            descriptor=descriptor,
            call=self._call_data_query_with_session_scope,
        )
        return cast(list[JsonValue], result)

    def list_boxy_tools(self) -> list[ToolDescriptor]:
        return _filter_descriptors(
            allowed=self.capabilities.boxy_tools,
            catalog=self.capability_catalog.boxy_tools,
        )

    def call_boxy_tool(self, name: str, params: dict[str, JsonValue]) -> JsonValue:
        self._ensure_capability(
            name=name,
            allowed=self.capabilities.boxy_tools,
            kind="boxy tool",
        )
        descriptor = self._require_boxy_tool_descriptor(name)
        return self._call_checked_capability(
            name=name,
            params=params,
            kind="boxy tool",
            descriptor=descriptor,
            call=self._call_boxy_tool_with_actor_scope,
        )

    def list_builtin_tools(self) -> list[ToolDescriptor]:
        return _filter_descriptors(
            allowed=self.capabilities.builtin_tools,
            catalog=self.capability_catalog.builtin_tools,
        )

    def call_builtin_tool(self, name: str, params: dict[str, JsonValue]) -> JsonValue:
        self._ensure_capability(
            name=name,
            allowed=self.capabilities.builtin_tools,
            kind="built-in tool",
        )
        descriptor = self._require_builtin_tool_descriptor(name)
        return self._call_checked_capability(
            name=name,
            params=params,
            kind="built-in tool",
            descriptor=descriptor,
            call=self._call_builtin_tool_with_scope,
        )

    def memory_get(self, key: str, *, scope: str = "session") -> JsonValue | None:
        _validate_scope(scope)
        return self.memory_store.get(scope=scope, key=key)

    def memory_set(self, key: str, value: JsonValue, *, scope: str = "session") -> None:
        _validate_scope(scope)
        self.memory_store.set(scope=scope, key=key, value=value)

    def memory_delete(self, key: str, *, scope: str = "session") -> None:
        _validate_scope(scope)
        self.memory_store.delete(scope=scope, key=key)

    def trace(self, name: str, payload: dict[str, JsonValue] | None = None) -> None:
        if not name.strip():
            raise ValueError("Trace name must be non-empty")
        payload_data = payload or {}
        for key, value in payload_data.items():
            ensure_json_value(value, label=f"trace payload value for key {key}")
        self.trace_callback(name, payload_data)

    def terminate(self, reason: str | None = None) -> None:
        self.terminate_callback(reason)

    def emit_event(self, event: AgentEvent) -> None:
        self._ensure_capability(
            name=event.type,
            allowed=self.capabilities.event_emitters,
            kind="event emitter",
        )
        self.emit_event_callback(event)

    def _ensure_capability(self, *, name: str, allowed: frozenset[str], kind: str) -> None:
        if name in allowed:
            return
        raise CapabilityViolationError(
            f"Agent '{self.agent_name}' is not allowed to access {kind} '{name}'"
        )

    def _require_data_query_descriptor(self, name: str) -> DataQueryDescriptor:
        descriptor = self.capability_catalog.data_queries.get(name)
        if descriptor is None:
            raise CapabilitySchemaError(f"Missing data query descriptor for '{name}'")
        return descriptor

    def _require_boxy_tool_descriptor(self, name: str) -> ToolDescriptor:
        descriptor = self.capability_catalog.boxy_tools.get(name)
        if descriptor is None:
            raise CapabilitySchemaError(f"Missing boxy tool descriptor for '{name}'")
        return descriptor

    def _require_builtin_tool_descriptor(self, name: str) -> ToolDescriptor:
        descriptor = self.capability_catalog.builtin_tools.get(name)
        if descriptor is None:
            raise CapabilitySchemaError(f"Missing built-in tool descriptor for '{name}'")
        return descriptor

    def _call_checked_capability(
        self,
        *,
        name: str,
        params: dict[str, JsonValue],
        kind: str,
        descriptor: DataQueryDescriptor | ToolDescriptor,
        call: Callable[[str, dict[str, JsonValue]], JsonValue],
    ) -> JsonValue:
        try:
            ensure_json_value(params, label=f"{kind} params for '{name}'")
        except TypeError as exc:
            raise CapabilitySchemaError(str(exc)) from exc
        _validate_schema_instance(
            schema=descriptor.input_schema,
            instance=params,
            label=f"{kind} input '{name}'",
        )
        result = call(name, params)
        try:
            ensure_json_value(result, label=f"{kind} output for '{name}'")
        except TypeError as exc:
            raise CapabilitySchemaError(str(exc)) from exc
        _validate_schema_instance(
            schema=descriptor.output_schema,
            instance=result,
            label=f"{kind} output '{name}'",
        )
        return result

    def _call_boxy_tool_with_actor_scope(
        self,
        name: str,
        params: dict[str, JsonValue],
    ) -> JsonValue:
        return self.boxy_tool_client.call_tool(
            name,
            params,
            session_id=self.session_id,
            actor_principal=self._actor_principal(),
        )

    def _call_data_query_with_session_scope(
        self,
        name: str,
        params: dict[str, JsonValue],
    ) -> JsonValue:
        return self.data_client.query_data(
            name,
            params,
            session_id=self.session_id,
            actor_principal=self._actor_principal(),
        )

    def _call_builtin_tool_with_scope(
        self,
        name: str,
        params: dict[str, JsonValue],
    ) -> JsonValue:
        return self.builtin_tool_client.call_tool(
            name,
            params,
            session_id=self.session_id,
            actor_principal=self._actor_principal(),
        )

    def _actor_principal(self) -> str:
        return f"agent:{self.agent_name}:session:{self.session_id}"


class AgentRuntime:
    """Runtime for discovered installed Boxy agents."""

    def __init__(
        self,
        *,
        agent_registry_loader: AgentRegistryLoader | None = None,
        capability_catalog: CapabilityCatalog,
        sdk_provider: AgentSdkProvider | None = None,
    ) -> None:
        if capability_catalog is None:
            raise ValueError("capability_catalog is required")

        self._capability_catalog = capability_catalog
        self._agent_registry_loader = agent_registry_loader or _empty_agent_registry_loader
        self._sdk_provider = sdk_provider or _RuntimeDefaultSdkProvider()
        self._data_client = self._sdk_provider.data_query_client(self._capability_catalog)
        self._boxy_tool_client = self._sdk_provider.boxy_tool_client(self._capability_catalog)
        self._builtin_tool_client = self._sdk_provider.builtin_tool_client(self._capability_catalog)
        self._terminated_sessions: set[str] = set()
        self._event_queue: list[EventQueueItem] = []

    def list_installed_agents(self) -> list[InstalledAgent]:
        """Return discovered installed agents."""
        discovered = self._agent_registry_loader()
        return sorted(
            (entry.installed for entry in discovered.values()), key=lambda item: item.name
        )

    def terminate_session(self, session_id: str) -> None:
        """Request a running session to terminate after its current step."""
        self._terminated_sessions.add(session_id)

    def queue_event(self, event: AgentEvent | Mapping[str, object], *, source: str) -> None:
        """Queue an external event (for example from a connector)."""
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source must be non-empty")
        coerced_event = _coerce_event(event)
        queue_item = EventQueueItem(
            event=coerced_event,
            source=source.strip(),
        )
        self._event_queue.append(queue_item)
        self._sdk_provider.publish_event(queue_item)

    def drain_event_queue(self) -> list[EventQueueItem]:
        """Return and clear queued events."""
        queued = list(self._event_queue)
        self._event_queue.clear()
        return queued

    def run(self, agent_name: str, event: AgentEvent | Mapping[str, object]) -> RunReport:
        """Run an installed agent once for a single trigger event."""
        discovered = self._agent_registry_loader()
        target = discovered.get(agent_name)
        if target is None:
            raise AgentNotFoundError(f"Unknown agent: {agent_name}")

        initial_event = _coerce_event(event)
        session_id = self._sdk_provider.create_session(
            agent_name=target.installed.name,
            event=initial_event,
        )
        session_state = _SessionState(session_id=session_id, traces=[])
        try:
            return self._run_agent(
                target=target,
                initial_event=initial_event,
                session_state=session_state,
            )
        finally:
            self._sdk_provider.close_session(session_id)

    def _run_agent(
        self,
        *,
        target: DiscoveredAgent,
        initial_event: AgentEvent,
        session_state: _SessionState,
    ) -> RunReport:
        memory_store = self._sdk_provider.create_memory_store(
            agent_name=target.installed.name,
            session_id=session_state.session_id,
        )

        last_output: JsonValue | None = None

        if not (session_state.terminated_by_agent or session_state.terminated_by_controller):
            if session_state.session_id in self._terminated_sessions:
                session_state.terminated_by_controller = True
            else:
                event = initial_event
                # This is trace metadata for observability; mismatches are not a hard runtime error.
                matched_expected_event = (
                    event.type in target.installed.expected_event_types
                    if target.installed.expected_event_types
                    else None
                )

                session_state.traces.append(
                    TraceRecord(
                        session_id=session_state.session_id,
                        agent_name=target.installed.name,
                        event_type=event.type,
                        expected_event_types=target.installed.expected_event_types,
                        matched_expected_event_type=matched_expected_event,
                        trace_name="step.start",
                        payload={
                            "description": event.description,
                        },
                    )
                )

                exec_ctx = self._build_exec_ctx(
                    target=target,
                    event=event,
                    memory_store=memory_store,
                    session_state=session_state,
                )

                raw_result = self._invoke_handler(target.handler, exec_ctx)
                result = _coerce_result(raw_result)

                # AgentResult memory updates are applied after handler completion so the runtime
                # can keep memory mutation ordering deterministic around one invocation.
                for key, value in result.session_memory_updates.items():
                    memory_store.set(scope="session", key=key, value=value)
                for key, value in result.persistent_memory_updates.items():
                    memory_store.set(scope="persistent", key=key, value=value)

                last_output = result.output

        status = _derive_status(session_state=session_state)

        return RunReport(
            session_id=session_state.session_id,
            status=status,
            last_output=last_output,
            traces=list(session_state.traces),
        )

    def _build_exec_ctx(
        self,
        *,
        target: DiscoveredAgent,
        event: AgentEvent,
        memory_store: MemoryStore,
        session_state: _SessionState,
    ) -> AgentExecutionContext:
        def terminate_callback(_reason: str | None) -> None:
            # Reason is currently not persisted in RunReport status, but retained in API shape.
            session_state.terminated_by_agent = True

        def trace_callback(name: str, payload: dict[str, JsonValue]) -> None:
            session_state.traces.append(
                TraceRecord(
                    session_id=session_state.session_id,
                    agent_name=target.installed.name,
                    event_type=event.type,
                    expected_event_types=target.installed.expected_event_types,
                    matched_expected_event_type=(
                        event.type in target.installed.expected_event_types
                        if target.installed.expected_event_types
                        else None
                    ),
                    trace_name=name,
                    payload=payload,
                )
            )
            self._sdk_provider.record_trace(
                agent_name=target.installed.name,
                session_id=session_state.session_id,
                event=event,
                trace_name=name,
                payload=payload,
            )

        def emit_event_callback(agent_event: AgentEvent) -> None:
            queue_item = EventQueueItem(
                event=agent_event,
                source="agent",
                source_agent=target.installed.name,
                session_id=session_state.session_id,
            )
            self._event_queue.append(queue_item)
            self._sdk_provider.publish_event(queue_item)

        bindings_kwargs = {
            "agent_name": target.installed.name,
            "session_id": session_state.session_id,
            "capabilities": target.installed.capabilities,
            "capability_catalog": self._capability_catalog,
            "data_client": self._data_client,
            "boxy_tool_client": self._boxy_tool_client,
            "builtin_tool_client": self._builtin_tool_client,
            "llm_client": self._sdk_provider.llm_client(
                agent_name=target.installed.name,
                session_id=session_state.session_id,
            ),
            "memory_store": memory_store,
            "trace_callback": trace_callback,
            "terminate_callback": terminate_callback,
            "emit_event_callback": emit_event_callback,
        }

        return AgentExecutionContext(
            event=event,
            session_id=session_state.session_id,
            agent_name=target.installed.name,
            _runtime=_ContextRuntimeBindings(**bindings_kwargs),
        )

    def _invoke_handler(
        self,
        handler: AgentMainFunction,
        exec_ctx: AgentExecutionContext,
    ) -> AgentResult | JsonValue | None:
        try:
            return handler(exec_ctx)
        except AgentRuntimeError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AgentExecutionError(f"Agent handler raised an exception: {exc}") from exc


def _validate_scope(scope: str) -> None:
    if scope not in {"session", "persistent"}:
        raise ValueError("scope must be either 'session' or 'persistent'")


def _filter_descriptors[T](
    *,
    allowed: frozenset[str],
    catalog: dict[str, T],
) -> list[T]:
    return [descriptor for name in sorted(allowed) if (descriptor := catalog.get(name)) is not None]


def _validate_schema_instance(
    *,
    schema: dict[str, JsonValue],
    instance: JsonValue,
    label: str,
) -> None:
    validator = _ASSERTIVE_DRAFT_202012_VALIDATOR(schema, format_checker=_FORMAT_CHECKER)
    try:
        validator.validate(instance)
    except ValidationError as exc:
        raise CapabilitySchemaError(
            f"{label} failed JSON Schema validation: {exc.message}"
        ) from exc


def _coerce_event(event: AgentEvent | Mapping[str, object]) -> AgentEvent:
    if isinstance(event, AgentEvent):
        return event
    if not isinstance(event, Mapping):
        raise InvalidEventError("Event input must be an AgentEvent or mapping")

    event_type = event.get("type")
    if not isinstance(event_type, str) or not event_type.strip():
        raise InvalidEventError("Event requires non-empty string field 'type'")

    description = event.get("description", "")
    if not isinstance(description, str):
        raise InvalidEventError("Event field 'description' must be a string")

    payload = event.get("payload", {})
    if not isinstance(payload, dict):
        raise InvalidEventError("Event field 'payload' must be an object")
    for key, value in payload.items():
        if not isinstance(key, str) or not key.strip():
            raise InvalidEventError("Event payload keys must be non-empty strings")
        ensure_json_value(value, label=f"event payload value for key {key}")

    return AgentEvent(type=event_type.strip(), description=description, payload=dict(payload))


def _coerce_result(result: AgentResult | JsonValue | None) -> AgentResult:
    if isinstance(result, AgentResult):
        return result
    ensure_json_value(result, label="agent result")
    return AgentResult(output=result)


def _derive_status(*, session_state: _SessionState) -> RunStatus:
    if session_state.terminated_by_controller:
        return "terminated_by_controller"
    if session_state.terminated_by_agent:
        return "terminated_by_agent"
    return "idle"
