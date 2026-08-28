from __future__ import annotations

import inspect
import json
from collections.abc import Mapping
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import UTC, datetime
from typing import ClassVar, cast
from uuid import UUID

import pytest
from google.api_core.exceptions import AlreadyExists, GoogleAPICallError, NotFound

from supplychain.contracts import (
    CanonicalEvent,
    EventMetadata,
    EventType,
    SourceMetadata,
    generate_deduplication_key,
)
from supplychain.messaging import (
    CANONICAL_EVENTS_DEAD_LETTER_SUBSCRIPTION_ID,
    CANONICAL_EVENTS_DEAD_LETTER_TOPIC_ID,
    CANONICAL_EVENTS_SUBSCRIPTION_ID,
    CANONICAL_EVENTS_TOPIC_ID,
    DEFAULT_ACK_DEADLINE_SECONDS,
    LOCAL_PUBSUB_PROJECT_ID,
    MESSAGE_CONTENT_TYPE,
    PUBSUB_DEAD_LETTER_MAX_DELIVERY_ATTEMPTS,
    LocalPubSubEmulatorConfig,
    LocalPubSubEmulatorConfigurationError,
    MessageAcknowledgeError,
    MessageAttributeMismatchError,
    MessageDeserializationError,
    MessagePublishError,
    MessagePublishTimeoutError,
    MessagePullError,
    MessageRedeliveryRequestError,
    PubSubCanonicalEventConsumer,
    PubSubCanonicalEventPublisher,
    PubSubSubscriptionConfig,
    PubSubTopicConfig,
    canonical_event_attributes,
    deserialize_canonical_event,
    ensure_local_pubsub_emulator_topic,
    ensure_local_pubsub_emulator_topology,
    is_loopback_emulator_host,
    serialize_canonical_event,
    validate_canonical_event_attributes,
)


class FakeFuture:
    def __init__(self, message_id: str = "transport-message-001", *, timeout: bool = False) -> None:
        self.message_id = message_id
        self.timeout = timeout
        self.received_timeout: float | None = None

    def result(self, timeout: float | None = None) -> str:
        self.received_timeout = timeout
        if self.timeout:
            raise FutureTimeoutError
        return self.message_id


class FakePublisherClient:
    topic_paths: ClassVar[list[str]] = []

    def __init__(
        self,
        *,
        future: FakeFuture | None = None,
        publish_error: GoogleAPICallError | None = None,
        topic_exists: bool = True,
        create_already_exists: bool = False,
    ) -> None:
        self.future = FakeFuture() if future is None else future
        self.publish_error = publish_error
        self.topic_exists = topic_exists
        self.create_already_exists = create_already_exists
        self.published_topic: str | None = None
        self.published_data: bytes | None = None
        self.published_attrs: dict[str, str] | None = None
        self.get_topic_requests: list[Mapping[str, str]] = []
        self.create_topic_requests: list[Mapping[str, str]] = []
        self.stopped = False

    def topic_path(self, project: str, topic: str) -> str:
        path = f"projects/{project}/topics/{topic}"
        self.topic_paths.append(path)
        return path

    def publish(self, topic: str, data: bytes, **attrs: str) -> FakeFuture:
        if self.publish_error is not None:
            raise self.publish_error
        self.published_topic = topic
        self.published_data = data
        self.published_attrs = attrs
        return self.future

    def get_topic(self, request: Mapping[str, str]) -> object:
        self.get_topic_requests.append(request)
        if not self.topic_exists:
            raise NotFound("missing topic")  # type: ignore[no-untyped-call]
        return object()

    def create_topic(self, request: Mapping[str, str]) -> object:
        self.create_topic_requests.append(request)
        if self.create_already_exists:
            raise AlreadyExists("topic exists")  # type: ignore[no-untyped-call]
        self.topic_exists = True
        return object()

    def stop(self) -> None:
        self.stopped = True


class FakePubsubMessage:
    def __init__(
        self,
        *,
        data: bytes,
        attributes: Mapping[str, str],
        message_id: str,
    ) -> None:
        self.data = data
        self.attributes = attributes
        self.message_id = message_id


class FakeReceivedMessage:
    def __init__(
        self,
        *,
        ack_id: str,
        message: FakePubsubMessage,
        delivery_attempt: int | None = None,
    ) -> None:
        self.ack_id = ack_id
        self.message = message
        self.delivery_attempt = delivery_attempt


class FakePullResponse:
    def __init__(self, received_messages: list[FakeReceivedMessage]) -> None:
        self.received_messages: tuple[FakeReceivedMessage, ...] = tuple(received_messages)


class FakeSubscription:
    def __init__(self, *, topic: str, dead_letter_policy: object) -> None:
        self.topic = topic
        self.dead_letter_policy = dead_letter_policy


_DEFAULT_DEAD_LETTER_POLICY = object()


