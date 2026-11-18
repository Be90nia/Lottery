# Predictive model specification (LOT-051 / LOT-053)

**Status:** design specification for implementation and preregistration. No model in this document has been trained or promoted. The prospective LOT-042 protocol remains untouched.

## 1. Common probability space

Super Lotto tickets are modeled as two separate unordered subsets:

- Front zone: S_f ⊂ {1,…,35}, |S_f| = 5; support size C(35,5) = 324,632.
- Back zone: S_b ⊂ {1,…,12}, |S_b| = 2; support size C(12,2) = 66.

A ticket is a pair (S_f,S_b). The initial model assumes zone factorization:

P(S_f,S_b | history) = P_f(S_f | history) × P_b(S_b | history).

This is an explicit modeling assumption, not a claim that the physical drawing processes are causally independent. Report front and back scores separately. A joint dependence model is out of scope until separately preregistered.

The uniform reference assigns probability 1/C(35,5) to each front subset and 1/C(12,2) to each back subset.

## 2. LOT-051 complete-unordered-set candidate

For each zone independently, define a permutation-invariant feature vector. Do not use sorted display position as a predictive feature; sorted values are used only to calculate symmetric set summaries.

For a legal subset S = {x_1 < … < x_k}, define:

- sum(S) = Σ x_i;
- odd(S) = number of odd x_i;
- range(S) = x_k − x_1;
- adjacent(S) = Σ_{i=1}^{k−1} 1[x_{i+1} = x_i + 1];
- gap_var(S) = population variance of the k−1 internal gaps (x_{i+1} − x_i), when k > 1.

Use the first four features for both zones; include gap_var for the front zone as a fifth feature. For the back zone, the sole gap is exactly range, so gap_var is identically zero and must be omitted.

For each legal subset support, compute each feature's exact uniform-support mean μ_j and standard deviation σ_j by exhaustive enumeration. Define z_j(S) = (f_j(S) − μ_j)/σ_j. A zero-variance feature is omitted and documented. No empirical full-history standardization is allowed.

The candidate distribution is the regularized exponential family:

P_θ(S) = exp(θᵀ z(S) − A(θ)),
A(θ) = log Σ_{T in Ω} exp(θᵀ z(T)).

For a training window D with n observed subsets, fit θ by minimizing:

L(θ) = −(1/n)Σ_{S∈D} θᵀz(S) + A(θ) + (λ/2)||θ||².

Initial fixed implementation proposal: λ = 1.0, L-BFGS-B, zero initialization, maximum 5,000 iterations, gradient infinity-norm stopping tolerance 1e−8. These values are fixed design defaults, not tuned results. Any change must be made before the confirmatory evaluation is run and recorded in the preregistration; no target-wise, era-wise, or post-score tuning is permitted.

The normalizer must cover the complete legal support. To make repeated rolling-origin fitting tractable without approximation, implementations may aggregate identical feature vectors into (feature_vector, multiplicity) cells. Then:

Z(θ) = Σ_v multiplicity(v) exp(θᵀv).

This is mathematically identical to enumerating all legal subsets. Tests must compare aggregated and direct enumeration on small toy spaces and verify exact support multiplicities.

At θ = 0, the distribution must recover the uniform reference exactly (within numerical tolerance). Use stable log-sum-exp. Reject NaN, infinite, non-normalized, or negative probabilities.

## 3. Fixed comparators

Keep these as separately named models:

1. Uniform legal-subset reference.
2. Expanding-frequency marginal model, using only earlier draws, Dirichlet-style shrinkage α = 100 pseudo-draws.
3. EWMA marginal model, half-life 100 draws and α = 100 shrinkage.
4. LOT-051 complete-set exponential-family candidate.

For weighted-subset comparators, use the conditional-Poisson / rejective-sampling family P(S) ∝ ∏_{i∈S} w_i over all legal k-subsets, with w_i > 0. Calibrate log-weights by solving for the requested marginal inclusion probabilities under this fixed-size distribution (with one redundant scale degree of freedom removed, e.g. centering log-weights). Verify numerically that the resulting inclusion probabilities match the input marginals and sum to k. If the calibration fails or the target marginals are on an infeasible boundary, fail closed and report it; do not silently fall back to independent Bernoulli draws or arbitrary odds. This ensures the comparator preserves the fixed ticket size and the intended marginals.

