from __future__ import annotations

import io
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest
from google.cloud import bigquery
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from supplychain.agent.data import (
    AgentBigQueryConfig,
    GuardedBigQueryReader,
    QueryBudgetExceededError,
    _QuerySpec,
)
from supplychain.agent.errors import InvestigationModelError
from supplychain.agent.llm import GeminiInvestigationModel, GeminiInvestigationModelConfig
from supplychain.agent.models import (
    HumanReviewDecision,
    HumanReviewRecord,
    HumanReviewStatus,
    InvestigationSnapshot,
    InvestigationStatus,
    SubmitHumanReviewRequest,
    snapshot_to_state,
)
from supplychain.agent.reports import EvidenceFinding, InvestigationReport
from supplychain.agent.service import InvestigationService
from supplychain.agent.validation import InvestigationReportValidator
from supplychain.contracts import CanonicalEvent, EventMetadata, EventType, SourceMetadata
from supplychain.messaging import (
    PubSubCanonicalEventPublisher,
    PubSubTopicConfig,
    ReceivedCanonicalEvent,
)
from supplychain.observability import (
    ObservabilityConfig,
    ObservabilityContext,
    ObservabilityRuntime,
    bind_observability_context,
    current_observability_context,
)
from supplychain.observability.runtime import JsonLogFormatter
from supplychain.processing import (
    CanonicalEventHandler,
    MessageAcknowledger,
    ProcessingCoordinator,
    ProcessingLedger,
    ProcessingResolution,
    ProcessingResolutionResult,
)
from supplychain.risk import RiskFactorFamily, RiskLevel, SupplierRiskAssessment
from supplychain.risk.models import StructuralRiskBreakdown

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
INVESTIGATION_ID = UUID("11111111-1111-4111-8111-111111111111")
THREAD_ID = UUID("22222222-2222-4222-8222-222222222222")
SENSITIVE_SENTINELS = (
    "sk-test-secret",
    "postgresql://user:password@localhost/db",
    "SYSTEM_PROMPT_SENTINEL",
    "SELECT * FROM supplychain_raw.secret",
    "PROVIDER_RESPONSE_BODY_SENTINEL",
    "EVIDENCE_PAYLOAD_SENTINEL",
)


@dataclass(frozen=True, slots=True)
class RuntimeHarness:
    runtime: ObservabilityRuntime
    span_exporter: InMemorySpanExporter
    metric_reader: InMemoryMetricReader
    log_stream: io.StringIO


class FakeQueryJob:
    def __init__(
        self,
        *,
        rows: Sequence[Mapping[str, object]] = (),
        total_bytes_processed: int = 0,
    ) -> None:
        self.rows = tuple(rows)
        self.total_bytes_processed = total_bytes_processed

    def result(self, timeout: float | None = None) -> object:
        _ = timeout
        return self.rows


@dataclass(frozen=True, slots=True)
class QueryCall:
    query: str
    job_config: bigquery.QueryJobConfig


class FakeBigQueryClient:
    def __init__(self, jobs: Sequence[FakeQueryJob]) -> None:
        self.jobs = list(jobs)
        self.calls: list[QueryCall] = []
        self.closed = False

    def query(self, query: str, *, job_config: object) -> FakeQueryJob:
        self.calls.append(
            QueryCall(query=query, job_config=cast(bigquery.QueryJobConfig, job_config))
        )
        return self.jobs.pop(0)

    def close(self) -> None:
        self.closed = True


class FakeFuture:
    def result(self, timeout: float | None = None) -> str:
        _ = timeout
        return "message-001"


class FakePublisherClient:
    def __init__(self) -> None:
        self.published_data: bytes | None = None

    def topic_path(self, project: str, topic: str) -> str:
        return f"projects/{project}/topics/{topic}"

    def publish(self, topic: str, data: bytes, **attrs: str) -> FakeFuture:
        _ = topic, attrs
        self.published_data = data
        return FakeFuture()

    def get_topic(self, request: Mapping[str, str]) -> object:
        _ = request
        return object()

    def create_topic(self, request: Mapping[str, str]) -> object:
        _ = request
        return object()

    def stop(self) -> None:
        return None


