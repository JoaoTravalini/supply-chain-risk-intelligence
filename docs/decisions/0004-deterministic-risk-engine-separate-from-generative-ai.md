# ADR 0004: Deterministic Risk Engine Separate from Generative AI

## Status

Accepted

## Context

Supplier risk scores must be reproducible, auditable, testable, and explainable. Generative AI is useful for investigation and explanation, but it is not appropriate as the source of authoritative business metrics.

## Decision

Supplier risk scores and risk factors will be calculated by deterministic, versioned business logic.

The LLM may retrieve data, investigate, correlate evidence, explain findings, summarize, and recommend. The LLM must not generate the authoritative supplier risk score or invent authoritative business metrics.

## Consequences

- Risk scoring logic must be testable independently of LLM calls.
- Risk outputs must include enough metadata to support reproduction, such as calculation timestamp, model or rule version, component scores, and input references where appropriate.
- Agent responses must distinguish evidence-backed explanation from authoritative calculated metrics.
- Future prompt and tool design must prevent unrestricted metric generation.