No candidate may replace uniform merely because its top-ranked tickets look plausible. Score probability forecasts using exact-set negative log likelihood. Ticket hit counts are descriptive only.

## 4. Rolling-origin evaluation

- Freeze the exact input snapshot, SHA-256, code commit, feature definitions, regularization, optimizer, and bootstrap seed before evaluation.
- For every target t, use strictly earlier eligible draws only.
- Keep preprocessing and any fitted quantities inside the target's training window unless they are fixed from the legal combinatorial support itself.
- Use the 2,649 historical rolling-origin targets specified in LOT-051 only as historical research, not as prospective evidence.
- Do not inspect or use LOT-042 future outcomes; do not alter its 500-draw protocol.
- Report front and back primary log scores separately, absolute values, paired candidate-minus-uniform deltas, calibration and convergence diagnostics, and block-bootstrap uncertainty.
- LOT-051's primary bootstrap is 1,000 paired moving-block replicates, block length 50, fixed recorded seed. If any confirmatory multiplicity is introduced, declare the correction before evaluation.

The historical promotion gate remains the one in LOT-051: both zones must pass their preregistered criteria, and independent prospective confirmation is still required before user-facing promotion.

## 5. LOT-053 equipment-regime and ball-set conditioning

LOT-053 is a distinct conditional experiment. It may reuse the exact model family and feature/optimizer specification above, but it must train only on rows with authoritative per-draw ball-set evidence.

The historical equipment regime is not constant across the full dataset:
- The official 2007-06-04 launch-era procedure describes selecting one set from two formal sets.
- Official State General Administration of Sport material by 2019 describes three formal sets.
- The exact transition date, reason, and physical identity continuity/renumbering are not established.

This establishes a documented two-set procedure at launch and a three-set regime by 2019, but not the date or mechanism of transition. A 2019 official source also describes replacement of the “Venus” drawing machine after more than twelve years of service; that source does not say the ball sets changed at the same time, nor that the physical sets were renumbered. Machine replacement must not be used as evidence of ball-set replacement or continuity.

Every verified per-draw label must be scoped to an equipment regime. Do not create one timeless three-way partition by grouping all historical “set 1/2/3” indices. Do not assume index 1 in the two-set regime is physically identical to index 1 in the later three-set regime. See `docs/BALL_SET_LABEL_EVIDENCE.md` for the official source ledger and archival audit requirements.

The canonical `source_equipment_count` field remains raw metadata and is not an approved ball-set label. Only an explicit official per-draw announcement such as “本期使用第X套摇奖球”, preserved with source URL, retrieval timestamp, response hash, and parser version, can establish a row-level index. Missing or conflicting official labels remain unknown/conflicted; never infer them from draw order, neighboring draws, number patterns, or the raw equipment-count field.

For each eligible regime-scoped set slot g, compare:
- set-specific model trained only on verified rows in the same documented regime and set index;
- pooled model trained on all otherwise eligible earlier rows;
- uniform reference;
- regime/set-specific marginal baseline.

Use chronological cutoffs and report sample size, era coverage, missing labels, regime boundary assumptions, and fit eligibility at every target. Do not combine regimes to manufacture sample size. Do not assume separate set-conditioned models outperform the pooled model; splitting reduces training sample size.

The three-batch generator remains downstream and gated. It becomes active only if three distinct, contemporaneously meaningful, regime-compatible set-conditioned slots each pass the preregistered data, fit, calibration, and out-of-sample promotion gates. If historical evidence cannot establish three eligible slots within a coherent regime, the N → 3N behavior remains unavailable; do not duplicate pooled output or relabel two-set-era data to fill a slot.

## 6. Generation semantics after promotion

For request N, generate N tickets from each approved set-conditioned distribution and return 3N labeled rows. Default generation is weighted sampling from the normalized distribution, not a deterministic top-N ranking. Record model version, set label, training cutoff, snapshot hash, and random seed per batch. Do not silently replace failed model outputs with another model's output.

Legal ticket constraints: five distinct front numbers in 1..35 and two distinct back numbers in 1..12, displayed ascending. Cross-batch duplicate tickets are permitted and must not be silently removed; duplicate suppression changes the sampling distribution and would need a separately named mode.