class FakeLedger:
    def assess(self, event: CanonicalEvent) -> ProcessingResolutionResult:
        return ProcessingResolutionResult(
            resolution=ProcessingResolution.NEW,
            deduplication_key=event.metadata.deduplication_key,
            source_content_fingerprint="sha256:test",
        )

    def record_success(self, event: CanonicalEvent) -> ProcessingResolutionResult:
        return ProcessingResolutionResult(
            resolution=ProcessingResolution.NEW,
            deduplication_key=event.metadata.deduplication_key,
            source_content_fingerprint="sha256:test",
        )

    def get_record(self, deduplication_key: str) -> object:
        _ = deduplication_key
        return None

    def close(self) -> None:
        return None


class FakeHandler:
    def handle(self, event: CanonicalEvent) -> None:
        _ = event


class FakeAcknowledger:
    def acknowledge(self, received_messages: tuple[ReceivedCanonicalEvent, ...]) -> None:
        _ = received_messages


class FakeGeminiClient:
    class Models:
        def generate_content(self, *, model: str, contents: str, config: object) -> object:
            _ = model, contents, config
            return type(
                "FakeResponse",
                (),
                {
                    "parsed": {
                        "executive_summary": "A safe summary.",
                        "key_drivers": ("Structural exposure.",),
                        "evidence_findings": (),
                        "uncertainties": ("No environmental evidence.",),
                        "recommendations": ("Monitor sourcing options.",),
                    }
                },
            )()

    models = Models()


class SentinelProviderError(Exception):
    status_code = 404

    def __str__(self) -> str:
        return " ".join(SENSITIVE_SENTINELS)


class FailingGeminiClient:
    class Models:
        def generate_content(self, *, model: str, contents: str, config: object) -> object:
            _ = model, contents, config
            raise SentinelProviderError()

    models = Models()


class FakeInvestigationContext:
    prompt_version = "test"

    def model_dump(self, *, mode: str) -> dict[str, object]:
        _ = mode
        return {"supplier_id": "SUP-000001"}


class FakeStateSnapshot:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values


class FakeReviewGraph:
    def __init__(self, current: InvestigationSnapshot) -> None:
        self.current = current

    def get_state(self, config: Mapping[str, object]) -> FakeStateSnapshot:
        _ = config
        return FakeStateSnapshot(cast(dict[str, Any], snapshot_to_state(self.current)))

    def invoke(self, input: object, config: Mapping[str, object]) -> dict[str, Any]:
        _ = input, config
        reviewed = self.current.model_copy(
            update={
                "human_review_status": HumanReviewStatus.APPROVED,
                "human_review": HumanReviewRecord(
                    status=HumanReviewStatus.APPROVED,
                    reviewer_id="reviewer-001",
                    reviewed_at=NOW,
                ),
            }
        )
        return cast(dict[str, Any], snapshot_to_state(reviewed))


def test_context_nesting_cleanup_and_exception_restoration() -> None:
    assert current_observability_context() == ObservabilityContext()

    with bind_observability_context(request_id="outer", investigation_id=INVESTIGATION_ID):
        assert current_observability_context().request_id == "outer"
        with (
            pytest.raises(RuntimeError),
            bind_observability_context(
                request_id="inner",
                thread_id=THREAD_ID,
            ),
        ):
            assert current_observability_context().request_id == "inner"
            assert current_observability_context().thread_id == str(THREAD_ID)
            raise RuntimeError("boom")
        restored = current_observability_context()
        assert restored.request_id == "outer"
        assert restored.thread_id is None

    assert current_observability_context() == ObservabilityContext()
    with bind_observability_context(generate_request_id=True) as context:
        assert context.request_id is not None


