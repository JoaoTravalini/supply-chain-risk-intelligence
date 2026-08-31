# Investigation Validation, Human Review, and Evaluation

Stage 16 adds deterministic validation, native LangGraph human review, and an
offline evaluation harness for SupplyChain Sentinel investigations. It does not
require live Gemini availability.

## Validation Boundary

After an investigation report is produced, application code validates it before
human review. The validator is deterministic and does not use an LLM.

The gate checks:

- Supplier, investigation, and thread identity consistency.
- Exact preservation of MART-owned risk fields: risk score, risk level, model
  version, structural score, weather score, seismic score, dominant factor, and
  factor scores.
- Evidence integrity: every cited evidence key must be among retrieved
  Canonical Event deduplication keys.
- Required generated report sections remain present after Pydantic validation.

Validation failures use bounded project-owned failure codes and do not persist
raw model/provider output.

## Human Review Lifecycle

Human review is separate from `InvestigationStatus`. `COMPLETED` continues to
mean the investigation report was successfully produced.

Review status is tracked as:

- `NOT_REQUESTED`
- `PENDING`
- `APPROVED`
- `REJECTED`

When validation passes, the graph persists `PENDING` review state and pauses
with a native LangGraph interrupt. The interrupt payload contains only safe
review context: investigation identity, supplier ID, risk score/level, generated
summary, recommendations, evidence reference IDs, and validation success.

The payload must not contain API keys, DSNs, SQL, raw provider responses, full
internal prompts, credentials, BigQuery raw rows, or transport metadata.

## Review Decisions

Stage 16 supports exactly two decisions:

- `APPROVE`
- `REJECT`

Rejection requires a non-empty reason. Approval may include no reason.

The reviewer identity is an application-provided opaque identifier. Stage 16
does not implement authentication or authorization; those belong to a later
application/deployment boundary.

Human review cannot modify Supplier identity, evidence records, risk score,
risk level, model version, factor scores, or generated report fields. A rejected
report remains available for audit and does not trigger automatic regeneration.

## Evaluation Harness

The deterministic evaluation suite runs offline with fake data and fake model
responses:

```bash
uv run python -m supplychain.agent.evaluation
```

The command returns a non-zero exit code if any curated contract case fails.
The Stage 16 threshold is 100% because these are deterministic engineering
checks, not probabilistic model-quality metrics.

Evaluation cases cover:

- Zero evidence with no fabricated citations.
- Valid allowlisted evidence references.
- Fabricated evidence reference rejection.
- Risk tampering rejection.
- Prompt-injection text in the user question.
- Instruction-like untrusted evidence text.

Reported metrics include total cases, passed/failed cases, pass rate, risk
immutability pass rate, evidence integrity pass rate, HITL routing pass rate,
and security boundary pass rate.

## Security

Generated recommendations remain advisory only. Stage 16 does not implement
autonomous remediation, supplier outreach, procurement changes, message
publication, BigQuery writes, or external tool execution.
