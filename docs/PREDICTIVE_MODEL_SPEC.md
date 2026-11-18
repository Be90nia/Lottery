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

L(θ) = −Σ_{S∈D} θᵀz(S) + n A(θ) + (λ/2)||θ||².

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

## 5. LOT-053 ball-set conditioning

LOT-053 is a distinct conditional experiment. It may reuse the exact model family and feature/optimizer specification above, but it must train on verified rows assigned to the relevant ball set only.

Before partitioning, prove the meaning and historical coverage of the source label. The repository's existing schema intentionally stores `source_equipment_count` as raw metadata and does not assert it is a ball-set ID. The legacy candidate's equipment codes are not adequate ground truth for three physical ball sets.

For each verified set g, compare:
- set-specific model trained only on g;
- pooled model trained on all otherwise eligible earlier rows;
- uniform reference;
- set-specific marginal baseline.

Use chronological cutoffs and report sample size, era coverage, missing labels, and fit eligibility at every target. Do not assume three separately trained models outperform the pooled model; splitting reduces training sample size.

The three-batch generator is a downstream interface only. It becomes active only if all three set-conditioned model slots pass the preregistered data, fit, calibration, and out-of-sample promotion gates.

## 6. Generation semantics after promotion

For request N, generate N tickets from each approved set-conditioned distribution and return 3N labeled rows. Default generation is weighted sampling from the normalized distribution, not a deterministic top-N ranking. Record model version, set label, training cutoff, snapshot hash, and random seed per batch. Do not silently replace failed model outputs with another model's output.

Legal ticket constraints: five distinct front numbers in 1..35 and two distinct back numbers in 1..12, displayed ascending. Cross-batch duplicate tickets are permitted and must not be silently removed; duplicate suppression changes the sampling distribution and would need a separately named mode.

## 7. Interpretation

Three separately labeled model outputs are three conditional forecasts, not three guaranteed independent sources of predictive edge. The lottery remains random; no result here establishes a recoverable PRNG seed, manipulation, or a physical mechanism. Negative and inconclusive results must be retained.
