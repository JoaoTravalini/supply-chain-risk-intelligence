"""Pub/Sub publisher and local-emulator bootstrap for Canonical Events."""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from google.api_core.exceptions import AlreadyExists, GoogleAPICallError, NotFound, RetryError
from google.cloud import pubsub_v1  # type: ignore[import-untyped]

from supplychain.contracts import CanonicalEvent
from supplychain.messaging.errors import (
    LocalPubSubEmulatorBootstrapError,
    MessagePublishError,
    MessagePublishTimeoutError,
)
from supplychain.messaging.serialization import (
    canonical_event_attributes,
    serialize_canonical_event,
)
from supplychain.messaging.topology import (
    CANONICAL_EVENTS_TOPIC_ID,
    LocalPubSubEmulatorConfig,
    PubSubTopicConfig,
)


class PublishFuture(Protocol):
    """Subset of the Pub/Sub publish future required by this project."""

    def result(self, timeout: float | None = None) -> str:
        """Return the transport-assigned Pub/Sub message ID."""


class PublisherClient(Protocol):
    """Subset of the Pub/Sub publisher client used by Stage 9A."""

    def topic_path(self, project: str, topic: str) -> str:
        """Build the canonical Pub/Sub topic path."""

    def publish(self, topic: str, data: bytes, **attrs: str) -> PublishFuture:
        """Publish message data and attributes."""

    def get_topic(self, request: Mapping[str, str]) -> object:
        """Fetch a topic by path."""

    def create_topic(self, request: Mapping[str, str]) -> object:
        """Create a topic by path."""

    def stop(self) -> None:
        """Stop the owned publisher client."""


@dataclass(frozen=True, slots=True)
class PublishReceipt:
    """Safe result returned after Pub/Sub acknowledges a publish."""

    message_id: str
    event_id: UUID
    topic_id: str
    topic_path: str


@dataclass(frozen=True, slots=True)
class LocalTopicBootstrapResult:
    """Safe result for local Pub/Sub emulator topic bootstrap."""

    project_id: str
    topic_id: str
    topic_path: str
    created: bool


class PubSubCanonicalEventPublisher:
    """Publish Canonical Events to one configured Pub/Sub topic."""

    def __init__(
        self,
        config: PubSubTopicConfig,
        *,
        client: PublisherClient | None = None,
    ) -> None:
        self._config = config
        self._client = pubsub_v1.PublisherClient() if client is None else client
        self._owns_client = client is None
        self._topic_path = self._client.topic_path(config.project_id, config.topic_id)

    @property
    def topic_path(self) -> str:
        """Return the safe Pub/Sub topic path used by this publisher."""

        return self._topic_path

    def publish(self, event: CanonicalEvent) -> PublishReceipt:
        """Serialize, attribute, publish, and await acknowledgement for one event."""

        data = serialize_canonical_event(event)
        attributes = canonical_event_attributes(event)
        try:
            future = self._client.publish(self._topic_path, data, **attributes)
            message_id = future.result(timeout=self._config.publish_ack_timeout_seconds)
        except FutureTimeoutError as exc:
            raise MessagePublishTimeoutError(
                "Pub/Sub publish acknowledgement timed out",
                project_id=self._config.project_id,
                topic_id=self._config.topic_id,
                topic_path=self._topic_path,
            ) from exc
        except (GoogleAPICallError, RetryError) as exc:
            raise MessagePublishError(
                "Pub/Sub publish failed",
                project_id=self._config.project_id,
                topic_id=self._config.topic_id,
                topic_path=self._topic_path,
            ) from exc
        return PublishReceipt(
            message_id=message_id,
            event_id=event.event_id,
            topic_id=self._config.topic_id,
            topic_path=self._topic_path,
        )

    def close(self) -> None:
        """Close the owned Pub/Sub client; injected clients remain caller-owned."""

        if self._owns_client:
            self._client.stop()

    def __enter__(self) -> PubSubCanonicalEventPublisher:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def ensure_local_pubsub_emulator_topic(
    *,
    config: LocalPubSubEmulatorConfig | None = None,
    client: PublisherClient | None = None,
) -> LocalTopicBootstrapResult:
    """Idempotently ensure the canonical topic exists in the local emulator only."""

    emulator_config = LocalPubSubEmulatorConfig.from_environment() if config is None else config
    publisher_client = pubsub_v1.PublisherClient() if client is None else client
    owns_client = client is None
    topic_id = CANONICAL_EVENTS_TOPIC_ID
    topic_path = publisher_client.topic_path(emulator_config.project_id, topic_id)
    try:
        try:
            publisher_client.get_topic(request={"topic": topic_path})
            created = False
        except NotFound:
            try:
                publisher_client.create_topic(request={"name": topic_path})
                created = True
            except AlreadyExists:
                created = False
        return LocalTopicBootstrapResult(
            project_id=emulator_config.project_id,
            topic_id=topic_id,
            topic_path=topic_path,
            created=created,
        )
    except (GoogleAPICallError, RetryError) as exc:
        raise LocalPubSubEmulatorBootstrapError(
            "Local Pub/Sub emulator topic bootstrap failed",
            project_id=emulator_config.project_id,
            topic_id=topic_id,
            topic_path=topic_path,
        ) from exc
    finally:
        if owns_client:
            publisher_client.stop()
