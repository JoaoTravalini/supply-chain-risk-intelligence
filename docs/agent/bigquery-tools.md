# Guarded BigQuery Agent Data Access

Stage 14 introduces the read-only BigQuery data boundary that future LangGraph
investigation nodes and a future LLM-facing tool layer will use.

The security rule is simple: future LLM output is untrusted, so LLM or user text
does not become SQL.

```text
LLM or UI
-> approved typed operation
-> validated parameters
-> static SQL catalog
-> dry-run cost check
-> maximum_bytes_billed
-> BigQuery CORE / MART
```

There is no arbitrary SQL API.

## Approved Operations

The Stage 14 service exposes exactly these operations:

- `get_supplier_profile`
- `get_current_supplier_risk`
- `get_supplier_risk_history`
- `get_risk_evidence`

The operations read only these approved objects:

- `supplychain_core.suppliers`
- `supplychain_core.canonical_events`
- `supplychain_mart.supplier_risk_current`
- `supplychain_mart.supplier_risk_history`

RAW is intentionally not exposed to agent-facing tools. RAW remains an
audit/replay/history layer.

## Query Catalog

SQL templates live in `src/supplychain/agent/sql/` and are owned by the
application. Callers cannot provide table names, dataset names, column names,
SQL fragments, predicates, orderings, expressions, or complete SQL strings.

All dynamic values use BigQuery query parameters. All queries are Standard SQL
with `use_legacy_sql = False`.

## Cost Controls

The default per-query budget is:

```text
100 * 1024 * 1024 bytes
```

This is exposed as `DEFAULT_AGENT_BIGQUERY_MAX_BYTES_BILLED` and may be
configured with `SUPPLYCHAIN_AGENT_BIGQUERY_MAX_BYTES_BILLED`.

Every non-empty query performs a BigQuery dry run before real execution. The
dry run disables query cache for estimation and reads `total_bytes_processed`.
If the estimate is greater than the configured budget, the actual query is not
submitted.

The actual query also sets `maximum_bytes_billed`, so BigQuery independently
enforces the same ceiling.

These controls reduce exposure but are not a zero-cost guarantee and do not
replace production billing controls.

## Result Bounds

The service enforces expected cardinality after execution:

- Supplier profile: zero or one row; duplicates fail integrity validation.
- Current risk: zero or one row; duplicates fail integrity validation.
- Risk history: ordered by `assessed_at DESC`; default limit `20`, maximum
  `100`.
- Evidence lookup: maximum `50` distinct deduplication keys.

Empty evidence input returns an empty collection without issuing a BigQuery
query.

## Typed Contracts

Inputs are strict Pydantic models:

- `SupplierLookupInput`
- `RiskHistoryInput`
- `RiskEvidenceInput`

Outputs are existing validated contracts where possible:

- `Supplier`
- `SupplierRiskAssessment`
- `CanonicalEvent`

Stage 14 does not convert structured data into prose. Explanation and
recommendation generation are deferred.

## Evidence Semantics

Risk evidence lookup uses Canonical Event `deduplication_key` values stored in
authoritative MART risk assessments. It does not use Pub/Sub message IDs,
acknowledgement IDs, event IDs, delivery attempts, or recomputed geographic
relevance.

Evidence results are ordered deterministically by `event_time ASC,
deduplication_key ASC` and mapped back to validated `CanonicalEvent` instances.

## Risk Authority

`get_current_supplier_risk` reads from
`supplychain_mart.supplier_risk_current`. It does not invoke
`SupplierRiskEngine.assess(...)`.

The deterministic Stage 12 risk engine remains the authoritative calculator.
The BigQuery tools retrieve authoritative data and evidence. A future LLM may
interpret and explain retrieved facts, but it must not calculate or overwrite
authoritative risk.

## Error Safety

Project-owned public query errors do not include full SQL text, payload dumps,
credentials, tokens, DSNs, ADC paths, or user questions. Original exceptions are
chained for debugging at the code boundary without widening public messages.

## Deferred

Stage 14 does not add an LLM provider, prompt architecture, full LangGraph
investigation workflow, Streamlit UI, production IAM, or managed production
PostgreSQL.
