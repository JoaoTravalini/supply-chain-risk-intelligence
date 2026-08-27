"""Public processing semantics for SupplyChain Sentinel."""

from supplychain.processing.coordinator import (
    CanonicalEventHandler,
    CoordinatorOutcome,
    MessageAcknowledger,
    ProcessingCoordinator,
    ProcessingCoordinatorResult,
)
from supplychain.processing.decisions import (
    ProcessedEventRecord,
    ProcessingAssessment,
    ProcessingConsistencyError,
    ProcessingDecision,
    ProcessingError,
    assess_event,
)
from supplychain.processing.failures import (
    NonRetryableProcessingError,
    ProcessingFailure,
    ProcessingFailureKind,
    ProcessingHandlerError,
    RetryableProcessingError,
    classify_processing_exception,
    classify_revision_conflict,
)
from supplychain.processing.fingerprints import (
    SOURCE_CONTENT_FINGERPRINT_ALGORITHM,
    generate_source_content_fingerprint,
)
from supplychain.processing.ledger import (
    PROCESSED_EVENTS_TABLE,
    SQLITE_LEDGER_SCHEMA_VERSION,
    ProcessedLedgerRecord,
    ProcessingLedger,
    ProcessingResolution,
    ProcessingResolutionResult,
    SqliteProcessingLedger,
)
from supplychain.processing.revisions import SourceRevision, extract_source_revision

__all__ = [
    "PROCESSED_EVENTS_TABLE",
    "SOURCE_CONTENT_FINGERPRINT_ALGORITHM",
    "SQLITE_LEDGER_SCHEMA_VERSION",
    "CanonicalEventHandler",
    "CoordinatorOutcome",
    "MessageAcknowledger",
    "NonRetryableProcessingError",
    "ProcessedEventRecord",
    "ProcessedLedgerRecord",
    "ProcessingAssessment",
    "ProcessingConsistencyError",
    "ProcessingCoordinator",
    "ProcessingCoordinatorResult",
    "ProcessingDecision",
    "ProcessingError",
    "ProcessingFailure",
    "ProcessingFailureKind",
    "ProcessingHandlerError",
    "ProcessingLedger",
    "ProcessingResolution",
    "ProcessingResolutionResult",
    "RetryableProcessingError",
    "SourceRevision",
    "SqliteProcessingLedger",
    "assess_event",
    "classify_processing_exception",
    "classify_revision_conflict",
    "extract_source_revision",
    "generate_source_content_fingerprint",
]
