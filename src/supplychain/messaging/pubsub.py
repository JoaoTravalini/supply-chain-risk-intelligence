"""Pub/Sub publisher and local-emulator bootstrap for Canonical Events."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Protocol, cast
from uuid import UUID

from google.api_core.exceptions import AlreadyExists, GoogleAPICallError, NotFound, RetryError
from google.cloud import pubsub_v1  # type: ignore[attr-defined]

from supplychain.contracts import CanonicalEvent
from supplychain.messaging.errors import (
    LocalPubSubEmulatorBootstrapError,
    MessageAcknowledgeError,
    MessagePublishError,
    MessagePublishTimeoutError,
    MessagePullError,
    MessageRedeliveryRequestError,
)
from supplychain.messaging.serialization import (
    canonical_event_attributes,
    deserialize_canonical_event,
    serialize_canonical_event,
    validate_canonical_event_attributes,
)
from supplychain.messaging.topology import (
    CANONICAL_EVENTS_DEAD_LETTER_SUBSCRIPTION_ID,
    CANONICAL_EVENTS_DEAD_LETTER_TOPIC_ID,
    CANONICAL_EVENTS_SUBSCRIPTION_ID,
    CANONICAL_EVENTS_TOPIC_ID,
    LocalPubSubEmulatorConfig,
    PubSubSubscriptionConfig,
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


class PubsubMessage(Protocol):
    """Subset of a Pub/Sub message used by the pull consumer."""

    data: bytes
    attributes: Mapping[str, str]
    message_id: str


class ReceivedMessage(Protocol):
    """Subset of a Pub/Sub received message used by the pull consumer."""

    ack_id: str
    message: PubsubMessage
    delivery_attempt: int | None


class PullResponse(Protocol):
    """Subset of the Pub/Sub pull response."""

    received_messages: Sequence[ReceivedMessage]


class Subscription(Protocol):
    """Subset of a Pub/Sub subscription resource."""

    topic: str
    dead_letter_policy: object


class SubscriberClient(Protocol):
    """Subset of the Pub/Sub subscriber client used by Stage 9B."""

    def subscription_path(self, project: str, subscription: str) -> str:
        """Build the canonical Pub/Sub subscription path."""

    def pull(self, request: Mapping[str, object], timeout: float) -> object:
        """Pull messages from a subscription."""

    def acknowledge(self, request: Mapping[str, object]) -> object:
        """Acknowledge one or more delivery ack IDs."""

    def modify_ack_deadline(self, request: Mapping[str, object]) -> object:
        """Modify the acknowledgement deadline for one or more delivery ack IDs."""

    def get_subscription(self, request: Mapping[str, str]) -> Subscription:
        """Fetch a subscription by path."""

    def create_subscription(self, request: Mapping[str, object]) -> Subscription:
        """Create a subscription."""

    def delete_subscription(self, request: Mapping[str, str]) -> object:
        """Delete a local subscription by path."""

    def close(self) -> None:
        """Close the owned subscriber client."""


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


@dataclass(frozen=True, slots=True)
class LocalTopologyBootstrapResult:
    """Safe result for local Pub/Sub emulator topic and subscription bootstrap."""

    project_id: str
    topic_id: str
    topic_path: str
    topic_created: bool
    dead_letter_topic_id: str
    dead_letter_topic_path: str
    dead_letter_topic_created: bool
    subscription_id: str
    subscription_path: str
    subscription_created: bool
    subscription_recreated: bool
    dead_letter_subscription_id: str
    dead_letter_subscription_path: str
    dead_letter_subscription_created: bool
    dead_letter_subscription_recreated: bool
    ack_deadline_seconds: int
    dead_letter_max_delivery_attempts: int


@dataclass(frozen=True, slots=True)
class ReceivedCanonicalEvent:
    """Project-owned representation of a pulled Canonical Event delivery."""

    event: CanonicalEvent
    message_id: str
    ack_id: str
    delivery_attempt: int | None = None


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


class PubSubCanonicalEventConsumer:
    """Synchronously pull Canonical Events from one Pub/Sub subscription."""

    def __init__(
        self,
        config: PubSubSubscriptionConfig,
        *,
        client: SubscriberClient | None = None,
    ) -> None:
        self._config = config
        self._client = pubsub_v1.SubscriberClient() if client is None else client
        self._owns_client = client is None
        self._subscription_path = self._client.subscription_path(
            config.project_id,
            config.subscription_id,
        )

    @property
    def subscription_path(self) -> str:
        """Return the safe Pub/Sub subscription path used by this consumer."""

        return self._subscription_path

    def pull(
        self,
        *,
        max_messages: int,
        timeout_seconds: float | None = None,
    ) -> tuple[ReceivedCanonicalEvent, ...]:
        """Pull a bounded batch without acknowledging it."""

        timeout = self._validate_pull_inputs(
            max_messages=max_messages,
            timeout_seconds=timeout_seconds,
        )
        try:
            response = cast(
                PullResponse,
                self._client.pull(
                    request={
                        "subscription": self._subscription_path,
                        "max_messages": max_messages,
                    },
                    timeout=timeout,
                ),
            )
        except (GoogleAPICallError, RetryError) as exc:
            raise MessagePullError(
                "Pub/Sub pull failed",
                project_id=self._config.project_id,
                topic_path=self._subscription_path,
            ) from exc
        return tuple(_received_message_to_canonical(item) for item in response.received_messages)

    def acknowledge(self, received_messages: tuple[ReceivedCanonicalEvent, ...]) -> None:
        """Explicitly acknowledge pulled messages after caller validation/processing."""

        ack_ids = _unique_ack_ids(received_messages)
        if not ack_ids:
            return
        try:
            self._client.acknowledge(
                request={
                    "subscription": self._subscription_path,
                    "ack_ids": ack_ids,
                },
            )
        except (GoogleAPICallError, RetryError) as exc:
            raise MessageAcknowledgeError(
                "Pub/Sub acknowledgement failed",
                project_id=self._config.project_id,
                topic_path=self._subscription_path,
            ) from exc

    def request_redelivery(self, received_messages: tuple[ReceivedCanonicalEvent, ...]) -> None:
        """Request redelivery by setting the acknowledgement deadline to zero."""

        ack_ids = _unique_ack_ids(received_messages)
        if not ack_ids:
            return
        try:
            self._client.modify_ack_deadline(
                request={
                    "subscription": self._subscription_path,
                    "ack_ids": ack_ids,
                    "ack_deadline_seconds": 0,
                },
            )
        except (GoogleAPICallError, RetryError) as exc:
            raise MessageRedeliveryRequestError(
                "Pub/Sub redelivery request failed",
                project_id=self._config.project_id,
                topic_path=self._subscription_path,
            ) from exc

    def close(self) -> None:
        """Close the owned Pub/Sub client; injected clients remain caller-owned."""

        if self._owns_client:
            self._client.close()

    def __enter__(self) -> PubSubCanonicalEventConsumer:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _validate_pull_inputs(
        self,
        *,
        max_messages: int,
        timeout_seconds: float | None,
    ) -> float:
        if max_messages < 1 or max_messages > self._config.max_pull_messages_limit:
            raise ValueError("max_messages must be positive and within the configured limit")
        timeout = self._config.pull_timeout_seconds if timeout_seconds is None else timeout_seconds
        if timeout <= 0:
            raise ValueError("pull timeout must be positive and finite")
        return timeout


def ensure_local_pubsub_emulator_topic(
    *,
    config: LocalPubSubEmulatorConfig | None = None,
    client: PublisherClient | None = None,
) -> LocalTopicBootstrapResult:
    """Idempotently ensure the canonical topic exists in the local emulator only."""

    emulator_config = LocalPubSubEmulatorConfig.from_environment() if config is None else config
    return _ensure_local_pubsub_emulator_topic_id(
        config=emulator_config,
        topic_id=CANONICAL_EVENTS_TOPIC_ID,
        client=client,
    )


def _ensure_local_pubsub_emulator_topic_id(
    *,
    config: LocalPubSubEmulatorConfig,
    topic_id: str,
    client: PublisherClient | None,
) -> LocalTopicBootstrapResult:
    publisher_client = pubsub_v1.PublisherClient() if client is None else client
    owns_client = client is None
    topic_path = publisher_client.topic_path(config.project_id, topic_id)
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
            project_id=config.project_id,
            topic_id=topic_id,
            topic_path=topic_path,
            created=created,
        )
    except (GoogleAPICallError, RetryError) as exc:
        raise LocalPubSubEmulatorBootstrapError(
            "Local Pub/Sub emulator topic bootstrap failed",
            project_id=config.project_id,
            topic_id=topic_id,
            topic_path=topic_path,
        ) from exc
    finally:
        if owns_client:
            publisher_client.stop()


def ensure_local_pubsub_emulator_topology(
    *,
    config: LocalPubSubEmulatorConfig | None = None,
    publisher_client: PublisherClient | None = None,
    subscriber_client: SubscriberClient | None = None,
) -> LocalTopologyBootstrapResult:
    """Idempotently ensure the Stage 9 topic and subscription exist locally."""

    emulator_config = LocalPubSubEmulatorConfig.from_environment() if config is None else config
    topic_result = _ensure_local_pubsub_emulator_topic_id(
        config=emulator_config,
        topic_id=CANONICAL_EVENTS_TOPIC_ID,
        client=publisher_client,
    )
    dead_letter_topic_result = _ensure_local_pubsub_emulator_topic_id(
        config=emulator_config,
        topic_id=CANONICAL_EVENTS_DEAD_LETTER_TOPIC_ID,
        client=publisher_client,
    )
    subscriber = pubsub_v1.SubscriberClient() if subscriber_client is None else subscriber_client
    owns_subscriber = subscriber_client is None
    subscription_path = subscriber.subscription_path(
        emulator_config.project_id,
        CANONICAL_EVENTS_SUBSCRIPTION_ID,
    )
    subscription_created = False
    subscription_recreated = False
    dead_letter_subscription_path = subscriber.subscription_path(
        emulator_config.project_id,
        CANONICAL_EVENTS_DEAD_LETTER_SUBSCRIPTION_ID,
    )
    dead_letter_subscription_created = False
    dead_letter_subscription_recreated = False
    try:
        try:
            subscription = subscriber.get_subscription(request={"subscription": subscription_path})
            if not _subscription_matches_local_topology(
                subscription=subscription,
                topic_path=topic_result.topic_path,
                dead_letter_topic_path=dead_letter_topic_result.topic_path,
                max_delivery_attempts=emulator_config.dead_letter_max_delivery_attempts,
            ):
                subscriber.delete_subscription(request={"subscription": subscription_path})
                _create_local_processing_subscription(
                    subscriber=subscriber,
                    subscription_path=subscription_path,
                    topic_path=topic_result.topic_path,
                    dead_letter_topic_path=dead_letter_topic_result.topic_path,
                    ack_deadline_seconds=emulator_config.ack_deadline_seconds,
                    max_delivery_attempts=emulator_config.dead_letter_max_delivery_attempts,
                )
                subscription_created = True
                subscription_recreated = True
        except NotFound:
            _create_local_processing_subscription(
                subscriber=subscriber,
                subscription_path=subscription_path,
                topic_path=topic_result.topic_path,
                dead_letter_topic_path=dead_letter_topic_result.topic_path,
                ack_deadline_seconds=emulator_config.ack_deadline_seconds,
                max_delivery_attempts=emulator_config.dead_letter_max_delivery_attempts,
            )
            subscription_created = True
        try:
            dead_letter_subscription = subscriber.get_subscription(
                request={"subscription": dead_letter_subscription_path},
            )
            if dead_letter_subscription.topic != dead_letter_topic_result.topic_path:
                subscriber.delete_subscription(
                    request={"subscription": dead_letter_subscription_path},
                )
                _create_local_inspection_subscription(
                    subscriber=subscriber,
                    subscription_path=dead_letter_subscription_path,
                    topic_path=dead_letter_topic_result.topic_path,
                    ack_deadline_seconds=emulator_config.ack_deadline_seconds,
                )
                dead_letter_subscription_created = True
                dead_letter_subscription_recreated = True
        except NotFound:
            _create_local_inspection_subscription(
                subscriber=subscriber,
                subscription_path=dead_letter_subscription_path,
                topic_path=dead_letter_topic_result.topic_path,
                ack_deadline_seconds=emulator_config.ack_deadline_seconds,
            )
            dead_letter_subscription_created = True
        return LocalTopologyBootstrapResult(
            project_id=emulator_config.project_id,
            topic_id=topic_result.topic_id,
            topic_path=topic_result.topic_path,
            topic_created=topic_result.created,
            dead_letter_topic_id=dead_letter_topic_result.topic_id,
            dead_letter_topic_path=dead_letter_topic_result.topic_path,
            dead_letter_topic_created=dead_letter_topic_result.created,
            subscription_id=CANONICAL_EVENTS_SUBSCRIPTION_ID,
            subscription_path=subscription_path,
            subscription_created=subscription_created,
            subscription_recreated=subscription_recreated,
            dead_letter_subscription_id=CANONICAL_EVENTS_DEAD_LETTER_SUBSCRIPTION_ID,
            dead_letter_subscription_path=dead_letter_subscription_path,
            dead_letter_subscription_created=dead_letter_subscription_created,
            dead_letter_subscription_recreated=dead_letter_subscription_recreated,
            ack_deadline_seconds=emulator_config.ack_deadline_seconds,
            dead_letter_max_delivery_attempts=(emulator_config.dead_letter_max_delivery_attempts),
        )
    except LocalPubSubEmulatorBootstrapError:
        raise
    except (GoogleAPICallError, RetryError) as exc:
        raise LocalPubSubEmulatorBootstrapError(
            "Local Pub/Sub emulator subscription bootstrap failed",
            project_id=emulator_config.project_id,
            topic_id=topic_result.topic_id,
            topic_path=topic_result.topic_path,
        ) from exc
    finally:
        if owns_subscriber:
            subscriber.close()


def _create_local_processing_subscription(
    *,
    subscriber: SubscriberClient,
    subscription_path: str,
    topic_path: str,
    dead_letter_topic_path: str,
    ack_deadline_seconds: int,
    max_delivery_attempts: int,
) -> None:
    subscriber.create_subscription(
        request={
            "name": subscription_path,
            "topic": topic_path,
            "ack_deadline_seconds": ack_deadline_seconds,
            "dead_letter_policy": {
                "dead_letter_topic": dead_letter_topic_path,
                "max_delivery_attempts": max_delivery_attempts,
            },
        },
    )


def _create_local_inspection_subscription(
    *,
    subscriber: SubscriberClient,
    subscription_path: str,
    topic_path: str,
    ack_deadline_seconds: int,
) -> None:
    subscriber.create_subscription(
        request={
            "name": subscription_path,
            "topic": topic_path,
            "ack_deadline_seconds": ack_deadline_seconds,
        },
    )


def _subscription_matches_local_topology(
    *,
    subscription: Subscription,
    topic_path: str,
    dead_letter_topic_path: str,
    max_delivery_attempts: int,
) -> bool:
    if subscription.topic != topic_path:
        return False
    policy = getattr(subscription, "dead_letter_policy", None)
    if policy is None:
        return False
    return (
        _policy_dead_letter_topic(policy) == dead_letter_topic_path
        and _policy_max_delivery_attempts(policy) == max_delivery_attempts
    )


def _policy_dead_letter_topic(policy: object) -> str | None:
    if isinstance(policy, Mapping):
        value = policy.get("dead_letter_topic")
    else:
        value = getattr(policy, "dead_letter_topic", None)
    return None if value is None else str(value)


def _policy_max_delivery_attempts(policy: object) -> int | None:
    if isinstance(policy, Mapping):
        value = policy.get("max_delivery_attempts")
    else:
        value = getattr(policy, "max_delivery_attempts", None)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _received_message_to_canonical(message: ReceivedMessage) -> ReceivedCanonicalEvent:
    event = deserialize_canonical_event(message.message.data)
    attributes = dict(message.message.attributes)
    validate_canonical_event_attributes(
        event=event,
        attributes=attributes,
        message_id=message.message.message_id,
    )
    return ReceivedCanonicalEvent(
        event=event,
        message_id=message.message.message_id,
        ack_id=message.ack_id,
        delivery_attempt=message.delivery_attempt,
    )


def _unique_ack_ids(received_messages: tuple[ReceivedCanonicalEvent, ...]) -> list[str]:
    ack_ids: list[str] = []
    seen: set[str] = set()
    for message in received_messages:
        if message.ack_id not in seen:
            ack_ids.append(message.ack_id)
            seen.add(message.ack_id)
    return ack_ids