class FakeSubscriberClient:
    def __init__(
        self,
        *,
        received_messages: list[FakeReceivedMessage] | None = None,
        pull_error: GoogleAPICallError | None = None,
        acknowledge_error: GoogleAPICallError | None = None,
        nack_error: GoogleAPICallError | None = None,
        subscription_exists: bool = True,
        subscription_topic: str = "projects/supplychain-local/topics/canonical-events-v1",
        dead_letter_policy: Mapping[str, object] | object | None = _DEFAULT_DEAD_LETTER_POLICY,
        dead_letter_subscription_exists: bool = True,
        dead_letter_subscription_topic: str = (
            "projects/supplychain-local/topics/canonical-events-dead-letter-v1"
        ),
    ) -> None:
        self.received_messages = [] if received_messages is None else received_messages
        self.pull_error = pull_error
        self.acknowledge_error = acknowledge_error
        self.nack_error = nack_error
        self.subscription_exists = subscription_exists
        self.subscription_topic = subscription_topic
        self.dead_letter_subscription_exists = dead_letter_subscription_exists
        self.dead_letter_subscription_topic = dead_letter_subscription_topic
        if dead_letter_policy is _DEFAULT_DEAD_LETTER_POLICY:
            self.dead_letter_policy: Mapping[str, object] | None = {
                "dead_letter_topic": (
                    "projects/supplychain-local/topics/canonical-events-dead-letter-v1"
                ),
                "max_delivery_attempts": PUBSUB_DEAD_LETTER_MAX_DELIVERY_ATTEMPTS,
            }
        else:
            self.dead_letter_policy = cast(Mapping[str, object] | None, dead_letter_policy)
        self.pull_requests: list[Mapping[str, object]] = []
        self.pull_timeouts: list[float] = []
        self.acknowledge_requests: list[Mapping[str, object]] = []
        self.nack_requests: list[Mapping[str, object]] = []
        self.get_subscription_requests: list[Mapping[str, str]] = []
        self.create_subscription_requests: list[Mapping[str, object]] = []
        self.delete_subscription_requests: list[Mapping[str, str]] = []
        self.closed = False

    def subscription_path(self, project: str, subscription: str) -> str:
        return f"projects/{project}/subscriptions/{subscription}"

    def pull(self, request: Mapping[str, object], timeout: float) -> FakePullResponse:
        if self.pull_error is not None:
            raise self.pull_error
        self.pull_requests.append(request)
        self.pull_timeouts.append(timeout)
        return FakePullResponse(self.received_messages)

    def acknowledge(self, request: Mapping[str, object]) -> object:
        if self.acknowledge_error is not None:
            raise self.acknowledge_error
        self.acknowledge_requests.append(request)
        return object()

    def modify_ack_deadline(self, request: Mapping[str, object]) -> object:
        if self.nack_error is not None:
            raise self.nack_error
        self.nack_requests.append(request)
        return object()

    def get_subscription(self, request: Mapping[str, str]) -> FakeSubscription:
        self.get_subscription_requests.append(request)
        if request["subscription"].endswith(
            f"/subscriptions/{CANONICAL_EVENTS_DEAD_LETTER_SUBSCRIPTION_ID}",
        ):
            if not self.dead_letter_subscription_exists:
                raise NotFound("missing dead-letter subscription")  # type: ignore[no-untyped-call]
            return FakeSubscription(
                topic=self.dead_letter_subscription_topic,
                dead_letter_policy=None,
            )
        if not self.subscription_exists:
            raise NotFound("missing subscription")  # type: ignore[no-untyped-call]
        return FakeSubscription(
            topic=self.subscription_topic,
            dead_letter_policy=self.dead_letter_policy,
        )

    def create_subscription(self, request: Mapping[str, object]) -> FakeSubscription:
        self.create_subscription_requests.append(request)
        name = cast(str, request["name"])
        if name.endswith(f"/subscriptions/{CANONICAL_EVENTS_DEAD_LETTER_SUBSCRIPTION_ID}"):
            self.dead_letter_subscription_exists = True
            self.dead_letter_subscription_topic = cast(str, request["topic"])
            return FakeSubscription(
                topic=self.dead_letter_subscription_topic,
                dead_letter_policy=None,
            )
        self.subscription_exists = True
        self.subscription_topic = cast(str, request["topic"])
        self.dead_letter_policy = cast(Mapping[str, object], request.get("dead_letter_policy"))
        return FakeSubscription(
            topic=self.subscription_topic,
            dead_letter_policy=self.dead_letter_policy,
        )

    def delete_subscription(self, request: Mapping[str, str]) -> object:
        self.delete_subscription_requests.append(request)
        if request["subscription"].endswith(
            f"/subscriptions/{CANONICAL_EVENTS_DEAD_LETTER_SUBSCRIPTION_ID}",
        ):
            self.dead_letter_subscription_exists = False
            return object()
        self.subscription_exists = False
        return object()

    def close(self) -> None:
        self.closed = True


def make_event(*, source_endpoint: str | None = "synthetic://supplier/snapshot") -> CanonicalEvent:
    event_time = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    source = SourceMetadata(
        provider="synthetic-operational",
        endpoint=source_endpoint,
        source_event_id="supplier-snapshot-001",
    )
    return CanonicalEvent(
        event_id=UUID("5f3b719c-0b5f-4c8c-9c92-0d2f3d0b9f10"),
        event_type=EventType.SUPPLIER_OPERATIONAL_SNAPSHOT_RECORDED,
        event_time=event_time,
        ingested_at=datetime(2026, 8, 26, 12, 1, tzinfo=UTC),
        source=source,
        payload={"status": "nominal", "on_time_delivery_pct": 98.5},
        metadata=EventMetadata(
            correlation_id="corr-pubsub-001",
            producer="synthetic-publisher-test",
            producer_version="1.0.0",
            deduplication_key=generate_deduplication_key(
                source=source,
                event_type=EventType.SUPPLIER_OPERATIONAL_SNAPSHOT_RECORDED,
                event_time=event_time,
            ),
        ),
    )


