# ADR 0005: LangGraph with PostgreSQL-Backed Persistent State

## Status

Accepted

## Context

The AI investigation workflow needs structured state, durable execution, interrupt/resume behavior, and human-in-the-loop support. Analytical warehouse storage is not suitable for transactional agent checkpoints or thread state.

## Decision

LangGraph will be used for the investigation workflow, with persistent checkpoints and thread state stored in PostgreSQL through an abstraction compatible with a production persistent checkpointer.

The intended logical workflow is:

```text
START
-> Understand Request
-> Plan Investigation
-> Determine Required Evidence
-> Retrieve Evidence
-> Analyze Evidence
-> Validate
-> Respond OR Human Review
```

## Consequences

- Agent state must be modeled explicitly when implementation reaches the agent stages.
- PostgreSQL becomes the transactional persistence target for LangGraph execution state.
- BigQuery remains the analytical system of record, not agent checkpoint storage.
- Human review and resume behavior must be treated as first-class workflow concerns.
