# Automatic official draw sync — MVP boundary

## Current operating mode

The `official-draw-sync-mvp` GitHub Actions workflow is currently **manual-only** (`workflow_dispatch`). Its former daily schedule was disabled to conserve the Actions budget and because the official source-completeness and authentication gates are not yet satisfied. Do not describe it as an unattended daily updater until the schedule is deliberately restored after those gates pass.

A manual run invokes the strict Sporttery history collector in an isolated per-run directory `sync-run/raw/<run_id>/`, preserving raw response snapshots and per-page SHA-256 manifests with requested URL, final URL, and redirect-chain evidence. The collector rejects HTTP redirects before following them. The fetch receipt's `raw_dir` is checked to remain beneath the isolated run root, and strict import consumes only that directory. It then re-imports archived pages with `--require-manifests` to build a validated candidate JSONL plus its output manifest. The workflow next runs `scripts/reconcile_draws.py` against the pinned 2,949-row baseline and exact isolated raw snapshot directory.

The append-only gate re-parses every raw page, verifies the source totals attestation, compares the candidate against every historical row, rejects corrections/missing rows/chronology regressions, and writes a separate append-only candidate artifact plus receipt when the full check passes. Strict import binds each sidecar's `page_no` to the URL's `pageNo`, requires the same `gameNo=85`, `provinceId=0`, `isVerify=1` and `pageSize` across all pages, requires a single fetch `run_id`, and rejects missing or duplicate page numbers in the observed inventory. When page 1 supplies positive integer `value.total` and `value.totalPage`, the importer checks the ceiling relation, every page's expected record count, the complete page inventory, and the deduplicated draw count, then emits a raw-page-backed pagination attestation. If those fields are absent, completeness remains unverified; inconsistent totals fail closed.

The workflow is read-only with respect to the repository: it has `contents: read`, checkout credentials are disabled, and it never commits or replaces canonical history. A completed fetch, strict import, and append-only gate is labeled `append_candidate_ready_untrusted`, not authenticated official data. The append gate can report `no_new_draws` or produce a full append-only candidate, but neither result mutates canonical history. A network, HTTP, parsing, or validation failure produces an evidence artifact and a visibly failed run.

## Why unattended canonical updating remains blocked

The official endpoint has previously returned HTTP 567 from GitHub-hosted runners. A successful fetch and internally consistent pagination receipt do not, by themselves, authenticate the source or prove that its historical inventory is authoritative. Until an authorized source path is consistently reachable and completeness can be independently established, automatically publishing fetched rows would risk silently truncating or corrupting history.

The workflow therefore archives candidate evidence only; it does not publish canonical history, write forecast/outcome ledgers, train models, promote a model, or consume the isolated LOT-042 prospective holdout. Its output is a run artifact rather than a canonical repository update.

The collector's stopping on an empty or short page is not, by itself, proof that all historical pages were returned. Before promoting this workflow to unattended canonical sync, the project must add and test source-side completeness reconciliation, monotonic draw-ID/date checks across the entire page set, correction/revision event handling, and an append-only canonical update transaction. The authorized source path and source authority classification also require review.

## MVP acceptance gates

1. The current workflow is manual-only and non-overlapping. Any return to a schedule requires an explicit change after source and budget gates pass.
2. Every received page is preserved with exact response bytes, metadata, requested and final URL, HTTP status, retrieval timestamp, parser version, and SHA-256. HTTP redirects are rejected before following; strict import and append-only publication require the final URL to equal the exact requested Sporttery endpoint and the redirect chain to be empty.
3. Any request, HTTP, schema, duplicate-conflict, or number-range error fails closed and retains diagnostics.
4. The receipt states fetch and strict-import outcomes, candidate and manifest hashes, pagination-completeness status, code commit, and that canonical data/model state was not modified.
5. No source response is treated as official authentication merely because it came from the configured endpoint or has a matching hash.
6. Canonical updates remain blocked unless raw-page-backed totals attestation passes and correction/revision semantics, historical coverage, and the authorized source path have been reviewed.
7. Re-enabling unattended runs additionally requires an operationally sustainable Actions budget and alerting/retention review.

## Operator path

Open **Actions → official-draw-sync-mvp → Run workflow** for an immediate probe. Download the `official-draw-sync-*` artifact and inspect `sync-receipt.json`, `fetch-error.txt`, raw page snapshots, and manifests. Do not manually copy candidate output into canonical history without completing the acceptance gates above.