def test_structured_logs_are_json_safe_and_trace_correlated() -> None:
    harness = runtime_harness()
    with (
        bind_observability_context(
            request_id="request-001",
            correlation_id="corr-001",
        ),
        harness.runtime.span("supplychain.test", attributes={"operation": "test"}),
    ):
        harness.runtime.log_event(
            "test.event",
            component="test",
            outcome="success",
            fields={
                "operation": "safe_operation",
                "provider_model": "gemini-2.5-flash",
                "sql": SENSITIVE_SENTINELS[3],
                "prompt": SENSITIVE_SENTINELS[2],
            },
        )

    payload = json.loads(harness.log_stream.getvalue())
    assert payload["event"] == "test.event"
    assert payload["severity"] == "INFO"
    assert payload["component"] == "test"
    assert payload["request_id"] == "request-001"
    assert payload["correlation_id"] == "corr-001"
    assert "trace_id" in payload
    assert "span_id" in payload
    assert payload["timestamp"].endswith("+00:00")
    assert_no_sentinels(harness.log_stream.getvalue())


def test_metrics_record_bounded_attributes_and_exclude_high_cardinality_ids() -> None:
    harness = runtime_harness()
    harness.runtime.record_operation(
        component="agent",
        operation="run",
        outcome="success",
        duration_ms=7.0,
        attributes={
            "supplier_id": "SUP-000001",
            "request_id": "request-001",
            "investigation_id": str(INVESTIGATION_ID),
            "review_id": "review-001",
            "review_decision": "APPROVE",
        },
    )

    attributes = metric_attributes(harness.metric_reader)
    assert_has_metric_attributes(
        attributes,
        component="agent",
        operation="run",
        outcome="success",
    )
    for item in attributes:
        assert "supplier_id" not in item
        assert "request_id" not in item
        assert "investigation_id" not in item
        assert "review_id" not in item


def test_guarded_bigquery_read_records_spans_metrics_and_budget_rejection() -> None:
    harness = runtime_harness()
    query = _QuerySpec(
        name="test_bigquery_read",
        sql="SELECT 1",
        parameters=(),
        max_result_rows=1,
    )
    client = FakeBigQueryClient(
        (
            FakeQueryJob(total_bytes_processed=12),
            FakeQueryJob(rows=({"value": 1},), total_bytes_processed=12),
        )
    )
    cfg = AgentBigQueryConfig(project_id="supplychain-local", max_bytes_billed=100)
    reader = GuardedBigQueryReader(cfg, client=client, observability=harness.runtime)

    assert reader.read(query) == ({"value": 1},)

    span_names = [span.name for span in harness.span_exporter.get_finished_spans()]
    assert "supplychain.bigquery.read" in span_names
    assert {"component": "bigquery", "operation": "test_bigquery_read", "outcome": "success"} in (
        metric_attributes(harness.metric_reader)
    )
    assert_no_sentinels(harness.log_stream.getvalue())

    rejected = runtime_harness()
    rejected_client = FakeBigQueryClient((FakeQueryJob(total_bytes_processed=101),))
    rejected_reader = GuardedBigQueryReader(
        AgentBigQueryConfig(project_id="supplychain-local", max_bytes_billed=100),
        client=rejected_client,
        observability=rejected.runtime,
    )

    with pytest.raises(QueryBudgetExceededError):
        rejected_reader.read(query)

    assert len(rejected_client.calls) == 1
    assert rejected_client.calls[0].job_config.dry_run
    assert_has_metric_attributes(
        metric_attributes(rejected.metric_reader),
        component="bigquery",
        operation="test_bigquery_read",
        outcome="budget_rejected",
    )


