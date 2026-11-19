# Ticket MVP batch contract

## Request and count semantics

`scripts/generate_tickets.py DATASET --tickets N --seed S` generates three explicitly named exploratory strategy lanes: `uniform`, `expanding`, and `ewma`. Each lane contains exactly N legal tickets; the complete output therefore contains exactly 3N tickets. N must be an integer in 1..100. Booleans, zero, negative values, and values above the cap are rejected by the Python API.

These are three computational strategies, **not three physical ball-set identities** and not three independently validated predictive models. The 3N contract is a development MVP contract only. It must not be presented as the approved physical three-set generator from LOT-053/057; that activation remains blocked on authoritative labels and three eligible model artifacts.

## Provenance

Every result records:
- deterministic generation run ID derived from canonical training rows, seed, N, alpha, half-life, strategy order, and sampler version;
- canonical training-data fingerprint and exact file SHA-256 in the CLI dataset block;
- master seed, algorithm identifier, and deterministic slot-seed derivation;
- per-strategy slot seed, model label, ticket count, training cutoff draw ID, and sampling method;
- stable ticket IDs derived from the run ID, strategy label, and within-lane ticket index.

Identical canonical inputs and parameters reproduce the same run ID, ticket IDs, and ticket values. The exact file SHA-256 additionally records byte-level input identity.

## Sampling limitations

The current sampler performs sequential weighted sampling without replacement inside each 5-number or 2-number subset. It is a reproducible marginal-weighted heuristic, not the exact conditional-Poisson sampler and not a calibrated joint ticket probability. The output explicitly records this limitation. No claim of predictive advantage or guaranteed result is made.

Cross-lane and within-lane duplicate tickets are preserved; no hidden deduplication or reroll is performed.


## One-command MVP runner

Use `python scripts/run_mvp.py --dataset PATH --tickets-per-strategy N --seed S --output mvp-output.json` to execute validation and candidate generation as one atomic output operation. The JSON document contains the batch and a receipt binding the exact input file SHA-256, deterministic generation run ID, batch SHA-256, code commit when available, timestamp, and published count. The receipt explicitly records that automatic source sync, model training, and model promotion were not performed. Invalid input or generation failure leaves no published output file.


Run receipts require an explicit full code commit SHA (or the GitHub Actions `GITHUB_SHA`) and the runner refuses to overwrite an existing output file. Use a fresh output path for each generation so earlier receipts remain available for audit.
