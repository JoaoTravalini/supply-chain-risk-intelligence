# Streamlit Application

Stage 17 adds the portfolio-facing Streamlit application for SupplyChain Sentinel. The UI is a presentation and workflow layer over existing application services; it does not reimplement warehouse reads, risk scoring, LangGraph orchestration, or human-review persistence.

## Startup

Run the application from the repository root:

```shell
uv run streamlit run src/supplychain/ui/app.py
```

The app uses the existing project environment configuration for BigQuery reads, PostgreSQL-backed investigation checkpoints, and Gemini-backed investigation generation. Missing configuration is shown as a safe unavailable state rather than a credential-bearing traceback.

## Application Areas

The application contains exactly three primary pages:

- Risk Portfolio: portfolio-level current Supplier risk visibility.
- Supplier Explorer: one-Supplier profile, current deterministic risk, factor decomposition, bounded history, and bounded evidence metadata.
- AI Investigation: explicit investigation execution, generated report display, deterministic validation status, and human review controls.

## Architecture

The Streamlit package is organized under `src/supplychain/ui/`:

- `app.py` renders pages and maps domain/application state into UI controls.
- `data.py` provides the dashboard read service and typed portfolio view models.
- `presentation.py` contains pure formatting and presentation helpers.
- `resources.py` centralizes Streamlit resource caching for long-lived service construction.
- `sql/` contains static dashboard SQL owned by the application.

The UI depends on typed services. It does not import a BigQuery client directly, does not write SQL in page rendering code, does not manipulate LangGraph `Command` objects, and does not write directly to checkpoint storage.

## Dashboard Data Boundary

Portfolio data is read through `PortfolioDataService`, which uses the existing guarded BigQuery reader architecture. Dashboard queries are static, SELECT-only, dry-run before execution, bounded by maximum bytes billed, finite timeout, and explicit result limits.

Dashboard reads use CORE Supplier data and MART Supplier risk data. RAW access is intentionally excluded, and no arbitrary SQL interface is exposed.

## Investigation And Human Review

The AI Investigation page calls `InvestigationService` only after the user explicitly presses `Run investigation`. Streamlit reruns, navigation, filtering, and form rendering do not create investigations.

When an investigation completes, authoritative risk fields remain MART-owned and are displayed separately from AI-generated analysis. The human reviewer can APPROVE or REJECT the generated investigation outcome, but cannot edit Supplier identity, risk score, risk level, model version, factor scores, or evidence source records. Generated recommendations remain advisory text only; Stage 17 does not implement autonomous remediation or action execution.

Review submission uses the Stage 16 service API. The UI does not construct LangGraph resume commands or treat UI session state as the source of review truth.

## Gemini Provider Limitation

The UI does not probe Gemini at startup, does not call `models.list()`, and does not switch models automatically. A real investigation can still fail at the existing provider boundary while the external Gemini provider/key capability blocker remains unresolved. In that case, the UI shows only safe project-owned failure information such as public message, category, and safe status/code. It never displays raw provider responses, prompts, request payloads, stack traces, API keys, or credentials.

## Resource Lifecycle

Streamlit reruns the script frequently. Long-lived resources are constructed through `st.cache_resource` in `resources.py` so BigQuery, agent data, and investigation services are not recreated for every widget interaction. Session state stores UI-level selections and investigation snapshots only; it must not store API keys, DSNs, credentials, complete provider request objects, or raw provider payloads.

## Testing

Default Stage 17 tests are offline, Gemini-free, BigQuery-free, and browser-free. Focused Streamlit tests use `streamlit.testing.v1.AppTest` with deterministic fake services to validate startup, page rendering, unavailable states, explicit investigation execution, safe failure display, pending human review controls, and rerun/idempotency behavior.

Run the normal test suite with:

```shell
uv run pytest
```

The deterministic agent evaluation gate from Stage 16 remains:

```shell
uv run python -m supplychain.agent.evaluation
```

## Security Boundaries

The Streamlit application preserves existing project boundaries:

- no arbitrary SQL;
- no RAW dashboard reads;
- no risk recalculation in the UI or LLM;
- no autonomous action execution;
- no credentials or provider payloads in UI state;
- no raw provider response dumps;
- no system prompt display;
- no direct checkpoint table access;
- no unsafe HTML rendering of model or evidence content.
