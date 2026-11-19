# Automatic official draw sync — MVP boundary

## What runs

The `official-draw-sync-mvp` GitHub Actions workflow runs daily at 15:17 UTC and can also be started manually. It invokes the existing strict Sporttery history collector in an isolated temporary directory, preserving raw response snapshots and per-page SHA-256 manifests. It uploads a 90-day run artifact and a machine-readable `sync-receipt.json`.

The workflow is deliberately read-only with respect to the repository: it has `contents: read`, checkout credentials are disabled, and it never commits or replaces canonical history. A completed fetch is labeled `fetch_completed_untrusted`, not authenticated official data. A network, HTTP, parsing, or validation failure produces an evidence artifact and a visibly failed run.

## Why this is not yet unattended canonical updating

The official endpoint has previously returned HTTP 567 from GitHub-hosted runners. Until an authorized source path is consistently reachable and completeness can be independently established, automatically publishing fetched rows would risk silently truncating or corrupting history. The workflow therefore archives candidate evidence only; it does not rebuild the trusted dataset, write forecast/outcome ledgers, train models, promote a model, or consume the isolated LOT-042 prospective holdout.

The collector currently stops on an empty or short page. That behavior is not, by itself, proof that all historical pages were returned. A later promotion of this workflow from candidate archive to canonical sync must add and test source-side completeness reconciliation, monotonic draw-ID/date checks across the entire page set, correction/revision event handling, and an append-only canonical update transaction.

## MVP acceptance gates

1. Daily and manual runs are deterministic in scope and non-overlapping.
2. Every received page is preserved with its exact response bytes, source URL, HTTP status, retrieval timestamp, parser version, and SHA-256.
3. Any request, HTTP, schema, duplicate-conflict, or number-range error fails closed and retains diagnostics.
4. The receipt states whether fetch completed, the code commit, and that canonical data/model state was not modified.
5. No source response is treated as official authentication merely because it came from the configured endpoint or has a matching hash.
6. Canonical updates remain blocked until completeness and correction semantics are independently verified.

## Operator path

Open **Actions → official-draw-sync-mvp → Run workflow** for an immediate probe. Download the `official-draw-sync-*` artifact and inspect `sync-receipt.json`, `fetch-error.txt`, raw page snapshots, and manifests. Do not manually copy candidate output into canonical history without completing the acceptance gates above.
