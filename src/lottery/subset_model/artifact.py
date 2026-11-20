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
    """Validate core shape and family-specific numerical dimensions."""
    required = {
        "schema_version", "model_family", "zone", "population_size",
        "selection_size", "training_snapshot_sha256", "training_cutoff_draw_id",
        "training_row_count", "code_revision", "runtime", "fit_diagnostics",
        "forecast_ready",
    }
    missing = required.difference(payload)
    if missing:
        raise ArtifactValidationError(f"missing required artifact fields: {sorted(missing)}")
    if payload["schema_version"] != 1:
        raise ArtifactValidationError("unsupported model artifact schema_version")
    if payload["zone"] == "front":
        expected = (35, 5)
    elif payload["zone"] == "back":
        expected = (12, 2)
    else:
        raise ArtifactValidationError("zone must be 'front' or 'back'")
    if (payload["population_size"], payload["selection_size"]) != expected:
        raise ArtifactValidationError("zone support dimensions do not match the lottery rules")
    if type(payload["training_row_count"]) is not int or payload["training_row_count"] < 1:
        raise ArtifactValidationError("training_row_count must be a positive integer")
    if not isinstance(payload["training_snapshot_sha256"], str) or len(payload["training_snapshot_sha256"]) != 64:
        raise ArtifactValidationError("training_snapshot_sha256 must be a 64-character hex digest")
    try:
        int(payload["training_snapshot_sha256"], 16)
    except ValueError as exc:
        raise ArtifactValidationError("training_snapshot_sha256 must be hexadecimal") from exc
    if not isinstance(payload["code_revision"], str) or not payload["code_revision"]:
        raise ArtifactValidationError("code_revision must be a non-empty string")
    if not isinstance(payload["runtime"], dict) or not isinstance(payload["fit_diagnostics"], dict):
        raise ArtifactValidationError("runtime and fit_diagnostics must be objects")
    if type(payload["forecast_ready"]) is not bool:
        raise ArtifactValidationError("forecast_ready must be boolean")
    if payload["forecast_ready"]:
        raise ArtifactValidationError(
            "serialization cannot confer forecast readiness; readiness belongs to lifecycle policy"
        )

    family = payload["model_family"]
    family_fields = {
        "complete_subset_exponential": {
            "feature_schema_version", "active_feature_names", "theta",
            "objective_scale", "regularization_lambda",
        },
        "conditional_poisson": {"centered_log_weights"},
    }
    if family not in family_fields:
        raise ArtifactValidationError("unknown model_family")
    unknown = set(payload).difference(required | family_fields[family])
    if unknown:
        raise ArtifactValidationError(
            f"unknown artifact fields for {family}: {sorted(unknown)}"
        )

    if family == "complete_subset_exponential":
        theta = payload.get("theta")
        feature_names = payload.get("active_feature_names")
        if not isinstance(theta, list) or not isinstance(feature_names, list) or len(theta) != len(feature_names):
            raise ArtifactValidationError("exponential artifact theta must match active_feature_names")
        if payload.get("objective_scale") != "mean_nll":
            raise ArtifactValidationError("exponential artifact objective_scale must be mean_nll")
        if payload.get("regularization_lambda") != 1.0:
            raise ArtifactValidationError("exponential artifact lambda must match the frozen value 1.0")
    elif family == "conditional_poisson":
        weights = payload.get("centered_log_weights")
        if not isinstance(weights, list) or len(weights) != expected[0]:
            raise ArtifactValidationError("conditional-Poisson weights must match population_size")
        if abs(sum(float(value) for value in weights)) > 1e-8:
            raise ArtifactValidationError("conditional-Poisson log weights must use the zero-sum gauge")



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
