# Roadmap

## Phase 0 — Engineering baseline
- [ ] Establish repository structure, linting, tests, and CI.
- [ ] Define configuration, logging, deterministic runs, and artifact conventions.
- [ ] Record data provenance and schema versions.

## Phase 1 — Historical data asset
- [ ] Identify authoritative data sources and document their coverage.
- [ ] Preserve immutable raw snapshots with retrieval timestamps and SHA-256 hashes.
- [ ] Build a parser and canonical dataset with strict validation.
- [ ] Reconcile draw identifiers, dates, numbers, prize tiers, and rule periods.

## Phase 2 — Descriptive statistics
- [ ] Validate marginal frequencies against theoretical expectations.
- [ ] Analyze pair/co-occurrence, gaps, sums, parity, ranges, and draw order.
- [ ] Use simulation or exact sampling distributions for fixed-size draws.
- [ ] Correct for multiple testing and report uncertainty.

## Phase 3 — Context and features
- [ ] Version documented rule, equipment, ball-set, and event metadata.
- [ ] Separate pre-draw predictors from post-draw explanatory metadata.
- [ ] Create leakage-resistant, time-indexed feature datasets.

## Phase 4 — Predictive experiments
- [ ] Establish legal random baselines.
- [ ] Use rolling-origin evaluation and untouched chronological test periods.
- [ ] Compare models using predeclared metrics and uncertainty intervals.
- [ ] Retain negative results and reproducible experiment configurations.

## Phase 5 — Prize and promotion accounting
- [ ] Version prize rules by effective draw.
- [ ] Reconcile base/add-on awards and promotion eligibility.
- [ ] Test edge cases against official examples and source records.

## Phase 6 — Reporting
- [ ] Publish reproducible reports with data versions and code revisions.
- [ ] Distinguish exploratory findings from confirmatory tests.
- [ ] Document limitations and avoid unsupported causal claims.

## Phase 7 — Maintenance
- [ ] Monitor source changes and schema drift.
- [ ] Re-run validation when new draws arrive.
- [ ] Review dependencies, security, and reproducibility.
