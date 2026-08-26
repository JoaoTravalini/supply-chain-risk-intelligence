# Synthetic Supplier Dataset

Stage 7B creates the canonical synthetic Supplier master dataset for the portfolio environment.

The dataset is fully synthetic. It is not intended to represent the actual supplier network, commercial exposure, sourcing strategy, or operating performance of any real company.

## Artifact

- Dataset: `data/synthetic/suppliers-v1.jsonl`
- Manifest: `data/synthetic/suppliers-v1.manifest.json`
- Format: UTF-8 JSONL, one Supplier JSON object per line.
- Record count: 120.
- Supplier schema version: `1.0.0`.
- Generator version: `1.0.0`.
- Deterministic seed: `7407`.

Each record validates through the Supplier v1 Pydantic contract before serialization. JSONL serialization uses stable key ordering, compact separators, and deterministic final newline behavior.

## Reproducibility

Generation uses a local `random.Random` instance with the fixed seed. It does not rely on global random state, current date/time, filesystem ordering, machine locale, network calls, or external datasets.

The committed tests regenerate the dataset and compare the canonical JSONL bytes. If generation rules change without regenerating the artifact, the reproducibility test fails.

## Geographic Approach

The generator uses a controlled internal catalog of public city/region/country coordinates. Locations are geographically plausible and diverse enough to support future weather and seismic correlation, but they are not associated with real supplier companies.

The catalog includes at least 10 country codes across North America, Europe, South America, and Asia. No geocoding or network lookup is performed.

## Category And Geography Plausibility

Approved Supplier categories are generated across controlled location pools. The mapping intentionally gives higher representation to plausible regions, such as East Asia and selected US locations for semiconductors, Germany/Mexico/US/Central Europe for automotive components, and Brazil/China/India/Canada/Poland for metals.

These rules are synthetic portfolio structure, not economic claims.

## Criticality

All criticality values appear in the dataset:

- `LOW`
- `MEDIUM`
- `HIGH`
- `CRITICAL`

The generation strategy uses deterministic weighted representation. `CRITICAL` suppliers are intentionally a minority because criticality represents business impact if unavailable, not current risk.

## Exposure, Dependency, And Single Source

Annual spend values are positive whole-dollar synthetic USD exposures. They vary by category and criticality to create materially different portfolio exposure levels. The values are normalized analytical inputs, not transactional accounting records.

Lead times vary by category within the Supplier contract's 1-365 day range.

Dependency scores vary from low to high across the valid `0.0` through `1.0` range. Higher criticality can trend toward higher dependency, but the fields are not mechanically equivalent.

Both `single_source = true` and `single_source = false` appear. Single-source suppliers are a minority and are not inferred by a real sourcing engine.

## Integrity Manifest

The manifest records:

- dataset name;
- Supplier schema version;
- generator version;
- deterministic seed;
- record count;
- relative Supplier schema path;
- SHA-256 checksum of the exact JSONL bytes.

The manifest does not contain generation timestamps, usernames, absolute paths, or machine-specific metadata.

## Limitations

This dataset is master data only. It does not include operational observations, delivery history, current risk scores, external risk signals, weather exposure, seismic exposure, anomaly scores, or transformation outputs.

The dataset has not been loaded into BigQuery. No physical Supplier table exists yet.
