"""Application-owned logging, tracing, and metrics runtime."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from opentelemetry import trace
from opentelemetry.metrics import Counter, Histogram, Meter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import Span, Status, StatusCode, Tracer
from opentelemetry.util.types import AttributeValue

from supplychain.observability.context import current_observability_context

SUPPLYCHAIN_SERVICE_NAME_ENV = "SUPPLYCHAIN_SERVICE_NAME"
SUPPLYCHAIN_ENVIRONMENT_ENV = "SUPPLYCHAIN_ENVIRONMENT"
SUPPLYCHAIN_LOG_LEVEL_ENV = "SUPPLYCHAIN_LOG_LEVEL"
SUPPLYCHAIN_OBSERVABILITY_ENABLED_ENV = "SUPPLYCHAIN_OBSERVABILITY_ENABLED"

DEFAULT_SERVICE_NAME = "supplychain-sentinel"
DEFAULT_ENVIRONMENT = "development"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_SERVICE_VERSION = "0.1.0"

HIGH_CARDINALITY_METRIC_ATTRIBUTES = frozenset(
    {
        "request_id",
        "correlation_id",
        "event_id",
        "investigation_id",
        "thread_id",
        "supplier_id",
        "review_id",
    }
)
SAFE_LOG_FIELDS = frozenset(
    {
        "operation",
        "outcome",
        "error_category",
        "exception_class",
        "status_code",
        "provider_model",
        "validation_outcome",
        "validation_failure_code",
        "review_decision",
        "processing_decision",
        "component",
        "estimated_bytes",
        "maximum_bytes_billed",
        "row_count",
    }
)
SAFE_TRACE_FIELDS = SAFE_LOG_FIELDS | frozenset(
    {
        "supplier_id",
        "event_id",
        "investigation_id",
        "thread_id",
    }
)
SAFE_METRIC_FIELDS = frozenset(
    {
        "component",
        "operation",
        "outcome",
        "error_category",
        "review_decision",
        "processing_decision",
        "provider_model",
        "validation_outcome",
        "validation_failure_code",
    }
)


class TelemetryOutcome(StrEnum):
    """Common bounded operation outcomes."""

    SUCCESS = "success"
    FAILURE = "failure"
    BUDGET_REJECTED = "budget_rejected"
    INVALID_TRANSITION = "invalid_transition"


@dataclass(frozen=True, slots=True)
class ObservabilityConfig:
    """Non-secret observability runtime configuration."""

    service_name: str = DEFAULT_SERVICE_NAME
    environment: str = DEFAULT_ENVIRONMENT
    service_version: str = DEFAULT_SERVICE_VERSION
    log_level: str = DEFAULT_LOG_LEVEL
    enabled: bool = True
    structured_logging_enabled: bool = True
    tracing_enabled: bool = True
    metrics_enabled: bool = True
    external_exporter_configured: bool = False

    def __post_init__(self) -> None:
        _require_non_empty("service_name", self.service_name)
        _require_non_empty("environment", self.environment)
        _require_non_empty("service_version", self.service_version)
        _require_non_empty("log_level", self.log_level)


@dataclass(frozen=True, slots=True)
class ObservabilityDiagnostics:
    """Safe configuration snapshot; not a live dependency health probe."""

    service_name: str
    environment: str
    service_version: str
    structured_logging_enabled: bool
    tracing_enabled: bool
    metrics_enabled: bool
    external_telemetry_exporter_configured: bool


class JsonLogFormatter(logging.Formatter):
    """Format standard logging records as one safe JSON object per line."""

    def __init__(self, runtime: ObservabilityRuntime) -> None:
        super().__init__()
        self._runtime = runtime

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "severity": record.levelname,
            "event": getattr(record, "event_name", record.getMessage()),
            "component": getattr(record, "component", "application"),
            "service": self._runtime.config.service_name,
            "environment": self._runtime.config.environment,
        }
        payload.update(current_observability_context().log_fields())
        span = trace.get_current_span()
        span_context = span.get_span_context()
        if span_context.is_valid:
            payload["trace_id"] = format(span_context.trace_id, "032x")
            payload["span_id"] = format(span_context.span_id, "016x")
        safe_fields = getattr(record, "safe_fields", None)
        if isinstance(safe_fields, Mapping):
            payload.update(_safe_mapping(safe_fields, SAFE_LOG_FIELDS))
        if record.exc_info is not None:
            exc_type = record.exc_info[0]
            payload["exception_class"] = exc_type.__name__ if exc_type is not None else "Exception"
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


class ObservabilityRuntime:
    """Own OpenTelemetry providers, instruments, and structured logging helpers."""

    def __init__(
        self,
        config: ObservabilityConfig | None = None,
        *,
        tracer_provider: TracerProvider | None = None,
        meter_provider: MeterProvider | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = ObservabilityConfig() if config is None else config
        resource = Resource.create(
            {
                "service.name": self.config.service_name,
                "service.version": self.config.service_version,
                "deployment.environment": self.config.environment,
                "application.name": "supplychain-sentinel",
            }
        )
        self.tracer_provider = tracer_provider or TracerProvider(resource=resource)
        self.meter_provider = meter_provider or MeterProvider(resource=resource)
        self.tracer: Tracer = self.tracer_provider.get_tracer("supplychain.observability")
        self.meter: Meter = self.meter_provider.get_meter("supplychain.observability")
        self.logger = logger or logging.getLogger("supplychain")
        self._operation_counter: Counter | None = None
        self._operation_duration: Histogram | None = None
        self._bigquery_estimated_bytes: Histogram | None = None
        self._bigquery_rows: Histogram | None = None
        if self.config.enabled and self.config.metrics_enabled:
            self._operation_counter = self.meter.create_counter("supplychain.operation.count")
            self._operation_duration = self.meter.create_histogram(
                "supplychain.operation.duration_ms",
                unit="ms",
            )
            self._bigquery_estimated_bytes = self.meter.create_histogram(
                "supplychain.bigquery.estimated_bytes",
                unit="By",
            )
            self._bigquery_rows = self.meter.create_histogram(
                "supplychain.bigquery.returned_rows",
                unit="1",
            )

    @classmethod
    def disabled(cls) -> ObservabilityRuntime:
        """Return an isolated no-op runtime for tests or constrained environments."""

        return cls(
            ObservabilityConfig(
                enabled=False,
                structured_logging_enabled=False,
                tracing_enabled=False,
                metrics_enabled=False,
            )
        )

    def diagnostics(self) -> ObservabilityDiagnostics:
        """Return safe observability configuration diagnostics."""

        return ObservabilityDiagnostics(
            service_name=self.config.service_name,
            environment=self.config.environment,
            service_version=self.config.service_version,
            structured_logging_enabled=(
                self.config.enabled and self.config.structured_logging_enabled
            ),
            tracing_enabled=self.config.enabled and self.config.tracing_enabled,
            metrics_enabled=self.config.enabled and self.config.metrics_enabled,
            external_telemetry_exporter_configured=self.config.external_exporter_configured,
        )

    def configure_structured_logging(self) -> None:
        """Configure this runtime's logger for stdout JSON logs."""

        if not self.config.enabled or not self.config.structured_logging_enabled:
            return
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonLogFormatter(self))
        self.logger.handlers = [handler]
        self.logger.setLevel(_log_level(self.config.log_level))
        self.logger.propagate = False

    @contextmanager
    def span(
        self,
        name: str,
        *,
        attributes: Mapping[str, object] | None = None,
    ) -> Iterator[Span | None]:
        """Create a stable OpenTelemetry span, isolated from telemetry failures."""

        if not self.config.enabled or not self.config.tracing_enabled:
            yield None
            return
        safe_attributes = self._trace_attributes(attributes or {})
        safe_attributes.update(current_observability_context().log_fields())
        try:
            span_context = self.tracer.start_as_current_span(name, attributes=safe_attributes)
        except Exception:
            yield None
            return
        with span_context as span:
            yield span

    def log_event(
        self,
        event_name: str,
        *,
        component: str,
        outcome: str | None = None,
        fields: Mapping[str, object] | None = None,
        level: int = logging.INFO,
        exc: BaseException | None = None,
    ) -> None:
        """Emit one bounded structured log record."""

        if not self.config.enabled or not self.config.structured_logging_enabled:
            return
        safe_fields = dict(_safe_mapping(fields or {}, SAFE_LOG_FIELDS))
        if outcome is not None:
            safe_fields["outcome"] = outcome
        try:
            self.logger.log(
                level,
                event_name,
                exc_info=(type(exc), exc, exc.__traceback__) if exc is not None else None,
                extra={
                    "event_name": event_name,
                    "component": component,
                    "safe_fields": safe_fields,
                },
            )
        except Exception:
            return

    def record_operation(
        self,
        *,
        component: str,
        operation: str,
        outcome: str,
        duration_ms: float,
        attributes: Mapping[str, object] | None = None,
    ) -> None:
        """Record bounded operation count and duration metrics."""

        if not self.config.enabled or not self.config.metrics_enabled:
            return
        metric_attributes = self._metric_attributes(
            {
                "component": component,
                "operation": operation,
                "outcome": outcome,
                **dict(attributes or {}),
            }
        )
        try:
            if self._operation_counter is not None:
                self._operation_counter.add(1, attributes=metric_attributes)
            if self._operation_duration is not None:
                self._operation_duration.record(max(duration_ms, 0.0), attributes=metric_attributes)
        except Exception:
            return

    def record_bigquery_read(
        self,
        *,
        operation: str,
        outcome: str,
        estimated_bytes: int | None,
        maximum_bytes_billed: int,
        row_count: int | None,
        duration_ms: float,
        error_category: str | None = None,
    ) -> None:
        """Record bounded BigQuery read metrics."""

        attributes: dict[str, object] = {
            "component": "bigquery",
            "operation": operation,
            "outcome": outcome,
        }
        if error_category is not None:
            attributes["error_category"] = error_category
        self.record_operation(
            component="bigquery",
            operation=operation,
            outcome=outcome,
            duration_ms=duration_ms,
            attributes=attributes,
        )
        metric_attributes = self._metric_attributes(attributes)
        try:
            if estimated_bytes is not None and self._bigquery_estimated_bytes is not None:
                self._bigquery_estimated_bytes.record(estimated_bytes, attributes=metric_attributes)
            if row_count is not None and self._bigquery_rows is not None:
                self._bigquery_rows.record(row_count, attributes=metric_attributes)
        except Exception:
            return
        self.log_event(
            "bigquery.read",
            component="bigquery",
            outcome=outcome,
            fields={
                "operation": operation,
                "estimated_bytes": estimated_bytes,
                "maximum_bytes_billed": maximum_bytes_billed,
                "row_count": row_count,
                "error_category": error_category,
            },
        )

    def set_span_status(self, span: Span | None, outcome: str) -> None:
        """Set span status from a bounded operation outcome."""

        if span is None:
            return
        try:
            code = StatusCode.OK if outcome == TelemetryOutcome.SUCCESS else StatusCode.ERROR
            span.set_status(Status(code))
            span.set_attribute("outcome", outcome)
        except Exception:
            return

    def _trace_attributes(self, attributes: Mapping[str, object]) -> dict[str, AttributeValue]:
        return _safe_mapping(attributes, SAFE_TRACE_FIELDS)

    def _metric_attributes(self, attributes: Mapping[str, object]) -> dict[str, AttributeValue]:
        safe = _safe_mapping(attributes, SAFE_METRIC_FIELDS)
        return {
            key: value
            for key, value in safe.items()
            if key not in HIGH_CARDINALITY_METRIC_ATTRIBUTES
        }