def test_model_boundary_records_safe_provider_failure_without_sentinels() -> None:
    harness = runtime_harness()
    model = GeminiInvestigationModel(
        GeminiInvestigationModelConfig(api_key="test-key", model_name="gemini-2.5-flash"),
        client=FailingGeminiClient(),
        observability=harness.runtime,
    )

    with pytest.raises(InvestigationModelError):
        model.analyze(cast(Any, FakeInvestigationContext()))

    span = harness.span_exporter.get_finished_spans()[0]
    assert span.name == "supplychain.investigation.model"
    assert_has_metric_attributes(
        metric_attributes(harness.metric_reader),
        component="investigation_model",
        operation="gemini_generate_content",
        outcome="failure",
        error_category="MODEL_NOT_FOUND",
        provider_model="gemini-2.5-flash",
    )
    assert_no_sentinels(harness.log_stream.getvalue())
    assert_no_sentinels(json.dumps(dict(span.attributes or {})))


def test_validation_processing_pubsub_and_hitl_create_stable_spans() -> None:
    harness = runtime_harness()

    InvestigationReportValidator(observability=harness.runtime).validate(
        report=investigation_report(),
        current_risk=risk_assessment(),
        evidence=(),
        supplier_id="SUP-000001",
        investigation_id=INVESTIGATION_ID,
        thread_id=THREAD_ID,
        expected_thread_id=THREAD_ID,
    )

    event = canonical_event()
    coordinator = ProcessingCoordinator(
        ledger=cast(ProcessingLedger, FakeLedger()),
        handler=cast(CanonicalEventHandler, FakeHandler()),
        acknowledger=cast(MessageAcknowledger, FakeAcknowledger()),
        observability=harness.runtime,
    )
    coordinator.process(
        ReceivedCanonicalEvent(event=event, message_id="message-001", ack_id="ack-001")
    )

    publisher = PubSubCanonicalEventPublisher(
        PubSubTopicConfig(project_id="supplychain-local", topic_id="canonical-events-v1"),
        client=FakePublisherClient(),
        observability=harness.runtime,
    )
    publisher.publish(event)

    graph = FakeReviewGraph(pending_snapshot())
    service = InvestigationService(
        checkpointer=cast(Any, object()),
        graph=cast(Any, graph),
        investigation_graph=cast(Any, graph),
        observability=harness.runtime,
    )
    service.submit_review(
        SubmitHumanReviewRequest(
            investigation_id=INVESTIGATION_ID,
            thread_id=THREAD_ID,
            decision=HumanReviewDecision.APPROVE,
            reviewer_id="reviewer-001",
            reviewed_at=NOW,
        )
    )

    names = {span.name for span in harness.span_exporter.get_finished_spans()}
    assert "supplychain.investigation.validate" in names
    assert "supplychain.event.process" in names
    assert "supplychain.pubsub.publish" in names
    assert "supplychain.review.submit" in names
    attributes = metric_attributes(harness.metric_reader)
    assert any(item.get("processing_decision") == "new" for item in attributes)
    assert any(item.get("review_decision") == "APPROVE" for item in attributes)
    for item in attributes:
        assert "event_id" not in item
        assert "thread_id" not in item
        assert "investigation_id" not in item


def test_observability_diagnostics_are_configuration_not_health() -> None:
    runtime = ObservabilityRuntime(ObservabilityConfig(service_name="sentinel", environment="test"))

    diagnostics = runtime.diagnostics()

    assert diagnostics.service_name == "sentinel"
    assert diagnostics.environment == "test"
    assert diagnostics.external_telemetry_exporter_configured is False
    assert diagnostics.tracing_enabled
    assert diagnostics.metrics_enabled


def test_metric_recording_failure_isolated_from_business_path() -> None:
    runtime = ObservabilityRuntime(ObservabilityConfig(service_name="sentinel", environment="test"))
    cast(Any, runtime)._operation_counter = BrokenCounter()

    runtime.record_operation(
        component="test",
        operation="safe_operation",
        outcome="success",
        duration_ms=1.0,
    )


class BrokenCounter:
    def add(self, amount: int, *, attributes: Mapping[str, object]) -> None:
        _ = amount, attributes
        raise RuntimeError("telemetry failure")


