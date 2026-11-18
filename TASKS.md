# Task Backlog

## P0 — Trustworthy foundation
- [x] LOT-001 Confirm repository branch and CI baseline.
- [ ] LOT-002 Identify authoritative historical result source(s).
- [ ] LOT-003 Capture and hash immutable raw source snapshots.
- [x] LOT-004 Define canonical draw schema; prize schema remains specified separately in DATA_SPEC.
- [x] LOT-005 Implement strict number/date/identifier and canonical dataset validation.
- [x] LOT-006 Reconcile overlapping selected-number/date records across the legacy candidate and an independent CSV snapshot; official-source provenance remains open.
- [x] LOT-007 Add unit tests for parsing, duplicate reconciliation, and dataset validation.
- [ ] LOT-008 Complete live-source verification and ingestion-run provenance acceptance test.

## P1 — Research quality
- [x] LOT-009 Implement legal-draw random simulation.
- [x] LOT-010 Add initial descriptive frequency diagnostics; gap analysis remains open.
- [x] LOT-011 Add pair/co-occurrence statistics using exact equal-tailed binomial tests and one Holm family across all 661 front/back pairs; includes full pair output, provenance hash/validation, CLI, methodology limits, unit tests, and CI artifact. Linux CI [44227158435](https://github.com/Be90nia/Lottery/actions/runs/44227158435) passed (79 tests plus candidate-dataset analysis).
- [x] LOT-012 Add Holm multiple-testing correction for defined test families.
- [ ] LOT-013 Add equipment/ball-set/event metadata with citations.
- [x] LOT-014 Add deterministic date-grouped chronological train/validation/test splitting with input/output SHA-256 hashes, date-group boundaries, manifest, CLI, tests, docs, and CI smoke test. Linux CI [44227557430](https://github.com/Be90nia/Lottery/actions/runs/44227557430) passed (85 tests and full candidate-data split).
- [x] LOT-015 Add initial leakage-safe expanding rolling-origin benchmark (uniform, expanding frequency, EWMA); independent final holdout and inference remain open.
- [x] LOT-016 Add deterministic benchmark configuration and JSON report with input hash; artifact archival/CI acceptance remains open.

## P2 — Domain accounting and publication
- [x] LOT-017 Version prize rules by effective draw across six eras: 2007 launch eight-tier (07001–09120, reconstructed with explicit source-quality caveat), 2009 eight-tier, 2013 funding revision, 2014 six-tier, 2019 nine-tier, and 2026 seven-tier. Added per-era hit patterns, fixed prizes, add-on multipliers, Decimal-safe threshold handling, floating-award metadata, docs, and tests. Linux CI [44228536870](https://github.com/Be90nia/Lottery/actions/runs/44228536870) passed (96 tests); Windows ledger CI also passed.
- [ ] LOT-018 Reconcile base/additional awards and promotion overlays. Implemented 25-label classification, ruleset-aware joins, ±¥2 display tolerance for floating amounts, exact fixed-tier multiplier checks, promotion separation, coverage summaries, and full discrepancy output. CI [44230770405](https://github.com/Be90nia/Lottery/actions/runs/44230770405) passed (108 tests); candidate audit: 8,905 pairs, 6,037 floating pairs within tolerance, 14 residual mismatches, 734 unauthorized 2007 fixed-tier add-ons. Official raw snapshots, 07001 source resolution, and full campaign reconciliation remain open. See [PRIZE_AUDIT.md](docs/PRIZE_AUDIT.md) and [issue #6](https://github.com/Be90nia/Lottery/issues/6).
- [ ] LOT-019 Model promotion eligibility and ticket-level thresholds.
- [ ] LOT-020 Add prize-calculator regression fixtures.
- [ ] LOT-021 Publish data dictionary and methodology reports.
- [ ] LOT-022 Add source schema-drift monitoring.

## Additional data-reconciliation tasks
- [ ] LOT-035 Obtain an authorized network path or official response snapshots for source verification; do not bypass the source WAF.
- [ ] LOT-036 Reconcile legacy promotion flags, prize award types, equipment codes, and monetary fields against raw official records.
- [ ] LOT-037 Extend the candidate dataset from draw 26083 through the latest verified official draw (official provincial result page currently exposes draw 26131 dated 2026-11-16; reconcile the intervening 48 draws before use).
- [ ] LOT-038 Promote a versioned canonical dataset only after source overlap, completeness, and prize-field checks pass.
- [ ] LOT-039 Investigate early-era front-zone frequency deviations using authoritative equipment and ball-set histories, then run predeclared stratified tests.
- [x] LOT-040 Run the rolling-origin benchmark against the repository dataset in CI; first complete report archived as a GitHub Actions artifact. Initial performance is exploratory only.
- [x] LOT-041 Add paired moving-block bootstrap confidence intervals for Brier/log-loss differences versus uniform; results recorded in docs/INITIAL_BACKTEST_RESULTS.md. Period stability review remains open.
- [ ] LOT-042 Execute the prospective untouched holdout. Draft fixed protocol is in docs/HOLDOUT_PREREGISTRATION.md; do not mark complete until 500 post-freeze official draws are captured, reconciled, and analyzed once.
- [x] LOT-043 Add paired rolling-origin score comparisons by fixed calendar eras and assess descriptive stability without tuning. Results are exploratory/post-hoc, not confirmatory; see docs/ERA_STABILITY_RESULTS.md.


- [ ] LOT-044 Complete historical `lotteryUnsortDrawresult` / `lotteryEquipmentCount` provenance. Partial validation: twenty-one exact legacy-to-official row crosswalks, comprising 16 purposive examples and 5 matches from a seeded one-draw-per-year random audit sample span 2017, 2018, 2020, and 2022–2026; official announcements explicitly label the sequence “本期出球顺序” and confirm ball-set codes 1/2/3. Historical row-level provenance for the remaining 2,320 legacy rows and the exact operational timing semantics of draw order remain open. Machine-readable registry and CI verifier are in `data/metadata_verification/official_order_crosswalks_20261118.json` and `scripts/verify_official_order_crosswalks.py`. See [DRAW_ORDER_METADATA_AUDIT.md](docs/DRAW_ORDER_METADATA_AUDIT.md).
- [x] LOT-045 Add offline immutable JSON snapshot import with SHA-256 sidecar verification, duplicate reconciliation, dataset validation, output manifest, and explicit unverified status when provenance is incomplete. Audit: [DRAW_ORDER_METADATA_AUDIT.md](docs/DRAW_ORDER_METADATA_AUDIT.md).
- [x] LOT-046 Add pre-draw forecast ledger with fixed model probabilities, training-data hash, code commit, future-target guard, duplicate prevention, and hash-chain verification. This is instrumentation only; LOT-042 holdout remains unstarted.
- [x] LOT-047 Add separate provenance-gated post-draw outcome ledger and offline per-draw scoring; never mutate forecast events. Includes timestamp/source/result validation, forecast-event linkage, semantic ledger verification, per-draw Brier/Log Loss/Top-K scoring, and exact-score regression tests. CI run [44225221808](https://github.com/Be90nia/Lottery/actions/runs/44225221808) passed.
- [x] LOT-048 Serialize forecast/outcome ledger appends across processes with POSIX `flock` and Windows `msvcrt.locking`; lock the full verify/dedupe/append/fsync transaction, use bounded acquisition timeouts, retain lock files, and test duplicate/distinct concurrent writes plus timeout/crash release. Linux and Windows CI passed in [run 44226365462](https://github.com/Be90nia/Lottery/actions/runs/44226365462); CLI timeout reporting also passed in [run 44226591924](https://github.com/Be90nia/Lottery/actions/runs/44226591924).
- [ ] LOT-049 Replace lossy legacy prize transformation with source-preserving official prize ingestion.
- [ ] LOT-050 Resume V3 predictive model research: rerun fixed rolling-origin baseline on the 2,949-draw official selected-number snapshot; predeclare R1–R4 adjacent-draw dependence diagnostics; evaluate strictly causal lag-feature candidates against uniform/expanding/EWMA; keep order/equipment features gated on LOT-044 and keep LOT-042 prospective holdout separate. See [V3 model research plan](docs/V3_MODEL_RESEARCH_PLAN.md) and [issue #10](https://github.com/Be90nia/Lottery/issues/10). Preserve complete raw `prizeLevelList` objects, source snapshot hash, draw linkage, all optional identifiers/award-type fields, and quarantine ambiguous identities. Legacy cleaner audit: [LEGACY_PRIZE_TRANSFORM_AUDIT.md](docs/LEGACY_PRIZE_TRANSFORM_AUDIT.md). Do not promote existing candidate prize rows.

## Acceptance criteria

A task is complete only when code, tests, provenance, and documentation are updated together. Research claims require reproducible evidence and an explicit limitations section.