def observability_config_from_env() -> ObservabilityConfig:
    """Read non-secret observability configuration from environment variables."""

    return ObservabilityConfig(
        service_name=os.environ.get(SUPPLYCHAIN_SERVICE_NAME_ENV, DEFAULT_SERVICE_NAME),
        environment=os.environ.get(SUPPLYCHAIN_ENVIRONMENT_ENV, DEFAULT_ENVIRONMENT),
        log_level=os.environ.get(SUPPLYCHAIN_LOG_LEVEL_ENV, DEFAULT_LOG_LEVEL),
        enabled=_env_bool(SUPPLYCHAIN_OBSERVABILITY_ENABLED_ENV, default=True),
    )


def elapsed_ms(start: float) -> float:
    """Return elapsed monotonic time in milliseconds."""

    return (time.perf_counter() - start) * 1000


def _safe_mapping(
    values: Mapping[str, object],
    allowed_fields: frozenset[str],
) -> dict[str, AttributeValue]:
    safe: dict[str, AttributeValue] = {}
    for key, value in values.items():
        if key not in allowed_fields or value is None:
            continue
        if isinstance(value, StrEnum):
            safe[key] = value.value
        elif isinstance(value, str | int | float | bool):
            safe[key] = value
    return safe


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _log_level(value: str) -> int:
    level = getattr(logging, value.upper(), logging.INFO)
    return level if isinstance(level, int) else logging.INFO


def _require_non_empty(field_name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
