# Risk MART

Stage 12 defines the MART tables for deterministic Supplier Risk Model v1
outputs. The tables are provisioned only after human review and approval of the
saved Stage 12 OpenTofu plan.

## Tables

`supplychain_mart.supplier_risk_current` is the latest completed risk
assessment snapshot. It is loaded with a BigQuery batch load job using
`WRITE_TRUNCATE`, so a completed batch contains one row per Supplier.

`supplychain_mart.supplier_risk_history` is append-oriented assessment history.
It is loaded with a BigQuery batch load job using `WRITE_APPEND`, and each row
represents one Supplier assessment at one explicit `assessed_at` timestamp.

No streaming writes, DML, `MERGE`, `UPDATE`, or `DELETE` are used.

## Schema

Both tables share the Supplier Risk Assessment physical schema:

- `model_version`
- `supplier_id`
- `assessed_at`
- `risk_score`
- `risk_level`
- factor family scores
- structural decomposition components
- relevant weather and seismic event counts
- `evidence_deduplication_keys` as native BigQuery JSON
- `dominant_factor`

The MART tables do not store full Supplier records, full Canonical Events,
provider payload dumps, Pub/Sub transport IDs, acknowledgement IDs, delivery
attempts, or retry counters.

## Physical Design

`supplier_risk_current` is intentionally small and unpartitioned.

`supplier_risk_history` is partitioned by `assessed_at` at DAY granularity and
clustered by:

- `risk_level`
- `supplier_id`

The MART dataset continues to use the development BigQuery Sandbox retention
strategy inherited from the existing dataset configuration.

## Logical Identity

Current logical key:

```text
supplier_id
```

History logical identity:

```text
supplier_id + assessed_at + model_version
```

BigQuery does not enforce these identities as transactional primary keys in
Stage 12.

## Batch Consistency

The risk batch service computes the complete portfolio assessment in memory
before writing MART. It appends history first and then replaces the current
snapshot.

The two BigQuery load jobs are not one distributed transaction. If the history
write fails, the current snapshot is not replaced and the batch is not complete.
If the current snapshot replacement fails after history append succeeds, the
history table may contain a batch not reflected in current until a later
controlled rerun.
