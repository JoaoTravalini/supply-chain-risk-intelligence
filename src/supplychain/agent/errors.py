"""Project-owned agent exception boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AgentError(Exception):
    """Base class for agent runtime failures."""


class AgentConfigurationError(AgentError):
    """Raised when agent runtime configuration is invalid."""


class AgentPersistenceError(AgentError):
    """Raised when investigation state persistence fails."""


class InvestigationNotFoundError(AgentError):
    """Raised when no persisted investigation state exists for a thread."""


class HumanReviewTransitionError(AgentError):
    """Raised when a human review decision is invalid for the current state."""


class ProviderFailureCategory(StrEnum):
    """Safe bounded model-provider failure categories."""

    AUTHENTICATION = "AUTHENTICATION"
    PERMISSION = "PERMISSION"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    QUOTA = "QUOTA"
    RATE_LIMIT = "RATE_LIMIT"
    INVALID_REQUEST = "INVALID_REQUEST"
    TIMEOUT = "TIMEOUT"
    NETWORK = "NETWORK"
    SDK_CONFIGURATION = "SDK_CONFIGURATION"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ProviderFailureDiagnostic:
    """Sanitized provider failure metadata safe for checkpoint state."""

    category: ProviderFailureCategory
    exception_class: str
    status_code: str | None = None


class InvestigationModelError(AgentError):
    """Raised when the investigation model provider fails safely."""

    def __init__(
        self,
        message: str,
        *,
        provider_failure: ProviderFailureDiagnostic | None = None,
    ) -> None:
        super().__init__(message)
        self.provider_failure = provider_failure


class InvestigationModelConfigurationError(InvestigationModelError):
    """Raised when model provider configuration is invalid."""


class InvestigationOutputValidationError(InvestigationModelError):
    """Raised when model output fails structural or evidence validation."""


class InvestigationContextError(AgentError):
    """Raised when bounded investigation context cannot be constructed."""