def make_received_message(
    *,
    event: CanonicalEvent | None = None,
    attributes: dict[str, str] | None = None,
    message_id: str = "transport-message-001",
    ack_id: str = "ack-001",
) -> FakeReceivedMessage:
    canonical_event = make_event() if event is None else event
    message_attributes = (
        canonical_event_attributes(canonical_event) if attributes is None else attributes
    )
    return FakeReceivedMessage(
        ack_id=ack_id,
        message=FakePubsubMessage(
            data=serialize_canonical_event(canonical_event),
            attributes=message_attributes,
            message_id=message_id,
        ),
    )


def test_valid_local_emulator_configuration() -> None:
    config = LocalPubSubEmulatorConfig.from_environment(
        {
            "PUBSUB_EMULATOR_HOST": "127.0.0.1:8085",
            "PUBSUB_PROJECT_ID": LOCAL_PUBSUB_PROJECT_ID,
        }
    )

    assert config.emulator_host == "127.0.0.1:8085"
    assert config.project_id == LOCAL_PUBSUB_PROJECT_ID
    assert config.topic_config().topic_id == CANONICAL_EVENTS_TOPIC_ID


def test_missing_pubsub_emulator_host_is_rejected() -> None:
    with pytest.raises(LocalPubSubEmulatorConfigurationError):
        LocalPubSubEmulatorConfig.from_environment({"PUBSUB_PROJECT_ID": LOCAL_PUBSUB_PROJECT_ID})


def test_missing_pubsub_project_id_is_rejected() -> None:
    with pytest.raises(LocalPubSubEmulatorConfigurationError):
        LocalPubSubEmulatorConfig.from_environment({"PUBSUB_EMULATOR_HOST": "127.0.0.1:8085"})


def test_blank_pubsub_project_id_is_rejected() -> None:
    with pytest.raises(LocalPubSubEmulatorConfigurationError):
        LocalPubSubEmulatorConfig(emulator_host="127.0.0.1:8085", project_id=" ")


@pytest.mark.parametrize("host", ["127.0.0.1:8085", "localhost:9000", "[::1]:8085"])
def test_loopback_emulator_hosts_are_accepted(host: str) -> None:
    assert is_loopback_emulator_host(host)


@pytest.mark.parametrize("host", ["pubsub.googleapis.com:443", "10.0.0.2:8085", "127.0.0.1"])
def test_non_local_emulator_bootstrap_targets_are_rejected(host: str) -> None:
    with pytest.raises(LocalPubSubEmulatorConfigurationError):
        LocalPubSubEmulatorConfig(emulator_host=host, project_id=LOCAL_PUBSUB_PROJECT_ID)


def test_canonical_topic_id_is_the_approved_topology_value() -> None:
    assert CANONICAL_EVENTS_TOPIC_ID == "canonical-events-v1"


def test_canonical_dead_letter_topic_id_is_the_approved_topology_value() -> None:
    assert CANONICAL_EVENTS_DEAD_LETTER_TOPIC_ID == "canonical-events-dead-letter-v1"


def test_canonical_dead_letter_subscription_id_is_the_approved_topology_value() -> None:
    assert (
        CANONICAL_EVENTS_DEAD_LETTER_SUBSCRIPTION_ID == "canonical-events-dead-letter-inspection-v1"
    )


def test_canonical_event_serializes_to_bytes() -> None:
    assert isinstance(serialize_canonical_event(make_event()), bytes)


def test_serialized_bytes_are_utf8_json() -> None:
    decoded = serialize_canonical_event(make_event()).decode("utf-8")

    assert json.loads(decoded)["event_type"] == "supplier.operational.snapshot.recorded"


def test_serialized_body_validates_as_canonical_event() -> None:
    round_tripped = CanonicalEvent.model_validate_json(serialize_canonical_event(make_event()))

    assert round_tripped.event_id == make_event().event_id


def test_serialization_is_deterministic_for_repeated_calls() -> None:
    event = make_event()

    assert serialize_canonical_event(event) == serialize_canonical_event(event)


def test_serialization_is_independent_of_runtime_payload_key_order() -> None:
    first = make_event()
    second_data = first.model_dump()
    second_data["payload"] = {"on_time_delivery_pct": 98.5, "status": "nominal"}
    second = CanonicalEvent.model_validate(second_data)

    assert serialize_canonical_event(first) == serialize_canonical_event(second)


def test_canonical_event_payload_is_not_wrapped_in_message_envelope() -> None:
    body = json.loads(serialize_canonical_event(make_event()).decode("utf-8"))

    assert "event_id" in body
    assert "event" not in body


def test_identity_values_survive_round_trip_serialization() -> None:
    event = make_event()
    round_tripped = CanonicalEvent.model_validate_json(serialize_canonical_event(event))

    assert round_tripped.event_id == event.event_id
    assert round_tripped.metadata.deduplication_key == event.metadata.deduplication_key
    assert round_tripped.source.source_event_id == event.source.source_event_id


def test_serialization_does_not_mutate_event_identity_fields() -> None:
    event = make_event()
    before = (event.event_id, event.ingested_at, event.metadata.deduplication_key)

    serialize_canonical_event(event)

    assert (event.event_id, event.ingested_at, event.metadata.deduplication_key) == before


def test_required_approved_attributes_are_created() -> None:
    attrs = canonical_event_attributes(make_event())

    assert attrs == {
        "content_type": "application/json",
        "correlation_id": "corr-pubsub-001",
        "deduplication_key": make_event().metadata.deduplication_key,
        "event_id": "5f3b719c-0b5f-4c8c-9c92-0d2f3d0b9f10",
        "event_type": "supplier.operational.snapshot.recorded",
        "producer": "synthetic-publisher-test",
        "producer_version": "1.0.0",
        "schema_version": "1.0.0",
        "source_provider": "synthetic-operational",
    }


