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


class MessageDeserializationError(MessagingError):
    """Message data could not be decoded and validated as a Canonical Event."""


class MessageAttributeMismatchError(MessagingError):
    """Message attributes disagree with the authoritative Canonical Event body."""

    def __init__(
        self,
        message: str,
        *,
        attribute: str,
        message_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.attribute = attribute
        self.message_id = message_id


class MessagePullError(MessagingError):
    """Pulling messages from Pub/Sub failed."""


class MessageAcknowledgeError(MessagingError):
    """Acknowledging Pub/Sub messages failed."""


class MessageRedeliveryRequestError(MessagingError):
    """Requesting Pub/Sub redelivery failed."""