def runtime_harness() -> RuntimeHarness:
    span_exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    metric_reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[metric_reader])
    log_stream = io.StringIO()
    logger = logging.getLogger(f"supplychain-test-{id(log_stream)}")
    logger.handlers = []
    logger.propagate = False
    runtime = ObservabilityRuntime(
        ObservabilityConfig(service_name="supplychain-test", environment="test"),
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        logger=logger,
    )
    handler = logging.StreamHandler(log_stream)
    handler.setFormatter(JsonLogFormatter(runtime))
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    return RuntimeHarness(
        runtime=runtime,
        span_exporter=span_exporter,
        metric_reader=metric_reader,
        log_stream=log_stream,
    )


def metric_attributes(reader: InMemoryMetricReader) -> list[dict[str, object]]:
    data = reader.get_metrics_data()
    attributes: list[dict[str, object]] = []
    if data is None:
        return attributes
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                points = getattr(metric.data, "data_points", ())
                for point in points:
                    attributes.append(dict(point.attributes))
    return attributes


def assert_no_sentinels(value: str) -> None:
    for sentinel in SENSITIVE_SENTINELS:
        assert sentinel not in value


def assert_has_metric_attributes(
    attributes: list[dict[str, object]],
    **expected: object,
) -> None:
    assert any(
        all(item.get(key) == value for key, value in expected.items()) for item in attributes
    )


def canonical_event() -> CanonicalEvent:
    return CanonicalEvent.model_validate(
        {
            "event_type": EventType.WEATHER_OBSERVATION_RECORDED,
            "event_time": NOW,
            "ingested_at": NOW,
            "source": SourceMetadata(
                provider="synthetic-weather",
                source_event_id="weather-001",
            ),
            "payload": {"safe": True},
            "metadata": EventMetadata(
                correlation_id="corr-001",
                producer="test",
                producer_version="1.0.0",
                deduplication_key="a" * 64,
            ),
        }
    )


def risk_assessment() -> SupplierRiskAssessment:
    return SupplierRiskAssessment(
        supplier_id="SUP-000001",
        assessed_at=NOW,
        risk_score=41.83,
        risk_level=RiskLevel.MEDIUM,
        structural_score=83.66,
        weather_score=0.0,
        seismic_score=0.0,
        structural=StructuralRiskBreakdown(
            criticality_component=1.0,
            dependency_component=0.85,
            single_source_component=1.0,
            lead_time_component=0.19,
        ),
        relevant_weather_event_count=0,
        relevant_seismic_event_count=0,
        evidence_deduplication_keys=(),
        dominant_factor=RiskFactorFamily.STRUCTURAL,
    )


def investigation_report() -> InvestigationReport:
    risk = risk_assessment()
    return InvestigationReport(
        investigation_id=INVESTIGATION_ID,
        supplier_id=risk.supplier_id,
        generated_at=NOW,
        risk_score=risk.risk_score,
        risk_level=risk.risk_level,
        risk_model_version=risk.model_version,
        structural_score=risk.structural_score,
        weather_score=risk.weather_score,
        seismic_score=risk.seismic_score,
        dominant_factor=risk.dominant_factor,
        factor_scores=risk.structural,
        executive_summary="Structural risk is elevated.",
        key_drivers=("Single-source exposure.",),
        evidence_findings=(EvidenceFinding(finding="No evidence cited.", evidence_keys=()),),
        uncertainties=("No environmental evidence is attached.",),
        recommendations=("Monitor alternate sourcing.",),
        evidence_deduplication_keys_used=(),
    )


def pending_snapshot() -> InvestigationSnapshot:
    return InvestigationSnapshot(
        investigation_id=INVESTIGATION_ID,
        thread_id=THREAD_ID,
        supplier_id="SUP-000001",
        question="What should operations monitor?",
        status=InvestigationStatus.COMPLETED,
        created_at=NOW,
        updated_at=NOW,
        report=investigation_report(),
        human_review_status=HumanReviewStatus.PENDING,
        human_review=HumanReviewRecord(status=HumanReviewStatus.PENDING),
    )