def test_all_attribute_values_are_strings() -> None:
    attribute_values = canonical_event_attributes(make_event()).values()

    assert all(isinstance(value, str) for value in attribute_values)


def test_content_type_attribute_is_application_json() -> None:
    assert canonical_event_attributes(make_event())["content_type"] == MESSAGE_CONTENT_TYPE


def test_attributes_are_derived_from_event() -> None:
    event = make_event()
    attrs = canonical_event_attributes(event)

    assert attrs["event_id"] == str(event.event_id)
    assert attrs["event_type"] == event.event_type.value
    assert attrs["source_provider"] == event.source.provider


def test_payload_is_not_placed_into_attributes() -> None:
    attrs = canonical_event_attributes(make_event())

    assert "payload" not in attrs
    assert "status" not in attrs
    assert "on_time_delivery_pct" not in attrs


def test_endpoint_query_string_is_not_placed_into_attributes() -> None:
    attrs = canonical_event_attributes(make_event(source_endpoint="synthetic://source?debug=true"))

    assert "endpoint" not in attrs
    assert "debug" not in " ".join(attrs.values()).lower()


def test_none_strings_are_not_produced_in_attributes() -> None:
    assert "None" not in canonical_event_attributes(make_event()).values()


def test_source_event_id_is_not_duplicated_into_attributes() -> None:
    attrs = canonical_event_attributes(make_event())

    assert "source_event_id" not in attrs
    assert "supplier-snapshot-001" not in attrs.values()


def test_publisher_uses_correct_topic_path() -> None:
    client = FakePublisherClient()
    publisher = PubSubCanonicalEventPublisher(
        PubSubTopicConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=client,
    )

    publisher.publish(make_event())

    assert client.published_topic == "projects/supplychain-local/topics/canonical-events-v1"


def test_publisher_sends_deterministic_data_bytes() -> None:
    client = FakePublisherClient()
    event = make_event()

    PubSubCanonicalEventPublisher(
        PubSubTopicConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=client,
    ).publish(event)

    assert client.published_data == serialize_canonical_event(event)


def test_publisher_sends_derived_attributes() -> None:
    client = FakePublisherClient()
    event = make_event()

    PubSubCanonicalEventPublisher(
        PubSubTopicConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=client,
    ).publish(event)

    assert client.published_attrs == canonical_event_attributes(event)


def test_publisher_waits_for_acknowledgement_with_finite_timeout() -> None:
    future = FakeFuture()

    PubSubCanonicalEventPublisher(
        PubSubTopicConfig(project_id=LOCAL_PUBSUB_PROJECT_ID, publish_ack_timeout_seconds=3.5),
        client=FakePublisherClient(future=future),
    ).publish(make_event())

    assert future.received_timeout == 3.5


def test_successful_publish_returns_message_id() -> None:
    receipt = PubSubCanonicalEventPublisher(
        PubSubTopicConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=FakePublisherClient(future=FakeFuture(message_id="transport-123")),
    ).publish(make_event())

    assert receipt.message_id == "transport-123"


def test_receipt_preserves_event_id_separately_from_message_id() -> None:
    event = make_event()
    receipt = PubSubCanonicalEventPublisher(
        PubSubTopicConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=FakePublisherClient(future=FakeFuture(message_id="transport-123")),
    ).publish(event)

    assert receipt.event_id == event.event_id
    assert receipt.message_id != str(event.event_id)


def test_publish_acknowledgement_timeout_maps_to_project_error() -> None:
    publisher = PubSubCanonicalEventPublisher(
        PubSubTopicConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=FakePublisherClient(future=FakeFuture(timeout=True)),
    )

    with pytest.raises(MessagePublishTimeoutError) as exc_info:
        publisher.publish(make_event())

    assert "payload" not in str(exc_info.value).lower()


def test_google_publish_failure_maps_to_project_error() -> None:
    publisher = PubSubCanonicalEventPublisher(
        PubSubTopicConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=FakePublisherClient(
            publish_error=GoogleAPICallError("transport failed"),  # type: ignore[no-untyped-call]
        ),
    )

    with pytest.raises(MessagePublishError) as exc_info:
        publisher.publish(make_event())

    assert exc_info.value.topic_id == CANONICAL_EVENTS_TOPIC_ID


def test_raw_event_body_does_not_appear_in_publish_error_text() -> None:
    publisher = PubSubCanonicalEventPublisher(
        PubSubTopicConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=FakePublisherClient(
            publish_error=GoogleAPICallError("transport failed"),  # type: ignore[no-untyped-call]
        ),
    )

    with pytest.raises(MessagePublishError) as exc_info:
        publisher.publish(make_event())

    assert "on_time_delivery_pct" not in str(exc_info.value)
    assert "supplier-snapshot-001" not in str(exc_info.value)


def test_publish_api_does_not_accept_arbitrary_contradictory_attributes() -> None:
    signature = inspect.signature(PubSubCanonicalEventPublisher.publish)

    assert list(signature.parameters) == ["self", "event"]


def test_missing_local_emulator_configuration_blocks_bootstrap() -> None:
    with pytest.raises(LocalPubSubEmulatorConfigurationError):
        ensure_local_pubsub_emulator_topic(
            config=LocalPubSubEmulatorConfig.from_environment({}),
            client=FakePublisherClient(),
        )


