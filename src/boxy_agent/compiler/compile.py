"""Agent compilation entrypoint."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from boxy_agent.capabilities import CapabilityCatalog
from boxy_agent.compiler.metadata import load_agent_metadata
from boxy_agent.compiler.models import CompiledAgent, CompiledManifest


class CompilationError(ValueError):
    """Raised when an agent project cannot be compiled."""


def compile_agent(
    project_dir: Path,
    output_dir: Path,
    *,
    capability_catalog: CapabilityCatalog,
) -> CompiledAgent:
    """Compile an agent project into a validated manifest artifact."""
    project = project_dir.resolve()
    if not project.exists():
        raise CompilationError(f"Project directory does not exist: {project}")
    if capability_catalog is None:
        raise CompilationError("capability_catalog is required")

    metadata = load_agent_metadata(project, capability_catalog=capability_catalog)
    module_path = _resolve_module_path(project, metadata.module)
    entrypoint_function = _find_entrypoint_function(module_path)

    manifest = CompiledManifest.from_metadata(
        metadata=metadata,
        entrypoint_function=entrypoint_function,
    )

    compiled_output_dir = output_dir.resolve()
    compiled_output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = compiled_output_dir / f"{metadata.name}.compiled.json"
    manifest_path.write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return CompiledAgent(
        project_dir=project,
        output_dir=compiled_output_dir,
        module_path=module_path,
        manifest_path=manifest_path,
        manifest=manifest,
    )


def _resolve_module_path(project_dir: Path, module: str) -> Path:
    relative = Path(*module.split("."))
    candidates = [
        project_dir / "src" / relative.with_suffix(".py"),
        project_dir / relative.with_suffix(".py"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    rendered = ", ".join(str(candidate) for candidate in candidates)
    raise CompilationError(f"Could not resolve module '{module}'. Tried: {rendered}")


def _find_entrypoint_function(module_path: Path) -> str:
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module_path))

    decorated_defs: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    # Intentionally inspect only module-level definitions. This avoids import-time execution
    # and keeps compilation deterministic for static entrypoint validation.
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _has_agent_main_decorator(
            node
        ):
            decorated_defs.append(node)

    if not decorated_defs:
        raise CompilationError("Module must define exactly one function decorated with @agent_main")
    if len(decorated_defs) > 1:
        names = ", ".join(node.name for node in decorated_defs)
        raise CompilationError(
            f"Module defines multiple @agent_main functions: {names}. Exactly one is required"
        )

    entrypoint = decorated_defs[0]
    if isinstance(entrypoint, ast.AsyncFunctionDef):
        raise CompilationError(
            "@agent_main function must be synchronous (use `def`, not `async def`)"
        )
    _validate_signature(entrypoint)
    return entrypoint.name


def _has_agent_main_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator
        if isinstance(decorator, ast.Call):
            target = decorator.func
        # Support both `@agent_main` and qualified forms like `@boxy_agent.agent_main`.
        if isinstance(target, ast.Name) and target.id == "agent_main":
            return True
        if isinstance(target, ast.Attribute) and target.attr == "agent_main":
            return True
    return False


def _validate_signature(function_def: ast.FunctionDef) -> None:
    args = function_def.args
    positional_count = len(args.posonlyargs) + len(args.args)
    has_extras = bool(args.vararg or args.kwonlyargs or args.kwarg)
    if positional_count != 1 or has_extras:
        raise CompilationError(
            "@agent_main function must accept exactly one positional execution context argument"
        )
    if args.defaults:
        raise CompilationError(
            "@agent_main function execution context argument must not have defaults"
        )
