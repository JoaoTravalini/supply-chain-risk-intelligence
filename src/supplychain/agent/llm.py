"""Gemini-backed investigation model boundary."""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol, cast

from pydantic import ValidationError

from supplychain.agent.context import InvestigationContext
from supplychain.agent.errors import (
    InvestigationModelConfigurationError,
    InvestigationModelError,
    InvestigationOutputValidationError,
    ProviderFailureCategory,
    ProviderFailureDiagnostic,
)
from supplychain.agent.prompts import INVESTIGATION_SYSTEM_INSTRUCTION
from supplychain.agent.reports import InvestigationAnalysis
from supplychain.observability import ObservabilityRuntime
from supplychain.observability.runtime import TelemetryOutcome, elapsed_ms

GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
SUPPLYCHAIN_GEMINI_MODEL_ENV = "SUPPLYCHAIN_GEMINI_MODEL"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_GEMINI_TEMPERATURE = 0.0
DEFAULT_GEMINI_MAX_OUTPUT_TOKENS = 1_200
DEFAULT_GEMINI_TIMEOUT_SECONDS = 30.0


class InvestigationModel(Protocol):
    """Provider-neutral investigation analysis boundary."""

    def analyze(self, context: InvestigationContext) -> InvestigationAnalysis:
        """Analyze bounded context and return validated generated content."""


@dataclass(frozen=True, slots=True)
class GeminiInvestigationModelConfig:
    """Configuration for Gemini investigation analysis."""

    api_key: str
    model_name: str = DEFAULT_GEMINI_MODEL
    temperature: float = DEFAULT_GEMINI_TEMPERATURE
    max_output_tokens: int = DEFAULT_GEMINI_MAX_OUTPUT_TOKENS
    timeout_seconds: float = DEFAULT_GEMINI_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise InvestigationModelConfigurationError(f"{GEMINI_API_KEY_ENV} must be set")
        if not self.model_name.strip():
            raise InvestigationModelConfigurationError("Gemini model name must not be blank")
        if self.temperature < 0:
            raise InvestigationModelConfigurationError("Gemini temperature must be non-negative")
        if self.max_output_tokens <= 0:
            raise InvestigationModelConfigurationError("Gemini max output tokens must be positive")
        _timeout_milliseconds(self.timeout_seconds)


