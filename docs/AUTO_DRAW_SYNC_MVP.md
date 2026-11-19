# Automatic official draw sync — MVP boundary

## What runs

The `official-draw-sync-mvp` GitHub Actions workflow runs daily at 15:17 UTC and can also be started manually. It invokes the existing strict Sporttery history collector in an isolated per-run directory `sync-run/raw/<run_id>/`, preserving raw response snapshots and per-page SHA-256 manifests with requested URL, final URL, and an explicit empty redirect chain. The collector rejects HTTP redirects before following them. The fetch receipt's `raw_dir` is checked to remain beneath the isolated run root, and strict import consumes only that directory. It then re-imports the archived pages with `--require-manifests` to build a validated candidate JSONL plus its output manifest. The workflow next runs `scripts/reconcile_draws.py` against the pinned 2,949-row baseline and the exact isolated raw snapshot directory. This gate re-parses every raw page, verifies the source totals attestation, compares the candidate against every historical row, rejects corrections/missing rows/chronology regressions, and writes a separate append-only candidate artifact plus receipt when the full check passes. Strict import binds each sidecar's `page_no` to the URL's `pageNo`, requires the same `gameNo=85`, `provinceId=0`, `isVerify=1` and `pageSize` across all pages, requires a single fetch `run_id`, and rejects missing or duplicate page numbers in the observed inventory. When page 1 supplies positive integer `value.total` and `value.totalPage`, the importer checks the ceiling relation, every page's expected record count, the complete page inventory, and the deduplicated draw count, then emits a raw-page-backed pagination attestation. If those fields are absent, completeness remains unverified; inconsistent totals fail closed. The receipt binds the candidate and manifest hashes and carries the imported attestation status. It uploads a 90-day run artifact and a machine-readable `sync-receipt.json`.

The workflow is deliberately read-only with respect to the repository: it has `contents: read`, checkout credentials are disabled, and it never commits or replaces canonical history. A completed fetch, strict import, and append-only gate is labeled `append_candidate_ready_untrusted`, not authenticated official data. The append gate can report `no_new_draws` or produce a full append-only candidate, but neither result mutates canonical history. Page-manifest consistency is checked. Source pagination completeness is marked verified only when page-1 totals reconcile against all archived raw pages; otherwise it remains explicitly unverified. A network, HTTP, parsing, or validation failure produces an evidence artifact and a visibly failed run.

## Why this is not yet unattended canonical updating

The official endpoint has previously returned HTTP 567 from GitHub-hosted runners. Until an authorized source path is consistently reachable and completeness can be independently established, automatically publishing fetched rows would risk silently truncating or corrupting history. The workflow therefore archives candidate evidence only; it does not publish canonical history, write forecast/outcome ledgers, train models, promote a model, or consume the isolated LOT-042 prospective holdout. The append-only publication gate is now executed inside the workflow, but its output is still only a new artifact rather than a canonical repository update.

## Independent Jiangsu A2 source path

The separate [ball-set evidence workflow](BALL_SET_EVIDENCE_ARCHIVE.md) also captures Jiangsu Provincial Sports Lottery per-draw announcement pages. Those pages expose both the official front/back result and draw order, in addition to the reported set index. The workflow cross-checks all 1,067 primary-verified overlap results against the pinned inventory, rejects any historical mismatch, and appends only strictly sequential new draw IDs to a separate candidate dataset. It then runs the standard ticket MVP against that candidate. This provides an independent current-draw path when the Sporttery API is inaccessible, without bypassing its edge controls or modifying canonical data.

The collector currently stops on an empty or short page. That behavior is not, by itself, proof that all historical pages were returned. A later promotion of this workflow from candidate archive to canonical sync must add and test source-side completeness reconciliation, monotonic draw-ID/date checks across the entire page set, correction/revision event handling, and an append-only canonical update transaction.

## MVP acceptance gates

1. Daily and manual runs are deterministic in scope and non-overlapping.
2. Every received page is preserved with its exact response bytes, requested and final URL, HTTP status, retrieval timestamp, parser version, and SHA-256. HTTP redirects are rejected before following; strict import and append-only publication require the final URL to equal the exact requested Sporttery endpoint and the redirect chain to be empty.
3. Any request, HTTP, schema, duplicate-conflict, or number-range error fails closed and retains diagnostics.
4. The receipt states fetch and strict-import outcomes, candidate and manifest hashes, pagination-completeness status, code commit, and that canonical data/model state was not modified.
5. No source response is treated as official authentication merely because it came from the configured endpoint or has a matching hash.
6. Canonical updates remain blocked unless the raw-page-backed totals attestation passes and correction/revision semantics, historical coverage, and the authorized source path have been reviewed.

## Operator path

Open **Actions → official-draw-sync-mvp → Run workflow** for an immediate probe. Download the `official-draw-sync-*` artifact and inspect `sync-receipt.json`, `fetch-error.txt`, raw page snapshots, and manifests. Do not manually copy candidate output into canonical history without completing the acceptance gates above.
