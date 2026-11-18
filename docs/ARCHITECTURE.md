# Architecture

## Data flow

`official sources -> immutable raw snapshots -> parsing -> normalization -> validation -> canonical dataset -> analysis/features/backtests/reports`

Each stage must be reproducible and must retain references to its inputs and code version.

## Layers

- **Sources:** official result pages/APIs and authoritative rule notices.
- **Raw:** exact source payloads, retrieval timestamp, source URL, content hash.
- **Ingestion:** transport, pagination, retries, and source-specific parsing.
- **Canonical:** normalized draw records and separately normalized prize records.
- **Metadata:** rule eras, equipment, ball sets, and documented incidents with provenance and confidence.
- **Analysis:** descriptive statistics, simulation tests, anomaly screening.
- **Experiments:** time-aware features, baselines, models, and backtests.
- **Reporting:** generated tables and reports linked to dataset and code revisions.

## Invariants

1. Raw snapshots are immutable; corrections create new versions.
2. Every canonical row can be traced to source records.
3. Invalid records are quarantined with explicit reasons, not silently discarded.
4. Draw numbers and dates are identifiers/data, not inferred from adjacent records.
5. Post-draw information must never enter pre-draw prediction features.
6. Training and evaluation splits are chronological.
7. Exploratory analysis and confirmatory tests are labeled separately.

## Storage

Keep source code, schemas, manifests, compact metadata, and reports in Git. Large raw or derived datasets should use Git LFS or versioned external storage, with checksums and manifests committed to Git. Do not commit secrets or access tokens.

## Suggested package layout

```
src/lottery/
  sources/
  ingest/
  schemas/
  normalize/
  validation/
  statistics/
  features/
  models/
  backtest/
  prizes/
  reporting/
data/
  raw/
  interim/
  processed/
tests/
  unit/
  integration/
  fixtures/
configs/
reports/
```


## Durable publication and recovery

Git is for code, schemas, compact manifests and documentation; GitHub Actions artifacts are ephemeral transport only. Canonical evidence, snapshots, model artifacts and ledgers require durable versioned storage with content hashes and manifests.

Publish immutable objects by staging, read-back hash verification, schema validation, conditional create, durable receipt, then CAS update of the active pointer. Never expose partially written objects or mixed three-slot registry generations. A workflow is not successful until its durable commit receipt exists. Retries are idempotent and stale workers are fenced out. Reconciliation is read-only by default; repairs are explicit and audited.

Backups must be independently stored and periodically restored in isolation. Backup success without a restore drill is not proof of recoverability. Preserve old objects through corrections and schema migrations; write new versions with explicit lineage. Do not enable production collection, promotion or serving before fault-injection and restore acceptance tests pass.


## Software supply-chain security

Third-party Actions must be pinned to reviewed full commit SHAs; workflow permissions are explicit and least-privilege. The read-only source probe receives no write, signing, registry or production credentials, and checkout credentials are not persisted by default. Dependencies and release runtimes are locked; SBOM, vulnerability reports and build provenance are retained.

Artifact digests are signed by protected identities and verified against expected repository/workflow/source provenance at evaluation, promotion and serving. A hash/signature does not replace numerical or statistical validation. Secrets, signing keys and master RNG seeds never enter logs or ordinary artifacts. Protected review gates cover workflows, lockfiles, signing and registry changes. Production remains disabled until security acceptance and compromise-recovery drills pass.