def test_bootstrap_creates_absent_topic() -> None:
    client = FakePublisherClient(topic_exists=False)

    result = ensure_local_pubsub_emulator_topic(
        config=LocalPubSubEmulatorConfig(
            emulator_host="127.0.0.1:8085",
            project_id=LOCAL_PUBSUB_PROJECT_ID,
        ),
        client=client,
    )

    assert result.created is True
    assert client.create_topic_requests == [
        {"name": "projects/supplychain-local/topics/canonical-events-v1"}
    ]


def test_bootstrap_handles_existing_topic_idempotently() -> None:
    client = FakePublisherClient(topic_exists=True)

    result = ensure_local_pubsub_emulator_topic(
        config=LocalPubSubEmulatorConfig(
            emulator_host="localhost:8085",
            project_id=LOCAL_PUBSUB_PROJECT_ID,
        ),
        client=client,
    )

    assert result.created is False
    assert client.create_topic_requests == []


def test_bootstrap_handles_create_already_exists_idempotently() -> None:
    client = FakePublisherClient(topic_exists=False, create_already_exists=True)

    result = ensure_local_pubsub_emulator_topic(
        config=LocalPubSubEmulatorConfig(
            emulator_host="[::1]:8085",
            project_id=LOCAL_PUBSUB_PROJECT_ID,
        ),
        client=client,
    )

    assert result.created is False


def test_bootstrap_targets_canonical_topic_id() -> None:
    result = ensure_local_pubsub_emulator_topic(
        config=LocalPubSubEmulatorConfig(
            emulator_host="127.0.0.1:8085",
            project_id=LOCAL_PUBSUB_PROJECT_ID,
        ),
        client=FakePublisherClient(),
    )

    assert result.topic_id == CANONICAL_EVENTS_TOPIC_ID
    assert result.topic_path == "projects/supplychain-local/topics/canonical-events-v1"


def test_bootstrap_cannot_target_real_cloud_fallback() -> None:
    with pytest.raises(LocalPubSubEmulatorConfigurationError):
        ensure_local_pubsub_emulator_topic(
            config=LocalPubSubEmulatorConfig(
                emulator_host="pubsub.googleapis.com:443",
                project_id="real-project",
            ),
            client=FakePublisherClient(),
        )


def test_canonical_subscription_id_is_approved_topology_value() -> None:
    assert CANONICAL_EVENTS_SUBSCRIPTION_ID == "canonical-events-processing-v1"


def test_subscription_targets_canonical_topic() -> None:
    publisher_client = FakePublisherClient()
    subscriber_client = FakeSubscriberClient(subscription_exists=False)

    result = ensure_local_pubsub_emulator_topology(
        config=LocalPubSubEmulatorConfig(
            emulator_host="127.0.0.1:8085",
            project_id=LOCAL_PUBSUB_PROJECT_ID,
        ),
        publisher_client=publisher_client,
        subscriber_client=subscriber_client,
    )

    assert result.subscription_id == CANONICAL_EVENTS_SUBSCRIPTION_ID
    assert subscriber_client.create_subscription_requests[0]["topic"] == result.topic_path


def test_absent_subscription_is_created() -> None:
    subscriber_client = FakeSubscriberClient(subscription_exists=False)

    result = ensure_local_pubsub_emulator_topology(
        config=LocalPubSubEmulatorConfig(
            emulator_host="127.0.0.1:8085",
            project_id=LOCAL_PUBSUB_PROJECT_ID,
        ),
        publisher_client=FakePublisherClient(),
        subscriber_client=subscriber_client,
    )

    assert result.subscription_created is True
    assert subscriber_client.create_subscription_requests[0]["name"] == (
        "projects/supplychain-local/subscriptions/canonical-events-processing-v1"
    )


def test_existing_correct_subscription_is_idempotent() -> None:
    subscriber_client = FakeSubscriberClient(subscription_exists=True)

    result = ensure_local_pubsub_emulator_topology(
        config=LocalPubSubEmulatorConfig(
            emulator_host="127.0.0.1:8085",
            project_id=LOCAL_PUBSUB_PROJECT_ID,
        ),
        publisher_client=FakePublisherClient(),
        subscriber_client=subscriber_client,
    )

    assert result.subscription_created is False
    assert result.dead_letter_subscription_created is False
    assert subscriber_client.create_subscription_requests == []


def test_existing_subscription_with_unexpected_topic_is_recreated_locally() -> None:
    subscriber_client = FakeSubscriberClient(
        subscription_topic="projects/other/topics/wrong",
    )

    result = ensure_local_pubsub_emulator_topology(
        config=LocalPubSubEmulatorConfig(
            emulator_host="127.0.0.1:8085",
            project_id=LOCAL_PUBSUB_PROJECT_ID,
        ),
        publisher_client=FakePublisherClient(),
        subscriber_client=subscriber_client,
    )

    assert result.subscription_recreated is True
    assert subscriber_client.delete_subscription_requests == [
        {"subscription": "projects/supplychain-local/subscriptions/canonical-events-processing-v1"}
    ]
    assert subscriber_client.create_subscription_requests[0]["topic"] == result.topic_path


def test_existing_subscription_without_dead_letter_policy_is_recreated_locally() -> None:
    subscriber_client = FakeSubscriberClient(dead_letter_policy=None)

    result = ensure_local_pubsub_emulator_topology(
        config=LocalPubSubEmulatorConfig(
            emulator_host="127.0.0.1:8085",
            project_id=LOCAL_PUBSUB_PROJECT_ID,
        ),
        publisher_client=FakePublisherClient(),
        subscriber_client=subscriber_client,
    )

    assert result.subscription_recreated is True
    assert subscriber_client.delete_subscription_requests != []


