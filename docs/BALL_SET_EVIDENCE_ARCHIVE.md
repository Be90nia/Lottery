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
  --receipt data/evidence/ball-set-receipt.json \\
  --draw-inventory data/candidates/legacy_draws.jsonl
```

The JSONL ledger is append-only and uses the shared OS-level ledger lock. Identical response bytes are idempotent. Changed bytes from the same URL create a new `source_revision_requires_review` observation and preserve the prior bytes; disagreement between official sources creates a conflict record. Missing labels remain `missing_label`. Draw ID/date mismatches and malformed pages fail closed.

The scheduled workflow carries forward the latest cumulative archive artifact, cross-checks page draw IDs/dates against the checked-in candidate draw inventory, and uploads a new 90-day artifact. The inventory is still `candidate_unverified`, so a match is an identity/date crosswalk, not independent authentication of the draw result. This is a staging archive, **not yet the permanent canonical evidence store**. LOT-065 still requires durable content-addressed storage, independent backup, and restore verification before this archive can be treated as permanent canonical evidence.

## Regime and model eligibility

`reported_set_index`, `equipment_regime_id`, and `physical_ball_set_id` remain separate. This collector deliberately writes null regime and physical identity fields. The two-set launch-era / three-set-era transition and physical identity continuity are not inferred. No training view or 3N model slot is activated by collection alone.

A draw with an A2 primary label but unresolved regime remains archival evidence, not eligible for regime-scoped model training. Coverage reports and official regime adjudication remain separate gates. The collector never reads LOT-042 and never trains or promotes a model.
