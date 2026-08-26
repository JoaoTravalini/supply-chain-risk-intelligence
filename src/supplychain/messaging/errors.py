"""Project-owned messaging exception taxonomy."""

from __future__ import annotations


class MessagingError(Exception):
    """Base exception for safe messaging boundary failures."""

    def __init__(
        self,
        message: str,
        *,
        project_id: str | None = None,
        topic_id: str | None = None,
        topic_path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.project_id = project_id
        self.topic_id = topic_id
        self.topic_path = topic_path


class MessagingConfigurationError(MessagingError):
    """Messaging configuration is missing or unsafe."""


class LocalPubSubEmulatorConfigurationError(MessagingConfigurationError):
    """Local Pub/Sub emulator configuration is missing or unsafe."""


class LocalPubSubEmulatorBootstrapError(MessagingError):
    """Local Pub/Sub emulator topic bootstrap failed."""


class MessagePublishError(MessagingError):
    """Publishing a canonical event failed."""


class MessagePublishTimeoutError(MessagePublishError):
    """Publishing a canonical event did not acknowledge before the timeout."""
