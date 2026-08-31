# Evidence-Grounded Investigation Workflow

Stage 15 connects the durable LangGraph runtime to guarded BigQuery reads and a
Gemini model provider so Supplier risk investigations can produce structured,
evidence-grounded reports.

Status: implementation complete, with live Gemini provider validation externally
blocked. Offline validation is complete, and the full integration path reached
the Gemini boundary through guarded BigQuery reads, LangGraph, and PostgreSQL.
An independent minimal text-only Gemini diagnostic reproduced the provider/key
capability blocker without Supplier or project context. Live provider validation
must be repeated once provider/key capability is restored.

## Workflow

The implemented graph is deliberately bounded:

```text
START
-> initialize_investigation
-> load_supplier_context
-> load_risk_context
-> load_risk_history
-> load_evidence
-> analyze_investigation
-> finalize_investigation
-> END
```

`create_investigation` remains the Stage 13 compatibility path and creates a
`READY` checkpoint. `run_investigation` executes the Stage 15 workflow and
persists either `COMPLETED` with an `InvestigationReport` or `FAILED` with safe
failure metadata.

## Authoritative Data Sources

The workflow retrieves authoritative data through `AgentDataService`:

- Supplier profile from `supplychain_core.suppliers`.
- Current risk from `supplychain_mart.supplier_risk_current`.
- Bounded risk history from `supplychain_mart.supplier_risk_history`.
- Evidence from `supplychain_core.canonical_events`.

The workflow does not read RAW, expose arbitrary SQL, instantiate a raw
BigQuery client, or call `SupplierRiskEngine.assess`.

## Model Boundary

The graph depends on the provider-neutral `InvestigationModel` abstraction.
`GeminiInvestigationModel` is the Google Gen AI SDK implementation, created
behind explicit configuration and never at import time.

Default provider settings:

- SDK: `google-genai`.
- Model: `gemini-2.5-flash`.
- Prompt version: `investigation-v1`.
- Temperature: `0.0`.
- Max output tokens: `1200`.
- Application timeout: `30` seconds. The Google Gen AI SDK boundary converts
  this value to milliseconds before constructing SDK HTTP options.

Gemini receives bounded structured context only. It does not receive SQL,
database clients, query templates, credentials, or tool access.

## Prompt Responsibilities

The `investigation-v1` system instruction tells the model to analyze
supply-chain risk evidence, preserve authoritative risk values, treat retrieved
data and user text as untrusted content, cite only provided evidence
identifiers, state uncertainty, avoid invented source data, and keep
recommendations advisory.

Supplier names, locations, user questions, provider place strings, and payload
text are placed in structured context fields rather than concatenated into the
system instruction.

## Structured Report

Gemini may generate only `InvestigationAnalysis` fields:

- `executive_summary`
- `key_drivers`
- `evidence_findings`
- `uncertainties`
- `recommendations`

Application code constructs the final `InvestigationReport` by combining those
validated generated fields with authoritative MART fields:

- `risk_score`
- `risk_level`
- `risk_model_version`
- `structural_score`
- `weather_score`
- `seismic_score`
- `dominant_factor`
- `factor_scores`
- `evidence_deduplication_keys_used`

The model has no output field capable of replacing authoritative risk values.

## Evidence Grounding

Evidence identity uses Canonical Event `metadata.deduplication_key` values that
come from the authoritative current MART assessment. The workflow retrieves
those keys through `AgentDataService.get_risk_evidence`.

Every evidence key cited by Gemini is validated against the evidence actually
retrieved for the investigation. Unknown evidence keys fail the investigation
with safe `FAILED` metadata rather than being silently accepted.

## Zero-Evidence Behavior

A current assessment may contain zero environmental evidence. That is valid.
The workflow still succeeds when the model returns no evidence citations. The
model context explicitly marks `zero_evidence = true`, allowing the analysis to
discuss structural risk and uncertainty without fabricating weather or seismic
evidence.

## Context Bounds

The context builder enforces conservative defaults:

- Question length: `2000` characters.
- Evidence events sent to the model: `20`.
- Individual text fields: `500` characters.
- Per-evidence payload representation: `2000` bytes.
- Total serialized model context: `20000` bytes.

Transport metadata such as request IDs, correlation IDs, delivery IDs, and
warehouse SQL are not included in model context.

## Failure Semantics

Retrieval, context, model, and output-validation failures persist `FAILED`
state with a safe code and message. Persisted errors must not include API keys,
PostgreSQL DSNs, SQL text, prompts, full context, full provider responses, or
credential-bearing metadata.

Provider failures may also persist a bounded diagnostic category, provider
exception class name, and safe status/code when those are available from
structured exception metadata. Raw provider exceptions, response bodies, prompts,
and context are never checkpointed.

Stage 15 uses zero automatic model-output repair attempts. Invalid structured
output fails closed so the workflow does not spend an additional provider call
or risk accepting evidence citations produced outside the first validated
contract response. A later evaluation stage may introduce an explicit bounded
repair policy.

No fake report is produced on failure.

## Persistence

The final state is persisted through the existing LangGraph checkpoint
integration. A completed checkpoint can be retrieved by `thread_id` after a
service/checkpointer reconstruction. Stage 13 `CREATED`, `READY`, and `FAILED`
checkpoint shapes remain readable because Stage 15 fields are optional.

## Security

Metadata, examples, prompts, and errors must not include credentials, API keys,
authorization headers, DSNs, personal information, or provider raw responses.
Recommendations are advisory only; the workflow does not contact suppliers,
modify procurement systems, write BigQuery records, send messages, or perform
autonomous actions.