def test_absent_dead_letter_inspection_subscription_is_created() -> None:
    subscriber_client = FakeSubscriberClient(dead_letter_subscription_exists=False)

    result = ensure_local_pubsub_emulator_topology(
        config=LocalPubSubEmulatorConfig(
            emulator_host="127.0.0.1:8085",
            project_id=LOCAL_PUBSUB_PROJECT_ID,
        ),
        publisher_client=FakePublisherClient(),
        subscriber_client=subscriber_client,
    )

    assert result.dead_letter_subscription_created is True
    assert result.dead_letter_subscription_recreated is False
    assert subscriber_client.create_subscription_requests[-1] == {
        "name": (
            "projects/supplychain-local/subscriptions/canonical-events-dead-letter-inspection-v1"
        ),
        "topic": "projects/supplychain-local/topics/canonical-events-dead-letter-v1",
        "ack_deadline_seconds": DEFAULT_ACK_DEADLINE_SECONDS,
    }


def test_dead_letter_inspection_subscription_targets_dead_letter_topic() -> None:
    subscriber_client = FakeSubscriberClient(dead_letter_subscription_exists=False)

    result = ensure_local_pubsub_emulator_topology(
        config=LocalPubSubEmulatorConfig(
            emulator_host="127.0.0.1:8085",
            project_id=LOCAL_PUBSUB_PROJECT_ID,
        ),
        publisher_client=FakePublisherClient(),
        subscriber_client=subscriber_client,
    )

    assert result.dead_letter_subscription_id == CANONICAL_EVENTS_DEAD_LETTER_SUBSCRIPTION_ID
    assert result.dead_letter_subscription_path == (
        "projects/supplychain-local/subscriptions/canonical-events-dead-letter-inspection-v1"
    )
    assert subscriber_client.create_subscription_requests[-1]["topic"] == (
        "projects/supplychain-local/topics/canonical-events-dead-letter-v1"
    )


def test_existing_dead_letter_inspection_subscription_is_idempotent() -> None:
    subscriber_client = FakeSubscriberClient(dead_letter_subscription_exists=True)

    result = ensure_local_pubsub_emulator_topology(
        config=LocalPubSubEmulatorConfig(
            emulator_host="127.0.0.1:8085",
            project_id=LOCAL_PUBSUB_PROJECT_ID,
        ),
        publisher_client=FakePublisherClient(),
        subscriber_client=subscriber_client,
    )

    assert result.dead_letter_subscription_created is False
    assert result.dead_letter_subscription_recreated is False


def test_dead_letter_inspection_subscription_with_unexpected_topic_is_recreated_locally() -> None:
    subscriber_client = FakeSubscriberClient(
        dead_letter_subscription_topic="projects/other/topics/wrong-dlq",
    )

    result = ensure_local_pubsub_emulator_topology(
        config=LocalPubSubEmulatorConfig(
            emulator_host="127.0.0.1:8085",
            project_id=LOCAL_PUBSUB_PROJECT_ID,
        ),
        publisher_client=FakePublisherClient(),
        subscriber_client=subscriber_client,
    )

    assert result.dead_letter_subscription_recreated is True
    assert subscriber_client.delete_subscription_requests[-1] == {
        "subscription": (
            "projects/supplychain-local/subscriptions/canonical-events-dead-letter-inspection-v1"
        )
    }
    assert subscriber_client.create_subscription_requests[-1]["topic"] == (
        "projects/supplychain-local/topics/canonical-events-dead-letter-v1"
    )


def test_topology_bootstrap_remains_blocked_without_emulator_config() -> None:
    with pytest.raises(LocalPubSubEmulatorConfigurationError):
        ensure_local_pubsub_emulator_topology(
            config=LocalPubSubEmulatorConfig.from_environment({}),
            publisher_client=FakePublisherClient(),
            subscriber_client=FakeSubscriberClient(),
        )


def test_subscription_bootstrap_configures_native_dead_letter_policy_only() -> None:
    subscriber_client = FakeSubscriberClient(subscription_exists=False)

    ensure_local_pubsub_emulator_topology(
        config=LocalPubSubEmulatorConfig(
            emulator_host="127.0.0.1:8085",
            project_id=LOCAL_PUBSUB_PROJECT_ID,
        ),
        publisher_client=FakePublisherClient(),
        subscriber_client=subscriber_client,
    )

    request = subscriber_client.create_subscription_requests[0]
    assert request["ack_deadline_seconds"] == DEFAULT_ACK_DEADLINE_SECONDS
    assert request["dead_letter_policy"] == {
        "dead_letter_topic": "projects/supplychain-local/topics/canonical-events-dead-letter-v1",
        "max_delivery_attempts": PUBSUB_DEAD_LETTER_MAX_DELIVERY_ATTEMPTS,
    }
    assert "retry_policy" not in request
    assert "enable_exactly_once_delivery" not in request
    assert "enable_message_ordering" not in request
    assert "filter" not in request


def test_topology_bootstrap_reports_dead_letter_configuration() -> None:
    result = ensure_local_pubsub_emulator_topology(
        config=LocalPubSubEmulatorConfig(
            emulator_host="127.0.0.1:8085",
            project_id=LOCAL_PUBSUB_PROJECT_ID,
        ),
        publisher_client=FakePublisherClient(),
        subscriber_client=FakeSubscriberClient(subscription_exists=False),
    )

    assert result.dead_letter_topic_id == CANONICAL_EVENTS_DEAD_LETTER_TOPIC_ID
    assert result.dead_letter_topic_path == (
        "projects/supplychain-local/topics/canonical-events-dead-letter-v1"
    )
    assert result.dead_letter_max_delivery_attempts == PUBSUB_DEAD_LETTER_MAX_DELIVERY_ATTEMPTS


