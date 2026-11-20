# LOT-058: Official per-draw ball-set evidence archive

## Purpose and trust boundary

The collector archives per-draw announcement pages from the Jiangsu Provincial Sports Lottery Management Center (A2). It extracts a ball-set index only when the page literally states `本期使用第X套摇奖球`, with X in 1..3. It does not infer a label from `lotteryEquipmentCount`, number patterns, adjacent draws, or the date.

The registry starts from draw 19101 (2019-08-31), a verified A2 announcement in the documented three-set era, and follows the official article's newer-draw navigation link through the current draw. The initial backfill is capped at 2,000 pages per run. The collector resumes from the latest archived page on later runs, so it can discover future announcements without hardcoding future page IDs. Every response is archived as exact bytes under a content-addressed SHA-256 path before parsing.

Each observation stores source authority, requested/final URL, redirects, retrieval time, HTTP metadata, byte length/hash, parser version, exact matched phrase and text span, draw ID/date, reported set index, a draw-inventory crosswalk at capture time, nullable regime/physical identity, status, conflict group, and superseded observation ID. Labels absent from the current draw inventory remain `official_label_pending_inventory`; date mismatches fail closed.

## Run

```bash
python scripts/collect_ball_set_evidence.py \
  --registry config/ball_set_source_registry.json \
  --archive-dir data/evidence/ball-set-archive \
  --ledger data/evidence/ball-set-observations.jsonl \
  --receipt data/evidence/ball-set-receipt.json \
  --draw-inventory data/ball_set/draw-inventory-20261118.jsonl
```

The JSONL ledger is append-only, uses the shared OS-level ledger lock, and carries a SHA-256 event chain (`prev_hash`/`event_hash`) that is verified before every append and coverage build. Identical response bytes are idempotent. Changed bytes from the same URL always create a new immutable observation version and preserve prior bytes. If draw date and explicit set label are unchanged, the version is `source_revision_same_semantics`; if either changes, it is `source_revision_requires_review` and blocks the verified view. Disagreement between official sources creates a conflict record. Missing labels remain `missing_label`. Draw ID/date mismatches and malformed pages fail closed.

The scheduled workflow carries forward the latest cumulative archive artifact, cross-checks page draw IDs/dates against the checked-in candidate draw inventory, and uploads a new 90-day artifact. The inventory is still `candidate_unverified`, so a match is an identity/date crosswalk, not independent authentication of the draw result. This is a staging archive, **not yet the permanent canonical evidence store**. LOT-065 still requires durable content-addressed storage, independent backup, and restore verification before this archive can be treated as permanent canonical evidence.


The collector and coverage workflow use the pinned 2,949-row candidate inventory at `data/ball_set/draw-inventory-20261118.jsonl`, through draw 26131 (2026-11-16), SHA-256 `9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa`. Its trust status is `manifest_complete_not_officially_authenticated`. Newer official announcements (including draw 26132 on 2026-11-18) can be archived, but remain `official_label_pending_inventory` until the draw inventory is reconciled; they are not silently added to the verified crosswalk.

## Regime and model eligibility

`reported_set_index`, `equipment_regime_id`, and `physical_ball_set_id` remain separate. This collector deliberately writes null regime and physical identity fields. The two-set launch-era / three-set-era transition and physical identity continuity are not inferred. No training view or 3N model slot is activated by collection alone.

A draw with an A2 primary label but unresolved regime remains archival evidence, not eligible for regime-scoped model training. Coverage reports and official regime adjudication remain separate gates. The collector never reads LOT-042 and never trains or promotes a model.

## Coverage report

After collection, rebuild the evidence-derived coverage report:

```bash
python scripts/build_ball_set_coverage.py \
  --draw-inventory data/ball_set/draw-inventory-20261118.jsonl \
  --ledger data/evidence/ball-set-archive/observations.jsonl \
  --archive-dir data/evidence/ball-set-archive \
  --output-json data/evidence/ball-set-archive/coverage/coverage.json \
  --output-csv data/evidence/ball-set-archive/coverage/per-draw.csv \
  --output-per-set-csv data/evidence/ball-set-archive/coverage/per-set.csv \
  --output-per-year-csv data/evidence/ball-set-archive/coverage/per-year.csv \
  --output-markdown data/evidence/ball-set-archive/coverage/coverage.md
```

The report re-hashes every raw object, verifies the complete retrieval manifest and observation identity/hash chain, re-runs the parser, and cross-checks draw ID/date against the supplied inventory. It reports verified counts by set, year, and source domain; missing/unobserved/conflicting records; first/last draw; leading/trailing and largest inter-label gaps. Because the supplied inventory is still an unverified candidate and the equipment-regime boundary/physical identities are unresolved, the report keeps every target ineligible and does not compute a training denominator or promote a 3N model.

For the frozen 2019+ reported-index pilot, the workflow then runs `scripts/build_reported_set_index_view.py`, which replays the raw archive and binds the inventory, coverage report, and ledger hashes. It includes only the 1,067 primary-verified labels in the preregistered window (360 / 347 / 360 by reported index), and fails if the counts or draw window change without a protocol version update. The resulting view preserves null regime/physical IDs and a blocked physical-model eligibility flag.

The workflow runs the preregistered same-index rolling-origin pilot and, after a complete pilot receipt, emits all three estimator lanes for each reported index (5 tickets per lane by default; 45 total). These are exploratory reported-index-conditioned candidates, not physical ball-set predictions. No lane is selected from the pilot results, no efficacy is claimed, and no model is promoted. See [the preregistration](REPORTED_SET_INDEX_CONDITIONAL_MODEL_PREREGISTRATION.md).
