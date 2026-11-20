"""RFC 8785 JSON Canonicalization and content-addressed model artifacts.

The canonicalizer intentionally accepts only JSON data-model values and
rejects non-finite or unsafe numbers. It does not deserialize executable
objects and does not make an artifact forecast-ready.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any


class ArtifactValidationError(ValueError):
    """Raised for malformed, unsupported, or untrusted model artifacts."""


def _number_to_jcs(value: int | float) -> str:
    if type(value) is int:
        try:
            binary64_value = float(value)
        except OverflowError as exc:
            raise ArtifactValidationError(
                "integer cannot be represented as finite IEEE-754 binary64"
            ) from exc
        if not math.isfinite(binary64_value) or int(binary64_value) != value:
            raise ArtifactValidationError(
                "integer cannot be represented exactly as IEEE-754 binary64"
            )
        value = binary64_value
    if type(value) is not float or not math.isfinite(value):
        raise ArtifactValidationError("JSON numbers must be finite int/float values")
    if value == 0.0:
        return "0"

    negative = value < 0
    source = repr(abs(value)).lower()
    if "e" in source:
        mantissa, exponent_text = source.split("e", 1)
        exponent = int(exponent_text)
    else:
        mantissa = source
        exponent = 0

    if "." in mantissa:
        integer_part, fractional_part = mantissa.split(".", 1)
        digits = integer_part + fractional_part
        decimal_position = len(integer_part) + exponent
    else:
        digits = mantissa
        decimal_position = len(digits) + exponent

    while len(digits) > 1 and digits.startswith("0"):
        digits = digits[1:]
        decimal_position -= 1
    while len(digits) > 1 and digits.endswith("0"):
        digits = digits[:-1]

    magnitude = abs(value)
    if 1e-6 <= magnitude < 1e21:
        if decimal_position <= 0:
            rendered = "0." + ("0" * (-decimal_position)) + digits
        elif decimal_position >= len(digits):
            rendered = digits + ("0" * (decimal_position - len(digits)))
        else:
            rendered = digits[:decimal_position] + "." + digits[decimal_position:]
    else:
        scientific_exponent = decimal_position - 1
        mantissa_out = digits[0]
        if len(digits) > 1:
            mantissa_out += "." + digits[1:]
        sign = "+" if scientific_exponent >= 0 else ""
        rendered = mantissa_out + "e" + sign + str(scientific_exponent)
    return "-" + rendered if negative else rendered


def _quote_string(value: str) -> str:
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ArtifactValidationError("strings must not contain unpaired surrogates") from exc
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _is_finite_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _canonical(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if type(value) in (int, float):
        return _number_to_jcs(value)
    if isinstance(value, str):
        return _quote_string(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canonical(item) for item in value) + "]"
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ArtifactValidationError("object keys must be strings")
        ordered_keys = sorted(value, key=lambda key: key.encode("utf-16-be", errors="strict"))
        return "{" + ",".join(
            _quote_string(key) + ":" + _canonical(value[key]) for key in ordered_keys
        ) + "}"
    raise ArtifactValidationError(f"unsupported JSON value type: {type(value).__name__}")


def canonicalize(value: Any) -> bytes:
    """Return RFC 8785-style canonical UTF-8 bytes for supported JSON values."""
    return _canonical(value).encode("utf-8")


def _reject_constant(value: str):
    raise ArtifactValidationError(f"non-finite JSON constant is forbidden: {value}")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactValidationError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def parse_json_strict(raw: bytes | str) -> dict:
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        value = json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactValidationError("artifact is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ArtifactValidationError("model artifact root must be a JSON object")
    return value


def validate_model_artifact(payload: dict) -> None:
    """Validate the complete Section 9 artifact envelope and family payload."""
    required = {
        "schema_version", "artifact_schema", "artifact_type", "model_family", "zone",
        "population_size", "selection_size", "support", "feature_schema",
        "parameters", "model_configuration", "normalization", "fit", "training", "implementation",
        "training_snapshot_sha256", "training_cutoff_draw_id",
        "training_row_count", "code_revision", "runtime", "fit_diagnostics",
        "forecast_ready", "feature_schema_hash", "model_configuration_hash",
    }
    missing = required.difference(payload)
    if missing:
        raise ArtifactValidationError(f"missing required artifact fields: {sorted(missing)}")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ArtifactValidationError("unsupported model artifact schema_version")
    if payload["artifact_schema"] != "lottery.subset-probability-model/v1":
        raise ArtifactValidationError("unsupported artifact envelope schema")
    if payload["zone"] == "front":
        expected = (35, 5)
    elif payload["zone"] == "back":
        expected = (12, 2)
    else:
        raise ArtifactValidationError("zone must be 'front' or 'back'")
    family = payload["model_family"]
    if family not in ("complete_subset_exponential", "conditional_poisson"):
        raise ArtifactValidationError("unknown model_family")
    if (payload["population_size"], payload["selection_size"]) != expected:
        raise ArtifactValidationError("zone support dimensions do not match the lottery rules")

    support = payload["support"]
    if not isinstance(support, dict) or set(support) != {
        "population_size", "selection_size", "support_count", "subset_order"
    } or (
        support.get("population_size") != expected[0]
        or support.get("selection_size") != expected[1]
        or support.get("support_count") != math.comb(*expected)
        or support.get("subset_order") != "lexicographic_ascending"
    ):
        raise ArtifactValidationError("support descriptor does not match the exact legal subset space")

    if type(payload["training_row_count"]) is not int or payload["training_row_count"] < 1:
        raise ArtifactValidationError("training_row_count must be a positive integer")
    if (not isinstance(payload["training_snapshot_sha256"], str)
            or len(payload["training_snapshot_sha256"]) != 64
            or any(char not in "0123456789abcdef" for char in payload["training_snapshot_sha256"])):
        raise ArtifactValidationError("training_snapshot_sha256 must be 64 lowercase hexadecimal characters")
    if not isinstance(payload["training_cutoff_draw_id"], str) or not payload["training_cutoff_draw_id"]:
        raise ArtifactValidationError("training_cutoff_draw_id must be a non-empty string")
    if (not isinstance(payload["code_revision"], str) or len(payload["code_revision"]) != 40
            or any(char not in "0123456789abcdef" for char in payload["code_revision"])):
        raise ArtifactValidationError("code_revision must be a full lowercase 40-character Git SHA")
    for hash_field in ("feature_schema_hash", "model_configuration_hash"):
        value = payload.get(hash_field)
        if (not isinstance(value, str) or not value.startswith("sha256:")
                or len(value) != 71
                or any(char not in "0123456789abcdef" for char in value[7:])):
            raise ArtifactValidationError(f"{hash_field} must be a lowercase sha256 content identifier")
    if not isinstance(payload["runtime"], dict) or not isinstance(payload["fit_diagnostics"], dict):
        raise ArtifactValidationError("runtime and fit_diagnostics must be objects")
    for diagnostic_name in (
        "gradient_infinity_norm", "unregularized_mean_nll", "penalized_objective",
        "objective", "calibration_residual",
    ):
        diagnostic_value = payload["fit_diagnostics"].get(diagnostic_name)
        if diagnostic_value is not None and not _is_finite_number(diagnostic_value):
            raise ArtifactValidationError(
                f"fit_diagnostics.{diagnostic_name} must be finite numeric or null"
            )
    if type(payload["forecast_ready"]) is not bool:
        raise ArtifactValidationError("forecast_ready must be boolean")
    if payload["forecast_ready"]:
        raise ArtifactValidationError(
            "serialization cannot confer forecast readiness; readiness belongs to lifecycle policy"
        )

    training = payload["training"]
    if not isinstance(training, dict) or set(training) != {
        "snapshot_sha256", "row_count", "first_draw_id", "last_draw_id",
        "cutoff_draw_id", "cutoff_inclusive",
    } or (
        training.get("snapshot_sha256") != payload["training_snapshot_sha256"]
        or training.get("row_count") != payload["training_row_count"]
        or training.get("cutoff_draw_id") != payload["training_cutoff_draw_id"]
        or training.get("cutoff_inclusive") is not True
        or not isinstance(training.get("first_draw_id"), str)
        or not isinstance(training.get("last_draw_id"), str)
        or len(training["first_draw_id"]) != 5 or not training["first_draw_id"].isdigit()
        or len(training["last_draw_id"]) != 5 or not training["last_draw_id"].isdigit()
        or training["first_draw_id"] > training["last_draw_id"]
        or training["last_draw_id"] != training["cutoff_draw_id"]
        or payload.get("training_first_draw_id", training["first_draw_id"]) != training["first_draw_id"]
        or payload.get("training_last_draw_id", training["last_draw_id"]) != training["last_draw_id"]
    ):
        raise ArtifactValidationError("training provenance envelope is inconsistent")

    implementation = payload["implementation"]
    if not isinstance(implementation, dict) or set(implementation) != {
        "code_revision", "runtime", "library_versions", "rng_algorithm",
    } or (
        implementation.get("code_revision") != payload["code_revision"]
        or implementation.get("runtime") != payload["runtime"]
        or not isinstance(implementation.get("library_versions"), dict)
        or not isinstance(implementation.get("rng_algorithm"), str)
        or not implementation["rng_algorithm"]
    ):
        raise ArtifactValidationError("implementation/runtime/RNG provenance is incomplete")

    feature_schema = payload["feature_schema"]
    feature_schema_fields = {
        "version", "names", "uniform_means", "uniform_population_stds", "zero_variance_policy"
    }
    if family == "complete_subset_exponential":
        feature_schema_fields |= {"candidate_names", "zero_variance_features"}
    if not isinstance(feature_schema, dict) or set(feature_schema).difference(feature_schema_fields):
        raise ArtifactValidationError("feature_schema must use only registered schema fields")
    names = feature_schema.get("names")
    means = feature_schema.get("uniform_means")
    standard_deviations = feature_schema.get("uniform_population_stds")
    if (not isinstance(feature_schema.get("version"), str) or not feature_schema["version"]
            or not isinstance(names, list) or any(not isinstance(name, str) or not name for name in names)
            or len(set(names)) != len(names)
            or not isinstance(means, list) or not isinstance(standard_deviations, list)
            or len(means) != len(names) or len(standard_deviations) != len(names)
            or not isinstance(feature_schema.get("zero_variance_policy"), str)
            or not feature_schema["zero_variance_policy"]):
        raise ArtifactValidationError("feature schema names/moments/policy are invalid")
    for value in means + standard_deviations:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ArtifactValidationError("feature schema moments must be finite numeric values")
    if any(value < 0 for value in standard_deviations):
        raise ArtifactValidationError("feature standard deviations cannot be negative")
    expected_feature_hash = "sha256:" + hashlib.sha256(canonicalize(feature_schema)).hexdigest()
    if payload["feature_schema_hash"] != expected_feature_hash:
        raise ArtifactValidationError("feature_schema_hash does not bind the canonical feature schema")
    model_configuration = payload["model_configuration"]
    model_configuration_fields = {
        "model_family", "zone", "population_size", "selection_size", "feature_schema_hash"
    }
    if family == "complete_subset_exponential":
        model_configuration_fields |= {
            "objective_scale", "regularization_lambda", "solver",
            "max_iterations", "gradient_tolerance",
        }
    else:
        model_configuration_fields |= {"baseline", "alpha", "half_life", "weighting"}
    if (not isinstance(model_configuration, dict)
            or set(model_configuration).difference(model_configuration_fields)):
        raise ArtifactValidationError("model_configuration must use only registered family fields")
    expected_config_hash = "sha256:" + hashlib.sha256(canonicalize(model_configuration)).hexdigest()
    if payload["model_configuration_hash"] != expected_config_hash:
        raise ArtifactValidationError("model_configuration_hash does not bind the canonical configuration")
    if (model_configuration.get("model_family") != payload["model_family"]
            or model_configuration.get("zone") != payload["zone"]
            or model_configuration.get("population_size") != expected[0]
            or model_configuration.get("selection_size") != expected[1]
            or model_configuration.get("feature_schema_hash") != payload["feature_schema_hash"]):
        raise ArtifactValidationError("model_configuration does not match artifact identity/schema")
    if family == "complete_subset_exponential":
        if (model_configuration.get("objective_scale") != "mean_nll"
                or not _is_finite_number(model_configuration.get("regularization_lambda"))
                or model_configuration["regularization_lambda"] != 1.0
                or not isinstance(model_configuration.get("solver"), str)
                or not model_configuration["solver"]
                or type(model_configuration.get("max_iterations")) is not int
                or model_configuration["max_iterations"] < 1
                or not _is_finite_number(model_configuration.get("gradient_tolerance"))
                or model_configuration["gradient_tolerance"] <= 0):
            raise ArtifactValidationError("exponential model configuration is invalid")
    else:
        if (not isinstance(model_configuration.get("baseline"), str)
                or not model_configuration["baseline"]
                or not _is_finite_number(model_configuration.get("alpha"))
                or model_configuration["alpha"] <= 0
                or (model_configuration.get("half_life") is not None
                    and (not _is_finite_number(model_configuration["half_life"])
                         or model_configuration["half_life"] <= 0))
                or not isinstance(model_configuration.get("weighting"), str)
                or not model_configuration["weighting"]):
            raise ArtifactValidationError("conditional-Poisson model configuration is invalid")

    artifact_type = payload["artifact_type"]
    if artifact_type not in ("fitted_model", "fit_failure"):
        raise ArtifactValidationError("artifact_type must be fitted_model or fit_failure")
    allowed_fields = required | {"training_first_draw_id", "training_last_draw_id"}
    if family == "complete_subset_exponential":
        allowed_fields |= {
            "feature_schema_version", "candidate_feature_names", "active_feature_names",
            "zero_variance_features", "theta", "objective_scale", "regularization_lambda",
        }
    else:
        allowed_fields |= {
            "baseline", "alpha", "half_life",
            "centered_log_weights", "target_marginals", "achieved_marginals",
            "solver_status", "calibration_residual",
        }
    if artifact_type == "fit_failure":
        allowed_fields.add("failure_reason")
    unknown_fields = set(payload).difference(allowed_fields)
    if unknown_fields:
        raise ArtifactValidationError(
            f"unknown artifact fields for {family}/{artifact_type}: {sorted(unknown_fields)}"
        )
    normalization = payload["normalization"]
    if (not isinstance(normalization, dict)
            or set(normalization) != {"method", "log_partition", "numeric_dtype"}
            or normalization.get("numeric_dtype") != "float64"):
        raise ArtifactValidationError("normalization descriptor is invalid")
    if artifact_type == "fit_failure":
        if normalization.get("method") != "not_computed" or normalization.get("log_partition") is not None:
            raise ArtifactValidationError("failed fit artifact must explicitly mark normalization as not computed")
    elif (not isinstance(normalization.get("method"), str) or not normalization["method"]
          or type(normalization.get("log_partition")) not in (int, float)
          or not math.isfinite(normalization["log_partition"])):
        raise ArtifactValidationError("normalization descriptor is invalid")

    fit = payload["fit"]
    if not isinstance(fit, dict) or set(fit) != {
        "status", "termination_reason", "objective", "gradient_inf_norm",
        "iterations", "optimizer", "lambda",
    } or (
        not isinstance(fit.get("status"), str) or not fit["status"]
        or not isinstance(fit.get("termination_reason"), str) or not fit["termination_reason"]
        or type(fit.get("iterations")) is not int or fit["iterations"] < 0
        or not isinstance(fit.get("optimizer"), str) or not fit["optimizer"]
    ):
        raise ArtifactValidationError("fit diagnostics envelope is invalid")
    for numeric_field in ("objective", "gradient_inf_norm"):
        value = fit.get(numeric_field)
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
            raise ArtifactValidationError(f"fit {numeric_field} must be finite or null")
    if fit.get("gradient_inf_norm") is not None and fit["gradient_inf_norm"] < 0:
        raise ArtifactValidationError("fit gradient_inf_norm cannot be negative")

    parameters = payload["parameters"]
    expected_parameter_fields = (
        {"parameter_order", "parameters_available"} if artifact_type == "fit_failure"
        else {"parameter_order", "theta"} if family == "complete_subset_exponential"
        else {"parameter_order", "centered_log_weights"}
    )
    if (not isinstance(parameters, dict) or set(parameters) != expected_parameter_fields
            or parameters.get("parameter_order") != "feature_schema.names"):
        raise ArtifactValidationError("parameter order must bind to feature_schema.names")
    if artifact_type == "fit_failure":
        if payload["model_family"] not in ("complete_subset_exponential", "conditional_poisson"):
            raise ArtifactValidationError("fit failure artifact has an unknown model family")
        if (fit["status"] == "converged" or not isinstance(payload.get("failure_reason"), str)
                or not payload["failure_reason"] or parameters.get("parameters_available") is not False):
            raise ArtifactValidationError("fit failure artifact must carry a stable failure reason and no parameters")
        if payload["fit_diagnostics"].get("terminal_status") != fit["status"]:
            raise ArtifactValidationError("failed fit status envelope does not match diagnostics")
        if payload["fit_diagnostics"].get("converged") is not False:
            raise ArtifactValidationError("failed fit diagnostics must explicitly record converged=false")
        if payload["model_family"] == "complete_subset_exponential" and fit.get("lambda") != 1.0:
            raise ArtifactValidationError("failed exponential fit must preserve the registered lambda")
        if payload["model_family"] == "conditional_poisson" and fit.get("lambda") is not None:
            raise ArtifactValidationError("failed conditional-Poisson fit cannot carry exponential L2 lambda")
        return
    if fit["status"] != "converged":
        raise ArtifactValidationError("non-converged fits cannot be serialized as fitted model artifacts")
    if fit.get("objective") is None or fit.get("gradient_inf_norm") is None or fit["gradient_inf_norm"] > 1e-8:
        raise ArtifactValidationError("converged artifact exceeds the registered fit diagnostics")

    if family == "complete_subset_exponential":
        theta = payload.get("theta")
        feature_names = payload.get("active_feature_names")
        parameter_theta = parameters.get("theta")
        if (not isinstance(theta, list) or not isinstance(feature_names, list)
                or len(theta) != len(feature_names) or feature_names != names
                or parameter_theta != theta or len(means) != len(theta)
                or any(not _is_finite_number(value) for value in theta)):
            raise ArtifactValidationError("exponential artifact theta/schema/moments dimensions or numeric values are invalid")
        if payload.get("objective_scale") != "mean_nll":
            raise ArtifactValidationError("exponential artifact objective_scale must be mean_nll")
        if (not _is_finite_number(payload.get("regularization_lambda"))
                or payload["regularization_lambda"] != 1.0
                or not _is_finite_number(fit.get("lambda")) or fit["lambda"] != 1.0):
            raise ArtifactValidationError("exponential artifact lambda must match the frozen value 1.0")
        if fit.get("status") != payload["fit_diagnostics"].get("terminal_status"):
            raise ArtifactValidationError("fit status envelope does not match fit diagnostics")
    elif family == "conditional_poisson":
        weights = payload.get("centered_log_weights")
        parameter_weights = parameters.get("centered_log_weights")
        if (not isinstance(weights, list) or len(weights) != expected[0]
                or parameter_weights != weights or len(names) != expected[0]
                or any(not _is_finite_number(value) for value in weights)):
            raise ArtifactValidationError("conditional-Poisson weights/schema must be finite numeric values matching population_size")
        if abs(sum(weights)) > 1e-8:
            raise ArtifactValidationError("conditional-Poisson log weights must use the zero-sum gauge")
        for field in ("target_marginals", "achieved_marginals"):
            values = payload.get(field)
            if not isinstance(values, list) or len(values) != expected[0] or any(
                type(value) not in (int, float) or not math.isfinite(value) or not 0.0 < value < 1.0
                for value in values
            ):
                raise ArtifactValidationError(f"conditional-Poisson {field} are invalid")
        if payload.get("solver_status") != fit.get("status"):
            raise ArtifactValidationError("conditional-Poisson solver status mismatch")
        target_marginals = payload["target_marginals"]
        achieved_marginals = payload["achieved_marginals"]
        if (abs(sum(target_marginals) - expected[1]) > 1e-10
                or abs(sum(achieved_marginals) - expected[1]) > 1e-10):
            raise ArtifactValidationError("conditional-Poisson marginals must sum to selection_size")
        residual = payload.get("calibration_residual")
        actual_residual = max(abs(a - b) for a, b in zip(target_marginals, achieved_marginals))
        if (type(residual) not in (int, float) or not math.isfinite(residual)
                or residual < 0 or residual > 1e-8
                or abs(residual - actual_residual) > 1e-10):
            raise ArtifactValidationError("conditional-Poisson calibration residual is invalid or exceeds tolerance")
        if fit["gradient_inf_norm"] > 1e-8:
            raise ArtifactValidationError("conditional-Poisson fit exceeds gradient tolerance")
        if fit.get("lambda") is not None:
            raise ArtifactValidationError("conditional-Poisson artifact cannot carry exponential L2 lambda")
    else:
        raise ArtifactValidationError("unknown model_family")


DERIVED_CACHE_SCHEMA = "lottery.derived-cache/v1"


def validate_derived_cache(payload: dict) -> None:
    """Validate a non-executable derived cache bound to one immutable model artifact."""
    required = {
        "schema_version", "artifact_schema", "cache_type", "parent_artifact_id",
        "cache_payload", "code_revision", "runtime",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ArtifactValidationError("derived cache fields do not match the registered schema")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ArtifactValidationError("unsupported derived cache schema_version")
    if payload["artifact_schema"] != DERIVED_CACHE_SCHEMA:
        raise ArtifactValidationError("unsupported derived cache schema")
    if not isinstance(payload["cache_type"], str) or not payload["cache_type"]:
        raise ArtifactValidationError("derived cache cache_type must be non-empty")
    parent_id = payload["parent_artifact_id"]
    if (not isinstance(parent_id, str) or len(parent_id) != 71
            or not parent_id.startswith("sha256:")
            or any(char not in "0123456789abcdef" for char in parent_id[7:])):
        raise ArtifactValidationError("derived cache parent_artifact_id must be a lowercase sha256 ID")
    revision = payload["code_revision"]
    if (not isinstance(revision, str) or len(revision) != 40
            or any(char not in "0123456789abcdef" for char in revision)):
        raise ArtifactValidationError("derived cache code_revision must be a full lowercase Git SHA")
    if not isinstance(payload["runtime"], dict):
        raise ArtifactValidationError("derived cache runtime must be an object")
    canonicalize(payload["cache_payload"])


def create_derived_cache(payload: dict) -> tuple[bytes, str]:
    """Create canonical content-addressed cache bytes with a mandatory parent reference."""
    if not isinstance(payload, dict):
        raise ArtifactValidationError("derived cache payload must be an object")
    body = dict(payload)
    body.pop("artifact_id", None)
    validate_derived_cache(body)
    digest = hashlib.sha256(canonicalize(body)).hexdigest()
    artifact_id = "sha256:" + digest
    complete = dict(body)
    complete["artifact_id"] = artifact_id
    return canonicalize(complete), artifact_id


def verify_derived_cache(
    raw: bytes | str, *, expected_parent_artifact_id: str | None = None
) -> dict:
    """Verify cache digest, canonical bytes, and optionally its expected parent."""
    payload = parse_json_strict(raw)
    artifact_id = payload.get("artifact_id")
    if (not isinstance(artifact_id, str) or len(artifact_id) != 71
            or not artifact_id.startswith("sha256:")
            or any(char not in "0123456789abcdef" for char in artifact_id[7:])):
        raise ArtifactValidationError("derived cache artifact_id is missing or malformed")
    body = dict(payload)
    body.pop("artifact_id")
    validate_derived_cache(body)
    if (expected_parent_artifact_id is not None
            and body["parent_artifact_id"] != expected_parent_artifact_id):
        raise ArtifactValidationError("derived cache parent artifact ID mismatch")
    expected = "sha256:" + hashlib.sha256(canonicalize(body)).hexdigest()
    if artifact_id != expected:
        raise ArtifactValidationError("derived cache content hash does not match artifact_id")
    canonical_full = canonicalize(payload)
    raw_bytes = raw.encode("utf-8") if isinstance(raw, str) else raw
    if canonical_full != raw_bytes:
        raise ArtifactValidationError("derived cache bytes are not canonical RFC 8785 JSON")
    return payload


def create_artifact(payload: dict) -> tuple[bytes, str]:
    """Create canonical artifact bytes and ID; artifact_id is excluded from hash."""
    if not isinstance(payload, dict):
        raise ArtifactValidationError("payload must be an object")
    body = dict(payload)
    body.pop("artifact_id", None)
    validate_model_artifact(body)
    digest = hashlib.sha256(canonicalize(body)).hexdigest()
    artifact_id = "sha256:" + digest
    complete = dict(body)
    complete["artifact_id"] = artifact_id
    return canonicalize(complete), artifact_id


def verify_artifact(raw: bytes | str) -> dict:
    """Verify canonical bytes and content ID before returning parsed data."""
    payload = parse_json_strict(raw)
    artifact_id = payload.get("artifact_id")
    if not isinstance(artifact_id, str) or not artifact_id.startswith("sha256:"):
        raise ArtifactValidationError("artifact_id is missing or malformed")
    body = dict(payload)
    body.pop("artifact_id")
    validate_model_artifact(body)
    expected = "sha256:" + hashlib.sha256(canonicalize(body)).hexdigest()
    if artifact_id != expected:
        raise ArtifactValidationError("artifact content hash does not match artifact_id")
    canonical_full = canonicalize(payload)
    raw_bytes = raw.encode("utf-8") if isinstance(raw, str) else raw
    if canonical_full != raw_bytes:
        raise ArtifactValidationError("artifact bytes are not canonical RFC 8785 JSON")
    return payload