class GeminiInvestigationModel:
    """Official Google Gen AI SDK implementation of investigation analysis."""

    def __init__(
        self,
        config: GeminiInvestigationModelConfig,
        *,
        client: object | None = None,
        observability: ObservabilityRuntime | None = None,
    ) -> None:
        self._config = config
        self._client = client
        self._provider_calls = 0
        self._observability = observability or ObservabilityRuntime.disabled()

    @property
    def provider_calls(self) -> int:
        """Return the number of provider calls made by this model instance."""

        return self._provider_calls

    def analyze(self, context: InvestigationContext) -> InvestigationAnalysis:
        """Generate and validate structured investigation analysis."""

        client = self._client if self._client is not None else self._build_client()
        request_payload = json.dumps(
            {
                "prompt_version": context.prompt_version,
                "trusted_context": context.model_dump(mode="json"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        started_at = time.perf_counter()
        with self._observability.span(
            "supplychain.investigation.model",
            attributes={
                "component": "investigation_model",
                "operation": "gemini_generate_content",
                "provider_model": self._config.model_name,
            },
        ) as span:
            try:
                response = cast(Any, client).models.generate_content(
                    model=self._config.model_name,
                    contents=request_payload,
                    config=self._generation_config(),
                )
                self._provider_calls += 1
            except Exception as exc:
                diagnostic = classify_provider_failure(exc)
                self._observability.record_operation(
                    component="investigation_model",
                    operation="gemini_generate_content",
                    outcome=TelemetryOutcome.FAILURE,
                    duration_ms=elapsed_ms(started_at),
                    attributes={
                        "provider_model": self._config.model_name,
                        "error_category": diagnostic.category.value,
                    },
                )
                self._observability.log_event(
                    "investigation.model.failure",
                    component="investigation_model",
                    outcome=TelemetryOutcome.FAILURE,
                    fields={
                        "operation": "gemini_generate_content",
                        "provider_model": self._config.model_name,
                        "error_category": diagnostic.category.value,
                        "exception_class": diagnostic.exception_class,
                        "status_code": diagnostic.status_code,
                    },
                )
                self._observability.set_span_status(span, TelemetryOutcome.FAILURE)
                raise InvestigationModelError(
                    "Gemini investigation analysis failed",
                    provider_failure=diagnostic,
                ) from exc
            try:
                analysis = _analysis_from_response(response)
            except InvestigationOutputValidationError:
                self._observability.record_operation(
                    component="investigation_model",
                    operation="gemini_generate_content",
                    outcome=TelemetryOutcome.FAILURE,
                    duration_ms=elapsed_ms(started_at),
                    attributes={
                        "provider_model": self._config.model_name,
                        "error_category": "output_validation",
                    },
                )
                self._observability.set_span_status(span, TelemetryOutcome.FAILURE)
                raise
            self._observability.record_operation(
                component="investigation_model",
                operation="gemini_generate_content",
                outcome=TelemetryOutcome.SUCCESS,
                duration_ms=elapsed_ms(started_at),
                attributes={"provider_model": self._config.model_name},
            )
            self._observability.set_span_status(span, TelemetryOutcome.SUCCESS)
            return analysis

    def _build_client(self) -> object:
        from google import genai
        from google.genai import types

        return genai.Client(
            api_key=self._config.api_key,
            http_options=types.HttpOptions(
                timeout=_timeout_milliseconds(self._config.timeout_seconds)
            ),
        )

    def _generation_config(self) -> object:
        from google.genai import types

        return types.GenerateContentConfig(
            system_instruction=INVESTIGATION_SYSTEM_INSTRUCTION,
            temperature=self._config.temperature,
            max_output_tokens=self._config.max_output_tokens,
            response_mime_type="application/json",
            response_schema=_gemini_response_schema(),
        )


def gemini_config_from_env() -> GeminiInvestigationModelConfig:
    """Read Gemini provider configuration from environment variables."""

    api_key = os.environ.get(GEMINI_API_KEY_ENV)
    if api_key is None or not api_key.strip():
        raise InvestigationModelConfigurationError(f"{GEMINI_API_KEY_ENV} must be set")
    model_name = os.environ.get(SUPPLYCHAIN_GEMINI_MODEL_ENV) or DEFAULT_GEMINI_MODEL
    return GeminiInvestigationModelConfig(api_key=api_key, model_name=model_name)


def gemini_investigation_model_from_env(
    observability: ObservabilityRuntime | None = None,
) -> GeminiInvestigationModel:
    """Create a Gemini-backed investigation model from environment configuration."""

    return GeminiInvestigationModel(gemini_config_from_env(), observability=observability)


def classify_provider_failure(exc: BaseException) -> ProviderFailureDiagnostic:
    """Classify provider failures using safe structured metadata when available."""

    exception_class = type(exc).__name__
    status_code = _safe_status_code(exc)
    category = _category_from_status(status_code) or _category_from_exception_type(exc)
    return ProviderFailureDiagnostic(
        category=category,
        exception_class=exception_class,
        status_code=status_code,
    )


def _analysis_from_response(response: object) -> InvestigationAnalysis:
    parsed = getattr(response, "parsed", None)
    try:
        if parsed is not None:
            return InvestigationAnalysis.model_validate(parsed)
        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Gemini response did not contain JSON text")
        return InvestigationAnalysis.model_validate_json(text)
    except (ValidationError, ValueError) as exc:
        raise InvestigationOutputValidationError("Gemini output failed validation") from exc


def _gemini_response_schema() -> dict[str, Any]:
    """Return the Gemini Developer API-compatible response schema subset."""

    schema = InvestigationAnalysis.model_json_schema()
    _remove_provider_unsupported_schema_keywords(schema)
    return schema


def _remove_provider_unsupported_schema_keywords(value: object) -> None:
    if isinstance(value, dict):
        value.pop("additionalProperties", None)
        for child in value.values():
            _remove_provider_unsupported_schema_keywords(child)
    elif isinstance(value, list):
        for child in value:
            _remove_provider_unsupported_schema_keywords(child)


def _timeout_milliseconds(timeout_seconds: float) -> int:
    if timeout_seconds <= 0 or not math.isfinite(timeout_seconds):
        raise InvestigationModelConfigurationError("Gemini timeout must be positive and finite")
    timeout_ms = round(timeout_seconds * 1000)
    if timeout_ms <= 0:
        raise InvestigationModelConfigurationError("Gemini timeout milliseconds must be positive")
    return timeout_ms


def _safe_status_code(exc: BaseException) -> str | None:
    for attribute in ("status_code", "code", "status"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int | str):
            text = str(value).strip()
            if text:
                return text[:64]
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int | str):
        text = str(value).strip()
        if text:
            return text[:64]
    return None


def _category_from_status(status_code: str | None) -> ProviderFailureCategory | None:
    if status_code is None:
        return None
    normalized = status_code.upper()
    match normalized:
        case "400" | "INVALID_ARGUMENT":
            return ProviderFailureCategory.INVALID_REQUEST
        case "401" | "UNAUTHENTICATED":
            return ProviderFailureCategory.AUTHENTICATION
        case "403" | "PERMISSION_DENIED":
            return ProviderFailureCategory.PERMISSION
        case "404" | "NOT_FOUND":
            return ProviderFailureCategory.MODEL_NOT_FOUND
        case "408" | "504" | "DEADLINE_EXCEEDED":
            return ProviderFailureCategory.TIMEOUT
        case "429":
            return ProviderFailureCategory.RATE_LIMIT
        case "RESOURCE_EXHAUSTED":
            return ProviderFailureCategory.QUOTA
        case _:
            return None


def _category_from_exception_type(exc: BaseException) -> ProviderFailureCategory:
    if isinstance(exc, TimeoutError):
        return ProviderFailureCategory.TIMEOUT
    if isinstance(exc, ConnectionError):
        return ProviderFailureCategory.NETWORK
    if isinstance(exc, (TypeError, ValueError)):
        return ProviderFailureCategory.SDK_CONFIGURATION
    return ProviderFailureCategory.UNKNOWN