## 7. Interpretation

Three separately labeled model outputs are three conditional forecasts, not three guaranteed independent sources of predictive edge. The lottery remains random; no result here establishes a recoverable PRNG seed, manipulation, or a physical mechanism. Negative and inconclusive results must be retained.


## 8. LOT-054 implementation artifact and numerical contract

The implementation must separate fit-time operations from forecast-time operations. Forecasting consumes a frozen, forecast-ready artifact; it must not silently refit. The engine must provide equivalent operations for canonical support enumeration, feature-table/moment construction, exponential-family fitting, exact-subset log-probability evaluation, weighted-subset marginal calibration, and deterministic sampling.

Every artifact must include:
- artifact schema version, model family, zone, population size, and selection size;
- feature schema version, ordered feature names, exact uniform-support means and population standard deviations;
- fitted theta (or centered log-weights for a weighted-subset model);
- training cutoff draw, training row count, training snapshot SHA-256, and code revision;
- optimizer/calibration configuration, convergence status, termination reason, objective, gradient infinity norm, and iteration count;
- for regularized exponential-family fits, `objective_scale="mean_nll"`, fixed `lambda`, unregularized mean NLL, and penalized objective; do not use the penalized objective as the forecast comparison score;
- numeric dtype, implementation/runtime version, and deterministic sampling algorithm identifier.

Do not make a dense support probability vector the only source of truth. Retain parameters and schemas sufficient to recompute probabilities. Any cached support/probability table is derived and must be hash-linked to the artifact. A failed or non-converged fit must never be marked forecast-ready.

Probability semantics and numerical acceptance:
- The primary scoring interface returns natural-log probabilities for exact unordered subsets. Reject malformed, duplicate, out-of-range, or wrong-cardinality subsets; do not silently sort/deduplicate invalid input.
- Use float64 and stable log-sum-exp for full-support normalization. Aggregated feature cells retain exact integer multiplicities whose sum equals the combinatorial support size.
- On small exhaustive fixtures, direct and aggregated log-partition and per-subset log-probability results must agree within 1e-10.
- On full supports, the float64 probability sum must be 1 within absolute tolerance 1e-12; theta=0 must recover -log(C(m,k)) within 1e-12.
- Reject NaN/Inf in inputs, parameters, objective, gradients, log probabilities, and calibration outputs. Never clip invalid values into a valid-looking distribution.
- Weighted-subset calibration requires strictly interior marginals, sum-to-k within 1e-10, and maximum absolute marginal error no greater than 1e-8. Boundary/infeasible targets and non-convergence fail closed; no independent-Bernoulli fallback.
- Deterministic replay is guaranteed only for the same artifact, RNG algorithm identifier, seed, and runtime/library version. Record all of them; do not claim cross-version bit identity.

Every fit exposes convergence status, termination reason, iterations, objective, gradient infinity norm, and finite-value checks. Hitting the iteration cap without meeting the 1e-8 gradient stopping criterion is a failed fit, not a forecast-ready artifact.

Benchmark support enumeration, feature-table construction, grouped log-partition/gradient, one fit, probability evaluation, and sampling separately. Report hardware/runtime, peak memory, warm-up policy, repetitions, median, and p95. Do not impose a machine-specific hard wall-clock gate; provide measurements sufficient to estimate LOT-055 rolling-origin cost.

Adversarial tests must cover invalid subsets, non-finite inputs, zero-variance features, extreme finite parameters, multiplicity mismatch, optimizer iteration-cap exit, infeasible weighted marginals, calibration non-convergence, artifact/schema mismatch, and deterministic replay.

This implementation contract does not authorize model promotion, LOT-055 evaluation before preregistration verification, LOT-042 access, or production activation.


## 9. Canonical forecast-artifact envelope

LOT-054 must serialize a versioned artifact envelope rather than relying on implementation-specific pickles or an opaque in-memory object. The following is the canonical logical shape (illustrative values only; implementations must populate actual fitted values):

