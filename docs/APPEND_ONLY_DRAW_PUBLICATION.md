# Append-only draw publication gate

This local gate sits between immutable official-source response snapshots and a candidate canonical JSONL. It is separate from collection and model training.

## Build a full candidate snapshot

```bash
python scripts/fetch_history.py \
  --snapshots-dir data/raw/authorized-sporttery \
  --require-manifests \
  --output sync-run/candidate.jsonl
```

Strict import writes `sync-run/candidate.jsonl.manifest.json`. Internally complete provenance metadata is not a cryptographic source signature or independent proof of authenticity.

## Reconcile

```bash
python scripts/reconcile_draws.py \
  --current data/canonical/draws.jsonl \
  --candidate sync-run/candidate.jsonl \
  --candidate-manifest sync-run/candidate.jsonl.manifest.json \
  --output data/canonical/draws.next.jsonl \
  --receipt sync-run/reconciliation-receipt.json
```

Both files are validated. The candidate must contain every existing draw, and all existing draw semantics (date, selected numbers, draw order, equipment metadata) must match. Only strictly later chronological draws may be appended. Missing history, corrections, incomplete provenance, and chronology regressions fail closed.

No-new-draw runs emit a `no_new_draws` receipt and do not write the output. Appends write a new file atomically without overwriting the input. Review the receipt and explicitly promote the output in a separate controlled operation.

Corrections require a preserved raw snapshot, an incident, and a separately reviewed correction event. This tool does not update forecast/outcome ledgers, train/promote models, or access LOT-042. Trust remains `manifest_complete_not_officially_authenticated`.


## Source completeness gate

A candidate is not append-eligible merely because its raw pages have valid hashes and the candidate contains all currently known draws. The publisher also requires authoritative pagination metadata that matches the observed unique draw count, non-empty page count, page size, and contiguous page inventory. The current Sporttery collector does not yet validate authoritative total-page/record metadata, so its manifests explicitly set `source_completeness_verified: false`; such snapshots remain review artifacts and the append gate rejects them. This is intentional: a truncated but internally valid fetch must never advance the candidate history.
