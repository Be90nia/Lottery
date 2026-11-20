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
        if abs(value) > 9007199254740991:
            raise ArtifactValidationError("integer exceeds the interoperable IEEE-754 safe range")
        return str(value)
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
        "schema_version", "artifact_schema", "model_family", "zone",
        "population_size", "selection_size", "support", "feature_schema",
        "parameters", "normalization", "fit", "training", "implementation",
        "training_snapshot_sha256", "training_cutoff_draw_id",
        "training_row_count", "code_revision", "runtime", "fit_diagnostics",
        "forecast_ready",
    }
    missing = required.difference(payload)
    if missing:
        raise ArtifactValidationError(f"missing required artifact fields: {sorted(missing)}")
    if payload["schema_version"] != 1:
        raise ArtifactValidationError("unsupported model artifact schema_version")
    if payload["artifact_schema"] != "lottery.subset-probability-model/v1":
        raise ArtifactValidationError("unsupported artifact envelope schema")
    if payload["zone"] == "front":
        expected = (35, 5)
    elif payload["zone"] == "back":
        expected = (12, 2)
    else:
        raise ArtifactValidationError("zone must be 'front' or 'back'")
    if (payload["population_size"], payload["selection_size"]) != expected:
        raise ArtifactValidationError("zone support dimensions do not match the lottery rules")

    support = payload["support"]
    if not isinstance(support, dict) or (
        support.get("population_size") != expected[0]
        or support.get("selection_size") != expected[1]
        or support.get("support_count") != math.comb(*expected)
        or support.get("subset_order") != "lexicographic_ascending"
    ):
        raise ArtifactValidationError("support descriptor does not match the exact legal subset space")

    if type(payload["training_row_count"]) is not int or payload["training_row_count"] < 1:
        raise ArtifactValidationError("training_row_count must be a positive integer")
    if not isinstance(payload["training_snapshot_sha256"], str) or len(payload["training_snapshot_sha256"]) != 64:
        raise ArtifactValidationError("training_snapshot_sha256 must be a 64-character hex digest")
    try:
        int(payload["training_snapshot_sha256"], 16)
    except ValueError as exc:
        raise ArtifactValidationError("training_snapshot_sha256 must be hexadecimal") from exc
    if not isinstance(payload["training_cutoff_draw_id"], str) or not payload["training_cutoff_draw_id"]:
        raise ArtifactValidationError("training_cutoff_draw_id must be a non-empty string")
    if not isinstance(payload["code_revision"], str) or not payload["code_revision"]:
        raise ArtifactValidationError("code_revision must be a non-empty string")
    for hash_field in ("feature_schema_hash", "model_configuration_hash"):
        value = payload.get(hash_field)
        if (not isinstance(value, str) or not value.startswith("sha256:")
                or len(value) != 71):
            raise ArtifactValidationError(f"{hash_field} must be a sha256 content identifier")
        try:
            int(value[7:], 16)
        except ValueError as exc:
            raise ArtifactValidationError(f"{hash_field} must contain hexadecimal SHA-256") from exc
    if not isinstance(payload["runtime"], dict) or not isinstance(payload["fit_diagnostics"], dict):
        raise ArtifactValidationError("runtime and fit_diagnostics must be objects")
    if type(payload["forecast_ready"]) is not bool:
        raise ArtifactValidationError("forecast_ready must be boolean")
    if payload["forecast_ready"]:
        raise ArtifactValidationError(
            "serialization cannot confer forecast readiness; readiness belongs to lifecycle policy"
        )

    training = payload["training"]
    if not isinstance(training, dict) or (
        training.get("snapshot_sha256") != payload["training_snapshot_sha256"]
        or training.get("row_count") != payload["training_row_count"]
        or training.get("cutoff_draw_id") != payload["training_cutoff_draw_id"]
        or training.get("cutoff_inclusive") is not True
        or not isinstance(training.get("first_draw_id"), str)
        or not isinstance(training.get("last_draw_id"), str)
    ):
        raise ArtifactValidationError("training provenance envelope is inconsistent")

    implementation = payload["implementation"]
    if not isinstance(implementation, dict) or (
        implementation.get("code_revision") != payload["code_revision"]
        or implementation.get("runtime") != payload["runtime"]
        or not isinstance(implementation.get("library_versions"), dict)
        or not isinstance(implementation.get("rng_algorithm"), str)
        or not implementation["rng_algorithm"]
    ):
        raise ArtifactValidationError("implementation/runtime/RNG provenance is incomplete")

    feature_schema = payload["feature_schema"]
    if not isinstance(feature_schema, dict):
        raise ArtifactValidationError("feature_schema must be an object")
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

    normalization = payload["normalization"]
    if not isinstance(normalization, dict) or (
        not isinstance(normalization.get("method"), str) or not normalization["method"]
        or normalization.get("numeric_dtype") != "float64"
        or type(normalization.get("log_partition")) not in (int, float)
        or not math.isfinite(normalization["log_partition"])
    ):
        raise ArtifactValidationError("normalization descriptor is invalid")

    fit = payload["fit"]
    if not isinstance(fit, dict) or (
        not isinstance(fit.get("status"), str) or not fit["status"]
        or not isinstance(fit.get("termination_reason"), str) or not fit["termination_reason"]
        or type(fit.get("objective")) not in (int, float) or not math.isfinite(fit["objective"])
        or type(fit.get("gradient_inf_norm")) not in (int, float)
        or not math.isfinite(fit["gradient_inf_norm"]) or fit["gradient_inf_norm"] < 0
        or type(fit.get("iterations")) is not int or fit["iterations"] < 0
        or not isinstance(fit.get("optimizer"), str) or not fit["optimizer"]
    ):
        raise ArtifactValidationError("fit diagnostics envelope is invalid")

    parameters = payload["parameters"]
    if not isinstance(parameters, dict) or parameters.get("parameter_order") != "feature_schema.names":
        raise ArtifactValidationError("parameter order must bind to feature_schema.names")

    family = payload["model_family"]
    if family == "complete_subset_exponential":
        theta = payload.get("theta")
        feature_names = payload.get("active_feature_names")
        parameter_theta = parameters.get("theta")
        if (not isinstance(theta, list) or not isinstance(feature_names, list)
                or len(theta) != len(feature_names) or feature_names != names
                or parameter_theta != theta or len(means) != len(theta)):
            raise ArtifactValidationError("exponential artifact theta/schema/moments dimensions mismatch")
        if payload.get("objective_scale") != "mean_nll":
            raise ArtifactValidationError("exponential artifact objective_scale must be mean_nll")
        if payload.get("regularization_lambda") != 1.0 or fit.get("lambda") != 1.0:
            raise ArtifactValidationError("exponential artifact lambda must match the frozen value 1.0")
        if fit.get("status") != payload["fit_diagnostics"].get("terminal_status"):
            raise ArtifactValidationError("fit status envelope does not match fit diagnostics")
    elif family == "conditional_poisson":
        weights = payload.get("centered_log_weights")
        parameter_weights = parameters.get("centered_log_weights")
        if (not isinstance(weights, list) or len(weights) != expected[0]
                or parameter_weights != weights or len(names) != expected[0]):
            raise ArtifactValidationError("conditional-Poisson weights/schema must match population_size")
        if abs(sum(float(value) for value in weights)) > 1e-8:
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
        residual = payload.get("calibration_residual")
        if type(residual) not in (int, float) or not math.isfinite(residual) or residual < 0:
            raise ArtifactValidationError("conditional-Poisson calibration residual is invalid")
        if fit.get("lambda") is not None:
            raise ArtifactValidationError("conditional-Poisson artifact cannot carry exponential L2 lambda")
    else:
        raise ArtifactValidationError("unknown model_family")


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