```json
{
  "artifact_schema": "lottery.subset-probability-model/v1",
  "artifact_id": "sha256:<canonical-payload-hash>",
  "model_family": "regularized_exponential_subset",
  "zone": "front",
  "support": {
    "population_size": 35,
    "selection_size": 5,
    "support_count": 324632,
    "subset_order": "lexicographic_ascending"
  },
  "feature_schema": {
    "version": "lottery-set-features/v1",
    "names": ["sum", "odd", "range", "adjacent", "gap_var"],
    "uniform_means": ["..."],
    "uniform_population_stds": ["..."],
    "zero_variance_policy": "drop_and_record"
  },
  "parameters": {
    "theta": ["..."],
    "parameter_order": "feature_schema.names"
  },
  "normalization": {
    "method": "full_support_logsumexp",
    "log_partition": "...",
    "numeric_dtype": "float64"
  },
  "fit": {
    "status": "converged",
    "termination_reason": "gradient_tolerance",
    "objective": "...",
    "gradient_inf_norm": "...",
    "iterations": 0,
    "optimizer": "L-BFGS-B",
    "lambda": 1.0
  },
  "training": {
    "snapshot_sha256": "...",
    "row_count": 0,
    "first_draw_id": "...",
    "last_draw_id": "...",
    "cutoff_inclusive": true
  },
  "implementation": {
    "code_revision": "...",
    "runtime": "...",
    "library_versions": {},
    "rng_algorithm": "..."
  }
}
```

The example is a field contract, not a valid fitted artifact. The implementation must use RFC 8785 JSON Canonicalization Scheme (JCS) for artifact serialization: UTF-8 bytes, JCS property ordering/string escaping/number serialization, and rejection of NaN/Infinity or values outside the supported IEEE-754 binary64 domain. Do not substitute language-default `json.dumps(sort_keys=True)` or another serializer unless it is proven byte-identical to RFC 8785. Compute `artifact_id` as lowercase `sha256:` plus SHA-256 of the JCS bytes for the complete payload with the `artifact_id` member omitted. Verify canonicalization with published RFC 8785 test vectors and cross-language golden byte/hash fixtures. The hash must not depend on map insertion order or pretty-print whitespace. Parameters and schemas are the source of truth; cached support tables, probabilities, or marginal vectors are derived artifacts and must include the parent `artifact_id` plus their own content hash.

Model-family-specific parameter payloads must be explicit. For a weighted-subset model, use a distinct `model_family` and store centered per-item log weights, calibration target marginals, achieved marginals, solver status, and calibration residual; do not overload `theta` or imply it is an exponential-family feature model.

Forecast eligibility is a separate boolean/status decision derived from all checks, never inferred merely from successful serialization. A model with a failed fit, invalid artifact hash, mismatched support/feature schema, missing training snapshot provenance, or non-finite parameter is not forecast-ready.

For every forecast request, the generation ledger must reference the exact artifact ID and record the target draw ID (or an explicit non-draw simulation label), request ID, batch/slot ID, RNG algorithm, seed, and generated canonical subset. Never embed training rows or raw source files inside the model artifact.


## 10. Rolling-origin evaluation record contract

LOT-055 must write one immutable run manifest and one target record per zone/model/target combination. A target record must contain:
- `run_id`, `target_draw_id`, `zone`, `model_family`, `artifact_id` (nullable only for a non-fitted analytic baseline);
- `snapshot_sha256`, `training_first_draw_id`, `training_last_draw_id`, `training_row_count`, and a machine-checkable assertion that every training draw date is strictly earlier than the target date;
- model/configuration hash, feature schema hash, optimizer/solver status, convergence fields, and any failure reason;
- exact observed subset in canonical ascending form, predicted log probability, and negative log score;
- baseline/candidate pairing key so paired differences cannot accidentally compare different targets or different zones.

The run manifest must pin the snapshot path/hash/row count/draw range, target list hash, code revision, environment/library versions, model-spec/preregistration revision, bootstrap replicate count (1,000), block length (50), bootstrap seed, metric definitions, and exact comparison directions. Each target must appear exactly once for every expected model and zone, including failed fits. A failed fit has an explicit failure record and no fabricated score; the report must disclose its count and must not silently shrink the candidate's target set.

For each zone and candidate-vs-baseline comparison, compute per-target paired score differences on the intersection of valid, predeclared target records only. Also report the complete expected-target denominator and every exclusion reason. The promotion gate must not be satisfied by selectively dropping targets or by comparing models on different target sets.

