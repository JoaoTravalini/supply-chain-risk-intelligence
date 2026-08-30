"""Project-owned agent exception boundary."""

from __future__ import annotations


class AgentError(Exception):
    """Base class for agent runtime failures."""


class AgentConfigurationError(AgentError):
    """Raised when agent runtime configuration is invalid."""


class AgentPersistenceError(AgentError):
    """Raised when investigation state persistence fails."""


class InvestigationNotFoundError(AgentError):
    """Raised when no persisted investigation state exists for a thread."""