def test_valid_serialized_canonical_event_deserializes() -> None:
    event = make_event()

    assert deserialize_canonical_event(serialize_canonical_event(event)) == event


def test_invalid_utf8_deserialization_fails_safely() -> None:
    with pytest.raises(MessageDeserializationError):
        deserialize_canonical_event(b"\xff")


def test_malformed_json_deserialization_fails_safely() -> None:
    with pytest.raises(MessageDeserializationError):
        deserialize_canonical_event(b"{")


def test_invalid_canonical_event_json_fails_safely() -> None:
    with pytest.raises(MessageDeserializationError):
        deserialize_canonical_event(b'{"not":"an event"}')


def test_deserialization_does_not_use_attributes() -> None:
    event = deserialize_canonical_event(serialize_canonical_event(make_event()))

    assert event.event_type is EventType.SUPPLIER_OPERATIONAL_SNAPSHOT_RECORDED


def test_serialization_to_deserialization_preserves_contract_values() -> None:
    event = make_event()
    round_tripped = deserialize_canonical_event(serialize_canonical_event(event))

    assert round_tripped.model_dump(mode="json") == event.model_dump(mode="json")


def test_valid_publisher_attributes_match_body() -> None:
    event = make_event()

    validate_canonical_event_attributes(event=event, attributes=canonical_event_attributes(event))


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("event_id", "c0a2a352-67b8-4dc6-863e-c3e5d45b8c36"),
        ("event_type", "seismic.event.detected"),
        ("schema_version", "9.9.9"),
        ("source_provider", "other-provider"),
        ("deduplication_key", "bad-dedup-key"),
        ("correlation_id", "corr-other"),
        ("producer", "other-producer"),
        ("producer_version", "9.9.9"),
        ("content_type", "text/plain"),
    ],
)
def test_standard_attribute_mismatch_is_rejected(attribute: str, value: str) -> None:
    event = make_event()
    attrs = canonical_event_attributes(event)
    attrs[attribute] = value

    with pytest.raises(MessageAttributeMismatchError) as exc_info:
        validate_canonical_event_attributes(event=event, attributes=attrs)

    assert exc_info.value.attribute == attribute


def test_missing_standard_attribute_is_rejected() -> None:
    event = make_event()
    attrs = canonical_event_attributes(event)
    del attrs["content_type"]

    with pytest.raises(MessageAttributeMismatchError):
        validate_canonical_event_attributes(event=event, attributes=attrs)


def test_extra_transport_attributes_do_not_enter_canonical_event() -> None:
    event = make_event()
    attrs = canonical_event_attributes(event)
    attrs["extra"] = "ignored"
    message = make_received_message(event=event, attributes=attrs)

    received = PubSubCanonicalEventConsumer(
        PubSubSubscriptionConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=FakeSubscriberClient(received_messages=[message]),
    ).pull(max_messages=1)

    assert received[0].event == event
    assert "extra" not in received[0].event.model_dump(mode="json")


def test_pull_uses_correct_canonical_subscription_path() -> None:
    client = FakeSubscriberClient()

    PubSubCanonicalEventConsumer(
        PubSubSubscriptionConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=client,
    ).pull(max_messages=1)

    assert client.pull_requests[0]["subscription"] == (
        "projects/supplychain-local/subscriptions/canonical-events-processing-v1"
    )


def test_pull_passes_configured_max_messages() -> None:
    client = FakeSubscriberClient()

    PubSubCanonicalEventConsumer(
        PubSubSubscriptionConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=client,
    ).pull(max_messages=7)

    assert client.pull_requests[0]["max_messages"] == 7


def test_pull_uses_finite_rpc_timeout() -> None:
    client = FakeSubscriberClient()

    PubSubCanonicalEventConsumer(
        PubSubSubscriptionConfig(project_id=LOCAL_PUBSUB_PROJECT_ID, pull_timeout_seconds=4.0),
        client=client,
    ).pull(max_messages=1)

    assert client.pull_timeouts == [4.0]


def test_pull_rejects_invalid_inputs() -> None:
    consumer = PubSubCanonicalEventConsumer(
        PubSubSubscriptionConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=FakeSubscriberClient(),
    )

    with pytest.raises(ValueError):
        consumer.pull(max_messages=0)
    with pytest.raises(ValueError):
        consumer.pull(max_messages=1, timeout_seconds=0)


def test_zero_pulled_messages_returns_empty_tuple() -> None:
    received = PubSubCanonicalEventConsumer(
        PubSubSubscriptionConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=FakeSubscriberClient(),
    ).pull(max_messages=1)

    assert received == ()


def test_one_valid_message_becomes_received_canonical_event() -> None:
    received = PubSubCanonicalEventConsumer(
        PubSubSubscriptionConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=FakeSubscriberClient(received_messages=[make_received_message()]),
    ).pull(max_messages=1)

    assert len(received) == 1
    assert received[0].event == make_event()


def test_multiple_valid_messages_preserve_receive_order() -> None:
    first = make_received_message(message_id="message-1", ack_id="ack-1")
    second = make_received_message(message_id="message-2", ack_id="ack-2")

    received = PubSubCanonicalEventConsumer(
        PubSubSubscriptionConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=FakeSubscriberClient(received_messages=[first, second]),
    ).pull(max_messages=2)

    assert [item.message_id for item in received] == ["message-1", "message-2"]


