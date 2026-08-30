# LangGraph Investigation Runtime

Stage 13 introduces the durable local investigation runtime for SupplyChain
Sentinel. It provides a real LangGraph graph with PostgreSQL-backed checkpoints
while keeping business behavior intentionally minimal.

The agent runtime is orchestration and explanation infrastructure. It does not
calculate authoritative supplier risk, call an LLM, query BigQuery, use Pub/Sub,
or call external providers in Stage 13.

## Runtime Role

The Stage 13 runtime supports this local foundation:

```text
Future Streamlit
-> InvestigationService
-> LangGraph investigation graph
-> PostgreSQL checkpoint state
```

Future stages will add guarded read-only analytical tools:

```text
LangGraph
-> future guarded BigQuery tools
-> BigQuery CORE / MART
```

Those tools do not exist yet.

## State Contract

`InvestigationState` is JSON-serializable LangGraph checkpoint state. Public
inputs and outputs are validated with immutable Pydantic models at the service
boundary.

Persisted fields are:

- `investigation_id`
- `thread_id`
- `supplier_id`
- `question`
- `status`
- `created_at`
- `updated_at`
- `evidence_keys`
- `error_message`

State must not contain database clients, Google clients, checkpointer objects,
credentials, access tokens, callbacks, exception objects, or arbitrary Python
objects.

## Investigation Identity

`investigation_id` is the application/domain identity for one supply-chain
investigation.

`thread_id` is the LangGraph checkpoint thread identity used in
`configurable.thread_id`.

The two identifiers are separate. Neither identifier is a Pub/Sub message ID,
Canonical Event ID, supplier ID, or deduplication key. One supplier may have
many investigations over time.

## Lifecycle

Stage 13 uses a deliberately small lifecycle:

- `CREATED`
- `READY`
- `FAILED`

The graph currently moves a new investigation from `CREATED` to `READY`.
Human-in-the-loop states are deferred.

## Timestamps

Business-visible state timestamps are timezone-aware and normalized to UTC.
The service boundary creates `created_at` and `updated_at` explicitly, and tests
may supply deterministic timestamps. Naive datetimes are rejected.

## Graph

The compiled graph is built through `build_investigation_graph(checkpointer)`.
There is no mutable global compiled graph and no database connection is created
at import time.

The Stage 13 graph is:

```text
START
-> initialize_investigation
-> prepare_investigation
-> END
```

`initialize_investigation` validates durable investigation context.
`prepare_investigation` marks the investigation ready for future evidence
retrieval. No risk score is calculated and no evidence is fabricated.

## PostgreSQL Checkpoints

Stage 13 uses the official `langgraph-checkpoint-postgres` saver. The
application does not query LangGraph internal checkpoint tables directly and
does not implement a custom fake checkpoint schema.

Configure local persistence with:

```powershell
$env:SUPPLYCHAIN_AGENT_POSTGRES_DSN = "postgresql://$env:SUPPLYCHAIN_AGENT_POSTGRES_USER:$env:SUPPLYCHAIN_AGENT_POSTGRES_PASSWORD@localhost:$env:SUPPLYCHAIN_AGENT_POSTGRES_PORT/$env:SUPPLYCHAIN_AGENT_POSTGRES_DB"
```

Use only local-development values. Do not commit real credentials or
developer-specific DSNs.

Checkpoint schema setup is explicit and run once per local database:

```powershell
uv run python -m supplychain.agent.persistence
```

Graph invocation does not hide DDL at import time.

## Persistence Semantics

The persistence guarantee proven in Stage 13 is durable checkpoint resume:

1. One service/checkpointer creates an investigation.
2. Resources are closed.
3. A new service/checkpointer instance opens the same PostgreSQL database.
4. The same `thread_id` retrieves the latest persisted state.
5. A different `thread_id` remains isolated.

This is not distributed exactly-once processing.

## Storage Boundaries

LangGraph checkpoint state is not BigQuery analytical data, not the
ProcessingLedger, and not future LLM long-term memory.

BigQuery remains the analytical system of record for RAW, CORE, and MART.
ProcessingLedger remains operational event idempotency/revision state.
PostgreSQL stores transactional LangGraph checkpoint state only.
