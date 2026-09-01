"""Resource construction for the Streamlit application."""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from supplychain.agent.data import (
    AgentDataService,
    GuardedBigQueryReader,
    agent_bigquery_config_from_env,
)
from supplychain.agent.llm import gemini_investigation_model_from_env
from supplychain.agent.persistence import PostgresCheckpointStore, checkpoint_store_from_env
from supplychain.agent.service import InvestigationService
from supplychain.observability import ObservabilityRuntime, observability_config_from_env
from supplychain.ui.data import PortfolioDataService, portfolio_data_service_from_env


@dataclass(frozen=True, slots=True)
class StreamlitResources:
    """Long-lived application resources owned by Streamlit cache_resource."""

    portfolio_service: PortfolioDataService
    agent_data_service: AgentDataService
    investigation_service: InvestigationService
    observability: ObservabilityRuntime


@dataclass(frozen=True, slots=True)
class _InvestigationResource:
    """Retain the checkpoint store owner with the cached service."""

    checkpoint_store: PostgresCheckpointStore
    service: InvestigationService


@st.cache_resource(show_spinner=False)
def portfolio_service_resource() -> PortfolioDataService:
    """Return a cached guarded portfolio data service."""

    return portfolio_data_service_from_env(observability_runtime_resource())


@st.cache_resource(show_spinner=False)
def agent_data_service_resource() -> AgentDataService:
    """Return a cached guarded agent data service for supplier drill-downs."""

    config = agent_bigquery_config_from_env()
    runtime = observability_runtime_resource()
    return AgentDataService(config, reader=GuardedBigQueryReader(config, observability=runtime))


@st.cache_resource(show_spinner=False)
def investigation_service_resource() -> InvestigationService:
    """Return a cached investigation service without probing Gemini."""

    return _investigation_resource().service


@st.cache_resource(show_spinner=False)
def _investigation_resource() -> _InvestigationResource:
    """Return cached investigation resources with owned checkpoint lifecycle."""

    checkpoint_store = checkpoint_store_from_env()
    checkpoint_store.__enter__()
    service = InvestigationService(
        checkpointer=checkpoint_store.checkpointer,
        data_service=agent_data_service_resource(),
        model=gemini_investigation_model_from_env(observability=observability_runtime_resource()),
        observability=observability_runtime_resource(),
    )
    return _InvestigationResource(checkpoint_store=checkpoint_store, service=service)


@st.cache_resource(show_spinner=False)
def observability_runtime_resource() -> ObservabilityRuntime:
    """Return the cached application-owned observability runtime."""

    runtime = ObservabilityRuntime(observability_config_from_env())
    runtime.configure_structured_logging()
    return runtime


def resources_from_cache() -> StreamlitResources:
    """Return cached production resources for normal app execution."""

    return StreamlitResources(
        portfolio_service=portfolio_service_resource(),
        agent_data_service=agent_data_service_resource(),
        investigation_service=investigation_service_resource(),
        observability=observability_runtime_resource(),
    )
