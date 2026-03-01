"""Runtime exception hierarchy."""

from __future__ import annotations


class AgentRuntimeError(RuntimeError):
    """Base runtime error."""


class AgentExecutionError(AgentRuntimeError):
    """Raised when agent handler execution fails unexpectedly."""


class AgentNotFoundError(AgentRuntimeError):
    """Raised when an agent name cannot be resolved."""


class RegistrationError(AgentRuntimeError):
    """Raised when installed agents are malformed or conflicting."""


class CapabilityViolationError(AgentRuntimeError):
    """Raised when an agent attempts an undeclared capability."""


class CapabilitySchemaError(AgentRuntimeError):
    """Raised when capability input/output validation fails."""


class InvalidEventError(AgentRuntimeError):
    """Raised when runtime event input is invalid."""
