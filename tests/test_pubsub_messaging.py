from __future__ import annotations

import inspect
import json
from collections.abc import Mapping
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import UTC, datetime
from typing import ClassVar
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
    CANONICAL_EVENTS_TOPIC_ID,
    LOCAL_PUBSUB_PROJECT_ID,
    MESSAGE_CONTENT_TYPE,
    LocalPubSubEmulatorConfig,
    LocalPubSubEmulatorConfigurationError,
    MessagePublishError,
    MessagePublishTimeoutError,
    PubSubCanonicalEventPublisher,
    PubSubTopicConfig,
    canonical_event_attributes,
    ensure_local_pubsub_emulator_topic,
    is_loopback_emulator_host,
    serialize_canonical_event,
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