Calibration diagnostics are descriptive checks on the same chronological predictions; they do not replace exact-set log score. The moving-block bootstrap must resample contiguous blocks of the ordered paired-difference series, with deterministic boundary handling documented and tested. Report the point estimate and two-sided 95% interval. No iid row bootstrap is permitted.


## 11. LOT-054 language-neutral engine API contract

The library may choose its language and concrete type system, but it must expose equivalent pure/stateless operations with these semantics:

| Operation | Input | Output / invariant |
|---|---|---|
| `enumerate_support(m, k)` | integers `m >= k >= 1` | Every k-subset exactly once, ascending tuple, deterministic lexicographic order |
| `validate_subset(S, m, k)` | candidate subset | Accept only exactly k distinct integer members in [1,m]; do not repair invalid input |
| `extract_features(S, zone)` | validated subset, feature schema | Ordered finite feature vector; permutation invariant |
| `uniform_feature_stats(m, k, schema)` | support/schema | Exact or reproducibly high-precision mean, population variance/std, and zero-variance mask over the uniform legal support |
| `aggregate_feature_cells(m, k, schema)` | support/schema | Feature-vector → exact positive integer multiplicity; multiplicities sum to C(m,k) |
| `log_partition(theta, cells)` | finite theta, validated cells | Stable log Z and expected standardized feature vector under Pθ |
| `log_probability(S, artifact)` | validated subset, forecast-ready artifact | Natural log probability for that exact unordered subset |
| `fit_exponential(train_subsets, config)` | canonical training subsets and frozen config | Fitted artifact plus full optimizer diagnostics; failed convergence is not forecast-ready |
| `calibrate_weighted_subset(target_marginals, config)` | strictly interior feasible marginals summing to k | Centered log weights, achieved marginals, residual, solver diagnostics; otherwise explicit failure |
| `sample_subsets(artifact, n, rng)` | forecast-ready artifact, n >= 0, injected RNG | n legal subsets sampled from the exact normalized distribution; no hidden global RNG |
| `score_subsets(subsets, artifact)` | validated observed subsets and artifact | Aligned finite log-probability vector; preserve input row order |

Every operation must reject invalid dimensions, schema mismatches, duplicate or out-of-range elements, NaN/Infinity, and corrupted multiplicity totals with typed errors. It must not silently coerce floats to integers, sort-and-deduplicate malformed subsets, clip invalid probabilities, or fall back to another model family.

Front and back are separate calls with support (35,5) and (12,2). The combined ticket distribution is the declared factorized product assumption only; the engine must not imply a learned cross-zone dependence. All public APIs must be deterministic for fixed inputs except `sample_subsets`, whose randomness is fully injected and recorded.

Implementations should expose a lightweight support descriptor so callers can query support size and schema without materializing all subsets. The complete front support is small enough for exact enumeration (324,632 subsets); no Monte Carlo approximation is permitted for the preregistered full-support normalizer or exact uniform moments.

## 12. Exact conditional-Poisson normalization and calibration

For the fixed-size weighted-subset family, define positive item weights w_i = exp(η_i), with the scale gauge fixed by Σ_i η_i = 0. The normalizer is the elementary symmetric polynomial

e_k(w_1,…,w_m) = Σ_{S:|S|=k} ∏_{i∈S} w_i.

The probability of subset S is ∏_{i∈S}w_i / e_k(w). This is a fixed-size distribution, not independent Bernoulli sampling.

An implementation may use full subset enumeration, or the exact dynamic-programming recurrence below. It must not approximate the normalizer:

- E[i,0] = 1; E[0,j>0] = 0.
- E[i,j] = E[i−1,j] + w_i E[i−1,j−1].
- Compute in log space using logaddexp to avoid overflow/underflow.
- The final log normalizer is log E[m,k].
- The inclusion marginal is π_i = w_i e_{k−1}(w_{−i}) / e_k(w), computed with prefix/suffix DP or an equivalently exact stable method.

Calibration minimizes the convex log-partition dual A(η) − ηᵀπ_target under the zero-sum gauge, where A=log e_k(exp η). The target must satisfy 0 < π_i < 1 and Σ_i π_i = k within a declared input tolerance. A boundary target, non-finite value, wrong sum, or solver non-convergence is an explicit failure. After calibration, independently recompute achieved marginals and require max absolute residual ≤ 1e−8; record both target and achieved vectors, solver status, objective, gradient norm, iteration count, and residual. Never silently renormalize invalid targets or accept a fit based only on optimizer success.

