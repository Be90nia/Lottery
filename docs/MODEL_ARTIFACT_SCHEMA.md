# Content-addressed model artifacts

This document describes the version-1 model artifact and derived-cache contract implemented in `lottery.subset_model.artifact`.

## Canonical bytes and identity

- Artifact bodies are JSON data only. No pickle, executable object deserialization, or class reconstruction is performed.
- Canonical bytes use RFC 8785 JSON Canonicalization Scheme (JCS): UTF-8 output, UTF-16 code-unit object-key ordering, ECMAScript-compatible binary64 number formatting, and no insignificant whitespace.
- Duplicate JSON object keys, unpaired surrogates, NaN, positive/negative infinity, and unsupported Python values are rejected.
- Integer inputs are serialized through binary64 only when conversion is finite and exact. Thus exactly representable values such as `2^68` follow JCS number formatting, while values such as `2^53 + 1` are rejected rather than silently rounded.
- The SHA-256 identity is calculated over the canonical UTF-8 body **without** `artifact_id`. The completed envelope adds `artifact_id: "sha256:<lowercase-hex>"`.
- Verification checks the schema, recomputes the body digest, and requires the supplied bytes to equal the canonical serialization exactly.

Use `create_artifact(payload)` to produce canonical bytes and an ID. Use `verify_artifact(raw)` before consuming an artifact. Verification returns inert JSON data; it does not instantiate a model or grant serving eligibility.

## Model envelope

The version-1 envelope binds:

- schema version, artifact type, semantic model family, and front/back zone;
- exact legal subset support dimensions, cardinality, and canonical subset ordering;
- the feature schema and its content hash;
- the model configuration and its content hash;
- parameters in the declared feature-schema order;
- the exact normalization method and float64 log partition, or an explicit `not_computed` state for failed fits;
- fit terminal status, termination reason, iteration count, optimizer, objective and gradient diagnostics;
- training snapshot SHA-256, row count, first/last draw IDs, and inclusive chronological cutoff;
- code revision, runtime, dependency/library version map, and RNG algorithm;
- `forecast_ready: false`.

The top-level envelope and the support, training, implementation, feature-schema, model-configuration, normalization, fit, and parameter objects use closed registered field sets. A schema extension requires a versioned change; unknown fields are not silently incorporated into an existing model family.

### Fitted models

A `fitted_model` must have a converged fit, finite objective/gradient diagnostics, a recomputed gradient infinity norm within the registered (10^{-8}) tolerance, a valid exact-support normalizer, and family-specific parameters.

- `complete_subset_exponential`: finite `theta` values aligned exactly with active feature names, `objective_scale="mean_nll"`, and the frozen regularization value `lambda=1.0`.
- `conditional_poisson`: finite centered log weights, target and achieved first-order marginals, solver status, and a recomputed calibration residual within tolerance.

### Failed fits

A `fit_failure` is a diagnostic artifact, not a usable probability model. It must include a stable failure reason, explicit non-converged terminal status, `converged=false`, `parameters_available=false`, and normalization marked `not_computed`. The serializer rejects attempts to mark any artifact `forecast_ready=true`; lifecycle policy is the only authority that could later grant eligibility.

## Derived caches

A derived cache is a separate immutable content-addressed object. Its required envelope includes:

- `artifact_schema="lottery.derived-cache/v1"`;
- a non-empty cache type;
- the exact parent model `parent_artifact_id`;
- JSON-only cache payload;
- code revision and runtime metadata.

`create_derived_cache(payload)` hashes the canonical cache body without its own `artifact_id`. `verify_derived_cache(raw, expected_parent_artifact_id=...)` verifies canonical bytes, the cache digest, and—when supplied—the expected parent ID. A cache cannot be silently reused against a different model artifact.

## Population and source-evidence boundary

The current model envelope binds the pooled training population through its snapshot digest, row inventory, chronological range/cutoff, model configuration, and runtime/code provenance. It does **not** assert a physical lottery-ball identity. The reported set-index evidence remains a separate source-evidence ledger and is not promoted into a physical population key. Any future regime-conditioned artifact must introduce an explicit versioned population/evidence schema backed by adjudicated primary evidence; it must not infer a physical identity from a reported index.

## Validation

The CI suite includes shared Python/ECMAScript canonical-byte and SHA-256 fixtures, the finite RFC 8785 Appendix B binary64 vectors, invalid-number vectors, duplicate-key rejection, closed-schema tests, failed-fit artifact tests, parent-bound derived-cache tests, and the existing Windows ledger-lock checks.
