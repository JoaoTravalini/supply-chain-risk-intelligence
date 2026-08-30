"""Public agent runtime boundary for SupplyChain Sentinel."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from supplychain.agent.data import (
        AGENT_BIGQUERY_MAX_BYTES_BILLED_ENV,
        DEFAULT_AGENT_BIGQUERY_MAX_BYTES_BILLED,
        DEFAULT_RISK_HISTORY_LIMIT,
        MAX_EVIDENCE_KEYS,
        MAX_RISK_HISTORY_LIMIT,
        SUPPLYCHAIN_GCP_PROJECT_ID_ENV,
        AgentBigQueryConfig,
        AgentDataConfigurationError,
        AgentDataError,
        AgentDataIntegrityError,
        AgentDataNotFoundError,
        AgentDataQueryError,
        AgentDataService,
        GuardedBigQueryReader,
        QueryBudgetExceededError,
        RiskEvidenceInput,
        RiskHistoryInput,
        SupplierLookupInput,
        agent_bigquery_config_from_env,
        agent_data_service_from_env,
        approved_agent_data_tools,
    )
    from supplychain.agent.errors import (
        AgentConfigurationError,
        AgentError,
        AgentPersistenceError,
        InvestigationNotFoundError,
    )
    from supplychain.agent.graph import build_investigation_graph
    from supplychain.agent.models import (
        CreateInvestigationRequest,
        InvestigationIdentity,
        InvestigationSnapshot,
        InvestigationState,
        InvestigationStatus,
    )
    from supplychain.agent.persistence import AGENT_POSTGRES_DSN_ENV
    from supplychain.agent.service import InvestigationService, thread_config

__all__ = [
    "AGENT_BIGQUERY_MAX_BYTES_BILLED_ENV",
    "AGENT_POSTGRES_DSN_ENV",
    "DEFAULT_AGENT_BIGQUERY_MAX_BYTES_BILLED",
    "DEFAULT_RISK_HISTORY_LIMIT",
    "MAX_EVIDENCE_KEYS",
    "MAX_RISK_HISTORY_LIMIT",
    "SUPPLYCHAIN_GCP_PROJECT_ID_ENV",
    "AgentBigQueryConfig",
    "AgentConfigurationError",
    "AgentDataConfigurationError",
    "AgentDataError",
    "AgentDataIntegrityError",
    "AgentDataNotFoundError",
    "AgentDataQueryError",
    "AgentDataService",
    "AgentError",
    "AgentPersistenceError",
    "CreateInvestigationRequest",
    "GuardedBigQueryReader",
    "InvestigationIdentity",
    "InvestigationNotFoundError",
    "InvestigationService",
    "InvestigationSnapshot",
    "InvestigationState",
    "InvestigationStatus",
    "QueryBudgetExceededError",
    "RiskEvidenceInput",
    "RiskHistoryInput",
    "SupplierLookupInput",
    "agent_bigquery_config_from_env",
    "agent_data_service_from_env",
    "approved_agent_data_tools",
    "build_investigation_graph",
    "thread_config",
]


def __getattr__(name: str) -> Any:
    """Load public agent symbols lazily to keep module entrypoints clean."""

    if name in {
        "AGENT_BIGQUERY_MAX_BYTES_BILLED_ENV",
        "DEFAULT_AGENT_BIGQUERY_MAX_BYTES_BILLED",
        "DEFAULT_RISK_HISTORY_LIMIT",
        "MAX_EVIDENCE_KEYS",
        "MAX_RISK_HISTORY_LIMIT",
        "SUPPLYCHAIN_GCP_PROJECT_ID_ENV",
        "AgentBigQueryConfig",
        "AgentDataConfigurationError",
        "AgentDataError",
        "AgentDataIntegrityError",
        "AgentDataNotFoundError",
        "AgentDataQueryError",
        "AgentDataService",
        "GuardedBigQueryReader",
        "QueryBudgetExceededError",
        "RiskEvidenceInput",
        "RiskHistoryInput",
        "SupplierLookupInput",
        "agent_bigquery_config_from_env",
        "agent_data_service_from_env",
        "approved_agent_data_tools",
    }:
        from supplychain.agent import data

        return getattr(data, name)
    if name in {
        "AgentConfigurationError",
        "AgentError",
        "AgentPersistenceError",
        "InvestigationNotFoundError",
    }:
        from supplychain.agent import errors

        return getattr(errors, name)
    if name == "build_investigation_graph":
        from supplychain.agent.graph import build_investigation_graph

        return build_investigation_graph
    if name in {
        "CreateInvestigationRequest",
        "InvestigationIdentity",
        "InvestigationSnapshot",
        "InvestigationState",
        "InvestigationStatus",
    }:
        from supplychain.agent import models

        return getattr(models, name)
    if name == "AGENT_POSTGRES_DSN_ENV":
        from supplychain.agent.persistence import AGENT_POSTGRES_DSN_ENV

        return AGENT_POSTGRES_DSN_ENV
    if name in {"InvestigationService", "thread_config"}:
        from supplychain.agent import service

        return getattr(service, name)
    raise AttributeError(f"module 'supplychain.agent' has no attribute {name!r}")