For exact sampling, use the same prefix DP to choose whether item i is included conditional on the remaining selection count while traversing i from m down to 1, with probability w_i E[i−1,r−1] / E[i,r] (or an algebraically equivalent reverse traversal). Inject the RNG; return exactly k distinct indices. Tests must compare DP normalizers and marginals with brute-force enumeration for small m,k, verify permutation equivariance, and verify empirical sampling frequencies against exact marginals within predeclared Monte Carlo tolerance. The Monte Carlo check validates the sampler only; it must never replace exact normalization or calibration.

## 13. Exact marginal semantics for the expanding and EWMA baselines

The marginal baselines must output a fixed-size subset distribution through the conditional-Poisson calibration in Section 12; they must not independently sample Bernoulli indicators.

For a zone with population m, selection size k, n earlier training draws, and inclusion count c_i for item i, define the expanding-frequency target marginal:

π_i = (c_i + α k/m) / (n + α), with α=100.

This is a uniform-prior shrinkage of the empirical inclusion rates. It guarantees 0<π_i<1 and Σ_i π_i=k for finite n.

For EWMA with half-life h=100 draws, assign each prior training draw s at chronological lag ℓ_s (most recent lag 0) weight a_s=2^(−ℓ_s/h). Define W=Σ_s a_s and C_i=Σ_s a_s 1[i∈S_s]. Then:

π_i = (C_i + α k/m) / (W + α), with α=100.

The EWMA weights and counts use only draws strictly earlier than the target. The same fixed-size sum and interior constraints hold. Both target-marginal vectors are passed to the exact conditional-Poisson calibration routine; store the input target marginals, calibrated log weights, achieved marginals, and residual. If calibration fails, record a failed baseline for that target; do not replace it with independent Bernoulli sampling or silently substitute the uniform model.

These formulas are the frozen baseline semantics. Do not retune α or h per target, zone, regime, or observed performance.

### Regularization scale invariant across rolling-origin training sizes

The objective is the mean per-observation negative log likelihood plus the fixed L2 penalty, not the summed negative log likelihood. This keeps the effective regularization strength constant as the expanding training window grows from the minimum 300 draws to later cutoffs. The fixed default λ=1.0 is interpreted on this mean-loss scale and is not retuned by target, zone, or era.

Report both the unregularized mean NLL and penalized objective for each fit. The optimizer gradient is the mean-likelihood gradient plus λθ. Add a property test that exact replication of every training row leaves the mean objective, gradient, and fitted optimum unchanged (up to numerical tolerance); this catches accidental reintroduction of a summed-loss penalty. This is a design correction made before confirmatory evaluation; no historical target scores have been inspected to choose it.
## 14. Frozen snapshot availability and digest gate

The exact 2,949-row snapshot exists on `lot-050-official-snapshot-archive` at `data/processed/draws-20261118.jsonl`. SHA-256 independently recomputed over its exact UTF-8 bytes is `9f4cc51b76fd258dd056e0b86f675192d3d9a41c2901f771cab778c65ec2b6aa`, matching LOT-051/#13; byte count is 1,003,831 and the file has 2,949 unique IDs from 07001–26131 (2007-05-30–2026-11-16). The sidecar's stale output digest has been corrected in archive-branch commit `cbd5f5eac634ab12edc3fdda3c844f811587f6fd`; the JSONL bytes were not modified. The evaluation runner must pin this exact commit or an identical content-addressed artifact because the file is not on `main` or the model-design branch. Preserve `trust_status=manifest_complete_not_officially_authenticated`; capture provenance completeness does not establish independent official authentication. Reject the separate 2,901-row unverified legacy candidate. Continue exact hash, row count, unique ID, and boundary checks.
Structural preflight assertions for LOT-055: parse exactly 2,949 JSONL rows; require 2,949 unique IDs; strictly increasing draw IDs and dates; each front subset exactly five distinct ascending integers in 1..35; each back subset exactly two distinct ascending integers in 1..12; first target 09054 at zero-based index 300 with exactly 300 earlier rows; and exactly 2,649 targets through 26131. These checks supplement, and do not replace, the frozen byte hash or provenance trust classification.