def test_transport_message_id_and_ack_id_are_preserved() -> None:
    received = PubSubCanonicalEventConsumer(
        PubSubSubscriptionConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=FakeSubscriberClient(
            received_messages=[make_received_message(message_id="msg-123", ack_id="ack-123")]
        ),
    ).pull(max_messages=1)

    assert received[0].message_id == "msg-123"
    assert received[0].ack_id == "ack-123"


def test_canonical_event_id_remains_separate_from_transport_message_id() -> None:
    received = PubSubCanonicalEventConsumer(
        PubSubSubscriptionConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=FakeSubscriberClient(
            received_messages=[make_received_message(message_id="transport-123")]
        ),
    ).pull(max_messages=1)

    assert str(received[0].event.event_id) != received[0].message_id


def test_pull_failure_maps_to_project_error() -> None:
    consumer = PubSubCanonicalEventConsumer(
        PubSubSubscriptionConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=FakeSubscriberClient(
            pull_error=GoogleAPICallError("pull failed"),  # type: ignore[no-untyped-call]
        ),
    )

    with pytest.raises(MessagePullError):
        consumer.pull(max_messages=1)


def test_public_pull_api_does_not_return_raw_google_messages() -> None:
    received = PubSubCanonicalEventConsumer(
        PubSubSubscriptionConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=FakeSubscriberClient(received_messages=[make_received_message()]),
    ).pull(max_messages=1)

    assert all(not isinstance(item, FakeReceivedMessage) for item in received)


def test_pull_does_not_automatically_acknowledge() -> None:
    client = FakeSubscriberClient(received_messages=[make_received_message()])

    PubSubCanonicalEventConsumer(
        PubSubSubscriptionConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=client,
    ).pull(max_messages=1)

    assert client.acknowledge_requests == []


def test_explicit_acknowledge_uses_correct_ack_id() -> None:
    client = FakeSubscriberClient(received_messages=[make_received_message(ack_id="ack-123")])
    consumer = PubSubCanonicalEventConsumer(
        PubSubSubscriptionConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=client,
    )
    received = consumer.pull(max_messages=1)

    consumer.acknowledge(received)

    assert client.acknowledge_requests[0]["ack_ids"] == ["ack-123"]


def test_acknowledging_multiple_messages_uses_unique_ack_ids() -> None:
    client = FakeSubscriberClient(
        received_messages=[
            make_received_message(message_id="msg-1", ack_id="ack-1"),
            make_received_message(message_id="msg-2", ack_id="ack-2"),
            make_received_message(message_id="msg-3", ack_id="ack-2"),
        ]
    )
    consumer = PubSubCanonicalEventConsumer(
        PubSubSubscriptionConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=client,
    )

    consumer.acknowledge(consumer.pull(max_messages=3))

    assert client.acknowledge_requests[0]["ack_ids"] == ["ack-1", "ack-2"]


def test_acknowledgement_failure_maps_to_project_error() -> None:
    client = FakeSubscriberClient(
        received_messages=[make_received_message()],
        acknowledge_error=GoogleAPICallError("ack failed"),  # type: ignore[no-untyped-call]
    )
    consumer = PubSubCanonicalEventConsumer(
        PubSubSubscriptionConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=client,
    )

    with pytest.raises(MessageAcknowledgeError):
        consumer.acknowledge(consumer.pull(max_messages=1))


def test_acknowledgement_does_not_alter_canonical_event() -> None:
    client = FakeSubscriberClient(received_messages=[make_received_message()])
    consumer = PubSubCanonicalEventConsumer(
        PubSubSubscriptionConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=client,
    )
    received = consumer.pull(max_messages=1)
    before = received[0].event

    consumer.acknowledge(received)

    assert received[0].event == before


def test_empty_acknowledgement_is_noop() -> None:
    client = FakeSubscriberClient()

    PubSubCanonicalEventConsumer(
        PubSubSubscriptionConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=client,
    ).acknowledge(())

    assert client.acknowledge_requests == []


def test_redelivery_request_sets_ack_deadline_to_zero() -> None:
    client = FakeSubscriberClient(received_messages=[make_received_message(ack_id="ack-123")])
    consumer = PubSubCanonicalEventConsumer(
        PubSubSubscriptionConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=client,
    )

    consumer.request_redelivery(consumer.pull(max_messages=1))

    assert client.nack_requests[0]["ack_deadline_seconds"] == 0
    assert client.nack_requests[0]["ack_ids"] == ["ack-123"]


def test_redelivery_failure_maps_to_project_error() -> None:
    client = FakeSubscriberClient(
        received_messages=[make_received_message()],
        nack_error=GoogleAPICallError("nack failed"),  # type: ignore[no-untyped-call]
    )
    consumer = PubSubCanonicalEventConsumer(
        PubSubSubscriptionConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=client,
    )

    with pytest.raises(MessageRedeliveryRequestError):
        consumer.request_redelivery(consumer.pull(max_messages=1))


def test_redelivery_request_contains_no_processing_retry_policy() -> None:
    client = FakeSubscriberClient(received_messages=[make_received_message()])
    consumer = PubSubCanonicalEventConsumer(
        PubSubSubscriptionConfig(project_id=LOCAL_PUBSUB_PROJECT_ID),
        client=client,
    )

    consumer.request_redelivery(consumer.pull(max_messages=1))

    assert "retry_policy" not in client.nack_requests[0]
