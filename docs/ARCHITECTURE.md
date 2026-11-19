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


## Release readiness and integration

The system exposes derived readiness states: `NOT_READY`, `READY_FOR_OFFLINE_VALIDATION`, `READY_FOR_SHADOW`, and `READY_FOR_PRODUCTION`. State is computed from immutable receipts bound to one release-manifest digest. Unknown or missing evidence is not a pass; issue closure is not readiness.

The release manifest links source/workflow/dependencies, SBOM and provenance, canonical data/evidence, model and evaluation artifacts, Champion generation, sampler/RNG version, durable commit receipts, backup/restore drill, policy and approvals. Integration gates cover data, numerical correctness, experiment validity, regime evidence, lifecycle/serving, feedback, storage/recovery and security. Fault injection must demonstrate fail-closed behavior and no partial user-visible batches. Production requires protected approval for the exact manifest and successful restore/rollback drills.


## Legacy pipeline isolation

Existing `baseline.py`, `backtest.py` and `forecast.py` implement an older marginal-frequency research/holdout path. They are not the new complete-subset probability engine. Preserve the LOT-042 forecast path and data unchanged; do not silently reuse marginal inclusion vectors as exact ticket probabilities. Build LOT-054 in an isolated `src/lottery/subset_model/` package, beginning with strict support enumeration, symmetric features, exact uniform moments and multiplicity aggregation, then add probability fitting and sampling in later independently tested slices.


## Current code boundary and first implementation slice

The current `src/lottery/backtest.py` is a marginal-inclusion benchmark (per-number Brier/log loss), and `src/lottery/forecast.py` creates the older LOT-042 pre-draw ledger from uniform/expanding/EWMA marginal probabilities. They do not implement a joint distribution over complete unordered subsets and must remain isolated from the future exact-set serving path.

The existing CI entry point is `.github/workflows/tests.yml`. It runs unit tests and exploratory scripts over the unverified legacy candidate dataset; those jobs are not the frozen LOT-055 confirmatory evaluation. The first new implementation slice is LOT-068 (#31), a separate offline exact-subset engine with exact full-support exponential-family normalization, conditional-Poisson DP, fit/calibration gates, canonical artifact identity and numerical/property tests. LOT-055 follows as a separate frozen exact-set evaluator.
