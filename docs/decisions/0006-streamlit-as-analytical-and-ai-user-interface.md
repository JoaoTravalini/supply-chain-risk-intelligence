# ADR 0006: Streamlit as Analytical and AI User Interface

## Status

Accepted

## Context

The project needs a practical portfolio interface for supplier-risk analytics and evidence-grounded AI investigation. The UI should support dashboards, supplier profiles, event visibility, and investigation workflows without becoming the primary engineering focus.

## Decision

Streamlit will be the analytical and AI user interface.

The intended application areas are Overview, Suppliers, Events, and AI Investigation.

## Consequences

- Streamlit will be used for the future user-facing analytical workflow.
- UI implementation is deferred until the planned product stage.
- Application code should still respect system boundaries and avoid embedding domain logic directly in UI components.
- The UI should present deterministic risk outputs separately from LLM-generated explanations.
