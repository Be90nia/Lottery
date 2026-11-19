# Append-only draw publication gate

This local gate sits between immutable official-source response snapshots and a candidate canonical JSONL. It is separate from collection and model training.

## Build a full candidate snapshot

```bash
python scripts/fetch_history.py \
  --snapshots-dir data/raw/authorized-sporttery \
  --require-manifests \
  --output sync-run/candidate.jsonl
```

Strict import writes `sync-run/candidate.jsonl.manifest.json`. The manifest distinguishes complete per-page provenance from source-pagination completeness: the current importer explicitly emits `source_completeness_verified: false`. Complete page hashes do not prove that no page or newer draw was omitted.

## Reconcile

```bash
python scripts/reconcile_draws.py \
  --current data/canonical/draws.jsonl \
  --candidate sync-run/candidate.jsonl \
  --candidate-manifest sync-run/candidate.jsonl.manifest.json \
  --output data/canonical/draws.next.jsonl \
  --receipt sync-run/reconciliation-receipt.json
```

Both files are validated. The candidate must contain every existing draw, and all existing draw semantics (date, selected numbers, draw order, equipment metadata) must match. The publication gate additionally requires a sidecar whose final URL exactly equals the requested Sporttery endpoint and whose redirect chain is empty; redirected responses are rejected by the live collector and cannot pass strict import or publication. It also requires `source_completeness_verified: true`; it refuses the current collector output until upstream pagination totals/page inventory can be independently reconciled. Only then may strictly later chronological draws be appended. Missing history, unverified completeness, corrections, incomplete provenance, and chronology regressions fail closed.

No-new-draw runs emit a `no_new_draws` receipt and do not write the output. Appends write a new file atomically without overwriting the input. Review the receipt and explicitly promote the output in a separate controlled operation.

Corrections require a preserved raw snapshot, an incident, and a separately reviewed correction event. This tool does not update forecast/outcome ledgers, train/promote models, or access LOT-042. Trust remains `manifest_complete_not_officially_authenticated`. The completeness flag is a separate gate, not implied by provenance completeness; no current ingestion path sets it to true.
