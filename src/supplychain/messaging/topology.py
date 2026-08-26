"""Pub/Sub topology and local-emulator configuration."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass

from supplychain.messaging.errors import LocalPubSubEmulatorConfigurationError

CANONICAL_EVENTS_TOPIC_ID = "canonical-events-v1"
CANONICAL_EVENTS_SUBSCRIPTION_ID = "canonical-events-processing-v1"
LOCAL_PUBSUB_PROJECT_ID = "supplychain-local"
PUBSUB_EMULATOR_HOST_ENV = "PUBSUB_EMULATOR_HOST"
PUBSUB_PROJECT_ID_ENV = "PUBSUB_PROJECT_ID"
DEFAULT_PUBLISH_ACK_TIMEOUT_SECONDS = 10.0
DEFAULT_ACK_DEADLINE_SECONDS = 30
DEFAULT_PULL_TIMEOUT_SECONDS = 5.0
MAX_PULL_MESSAGES = 100


@dataclass(frozen=True, slots=True)
class PubSubTopicConfig:
    """Explicit Pub/Sub topic configuration for a publisher."""

    project_id: str
    topic_id: str = CANONICAL_EVENTS_TOPIC_ID
    publish_ack_timeout_seconds: float = DEFAULT_PUBLISH_ACK_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise LocalPubSubEmulatorConfigurationError("Pub/Sub project ID must not be blank")
        if not self.topic_id.strip():
            raise LocalPubSubEmulatorConfigurationError("Pub/Sub topic ID must not be blank")
        if self.publish_ack_timeout_seconds <= 0 or not math.isfinite(
            self.publish_ack_timeout_seconds
        ):
            raise LocalPubSubEmulatorConfigurationError(
                "Pub/Sub publish acknowledgement timeout must be positive and finite",
                project_id=self.project_id,
                topic_id=self.topic_id,
            )


@dataclass(frozen=True, slots=True)
class PubSubSubscriptionConfig:
    """Explicit Pub/Sub pull subscription configuration."""

    project_id: str
    subscription_id: str = CANONICAL_EVENTS_SUBSCRIPTION_ID
    pull_timeout_seconds: float = DEFAULT_PULL_TIMEOUT_SECONDS
    max_pull_messages_limit: int = MAX_PULL_MESSAGES

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise LocalPubSubEmulatorConfigurationError("Pub/Sub project ID must not be blank")
        if not self.subscription_id.strip():
            raise LocalPubSubEmulatorConfigurationError("Pub/Sub subscription ID must not be blank")
        if self.pull_timeout_seconds <= 0 or not math.isfinite(self.pull_timeout_seconds):
            raise LocalPubSubEmulatorConfigurationError(
                "Pub/Sub pull timeout must be positive and finite",
                project_id=self.project_id,
            )
        if self.max_pull_messages_limit < 1:
            raise LocalPubSubEmulatorConfigurationError(
                "Pub/Sub maximum pull messages limit must be positive",
                project_id=self.project_id,
            )


@dataclass(frozen=True, slots=True)
class LocalPubSubEmulatorConfig:
    """Fail-closed local Pub/Sub emulator configuration."""

    emulator_host: str
    project_id: str
    topic_id: str = CANONICAL_EVENTS_TOPIC_ID
    subscription_id: str = CANONICAL_EVENTS_SUBSCRIPTION_ID
    publish_ack_timeout_seconds: float = DEFAULT_PUBLISH_ACK_TIMEOUT_SECONDS
    pull_timeout_seconds: float = DEFAULT_PULL_TIMEOUT_SECONDS
    ack_deadline_seconds: int = DEFAULT_ACK_DEADLINE_SECONDS

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> LocalPubSubEmulatorConfig:
        source = os.environ if environ is None else environ
        emulator_host = source.get(PUBSUB_EMULATOR_HOST_ENV)
        project_id = source.get(PUBSUB_PROJECT_ID_ENV)
        if emulator_host is None:
            raise LocalPubSubEmulatorConfigurationError("PUBSUB_EMULATOR_HOST is required")
        if project_id is None:
            raise LocalPubSubEmulatorConfigurationError("PUBSUB_PROJECT_ID is required")
        return cls(emulator_host=emulator_host, project_id=project_id)

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise LocalPubSubEmulatorConfigurationError("PUBSUB_PROJECT_ID must not be blank")
        if not self.emulator_host.strip():
            raise LocalPubSubEmulatorConfigurationError("PUBSUB_EMULATOR_HOST must not be blank")
        if not is_loopback_emulator_host(self.emulator_host):
            raise LocalPubSubEmulatorConfigurationError(
                "PUBSUB_EMULATOR_HOST must target a local loopback emulator",
                project_id=self.project_id,
                topic_id=self.topic_id,
            )
        PubSubTopicConfig(
            project_id=self.project_id,
            topic_id=self.topic_id,
            publish_ack_timeout_seconds=self.publish_ack_timeout_seconds,
        )
        PubSubSubscriptionConfig(
            project_id=self.project_id,
            subscription_id=self.subscription_id,
            pull_timeout_seconds=self.pull_timeout_seconds,
        )
        if self.ack_deadline_seconds < 10 or self.ack_deadline_seconds > 600:
            raise LocalPubSubEmulatorConfigurationError(
                "Pub/Sub acknowledgement deadline must be between 10 and 600 seconds",
                project_id=self.project_id,
                topic_id=self.topic_id,
            )

    def topic_config(self) -> PubSubTopicConfig:
        """Return publisher configuration for the guarded local emulator project."""

        return PubSubTopicConfig(
            project_id=self.project_id,
            topic_id=self.topic_id,
            publish_ack_timeout_seconds=self.publish_ack_timeout_seconds,
        )

    def subscription_config(self) -> PubSubSubscriptionConfig:
        """Return consumer configuration for the guarded local emulator project."""

        return PubSubSubscriptionConfig(
            project_id=self.project_id,
            subscription_id=self.subscription_id,
            pull_timeout_seconds=self.pull_timeout_seconds,
        )


def is_loopback_emulator_host(value: str) -> bool:
    """Return whether a host:port string points at an accepted loopback emulator."""

    host, port = _split_host_port(value.strip())
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return False
    return port.isdecimal() and 1 <= int(port) <= 65535


def _split_host_port(value: str) -> tuple[str, str]:
    if value.startswith("[::1]:"):
        return "::1", value.removeprefix("[::1]:")
    host, separator, port = value.rpartition(":")
    if not separator:
        return "", ""
    return host, port
