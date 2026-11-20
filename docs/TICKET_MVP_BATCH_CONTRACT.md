# Ticket MVP batch contract

## Request and count semantics

`scripts/generate_tickets.py DATASET --tickets N --seed S` generates three explicitly named exploratory strategy lanes: `uniform`, `expanding`, and `ewma`. Each lane contains exactly N legal tickets; the complete output therefore contains exactly 3N tickets. N must be an integer in 1..100. Booleans, zero, negative values, and values above the cap are rejected by the Python API.

These are three computational strategies, **not three physical ball-set identities** and not three independently validated predictive models. The 3N contract is a development MVP contract only. It must not be presented as the approved physical three-set generator from LOT-053/057; that activation remains blocked on authoritative labels and three eligible model artifacts.

## Provenance

Every result records:
- deterministic generation run ID derived from canonical training rows, seed, N, alpha, half-life, strategy order, sampler version, and code commit;
- canonical training-data fingerprint and exact file SHA-256 in the CLI dataset block;
- master seed, algorithm identifier, and deterministic slot-seed derivation;
- per-strategy slot seed, model label, ticket count, training cutoff draw ID, sampling method, unique-combination count, and duplicate-ticket count;
- batch-wide unique-combination, duplicate-ticket, and cross-lane duplicate-combination counts;
- stable ticket IDs derived from the code-addressed run ID, strategy label, and within-lane ticket index.

Identical canonical inputs and parameters reproduce the same run ID, ticket IDs, and ticket values. The exact file SHA-256 additionally records byte-level input identity.

## Sampling semantics and limitations

The current implementation calibrates each lane's requested first-order inclusion marginals to an exact fixed-size conditional-Poisson (rejective) distribution, then samples subsets with the exact backward sampler. The calibration must converge and an independent marginal recomputation must meet the frozen maximum absolute residual tolerance of `1e-8`; otherwise generation fails closed.

This is a coherent joint distribution over legal fixed-size subsets, but its higher-order dependence structure is a rejective-sampling assumption. It is not evidence of the physical lottery mechanism and does not establish predictive advantage. The three lanes remain historical marginal heuristics, not physical ball-set models or three independently validated predictive models.

The batch uses Python `random.Random` (MT19937) with deterministic lane seed derivation for reproducible research output. This is not a cryptographically secure randomness source and is not suitable as a security boundary. Cross-lane and within-lane duplicate tickets are preserved; no hidden deduplication or reroll is performed. No claim of predictive advantage or guaranteed result is made.


## One-command MVP runner

Use `python scripts/run_mvp.py --dataset PATH --tickets-per-strategy N --seed S --code-commit SHA --output mvp-output.json` to execute validation and candidate generation as one atomic output operation. A full code commit is required (or supplied by GitHub Actions as `GITHUB_SHA`) and is bound into the generation run ID and ticket IDs. The JSON document contains the batch and a receipt binding the exact input file SHA-256, deterministic generation run ID, batch SHA-256, code commit, timestamp, and published count. The receipt explicitly records that automatic source sync, model training, and model promotion were not performed. Existing output paths are never overwritten; invalid input or generation failure leaves no published output file.
