"""Restricted RFC 8785 JSON Canonicalization Scheme support.

Only JSON-compatible values in the IEEE-754 binary64 domain are accepted.
The implementation follows ECMAScript number formatting thresholds and UTF-16
property ordering; it is intentionally small and covered by golden vectors.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

_SAFE_INTEGER = (1 << 53) - 1


def _quote(value: str) -> str:
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError("lone UTF-16 surrogates are not valid JCS strings")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _number(value: int | float) -> str:
    if type(value) is int:
        if abs(value) > _SAFE_INTEGER:
            raise ValueError("integer is outside the interoperable IEEE-754 safe range")
        return str(value)
    if type(value) is not float or not math.isfinite(value):
        raise ValueError("JCS numbers must be finite binary64 values")
    if value == 0.0:
        return "0"
    rendered = repr(value).lower()
    if "e" not in rendered:
        return rendered[:-2] if rendered.endswith(".0") else rendered
    mantissa, exponent_text = rendered.split("e", 1)
    exponent = int(exponent_text)
    sign = ""
    if mantissa.startswith("-"):
        sign, mantissa = "-", mantissa[1:]
    digits = mantissa.replace(".", "")
    decimal_position = (mantissa.find(".") if "." in mantissa else len(mantissa)) + exponent
    if -6 <= exponent < 21:
        if decimal_position <= 0:
            return sign + "0." + ("0" * (-decimal_position)) + digits
        if decimal_position >= len(digits):
            return sign + digits + ("0" * (decimal_position - len(digits)))
        return sign + digits[:decimal_position] + "." + digits[decimal_position:]
    normalized = digits[0]
    if len(digits) > 1:
        normalized += "." + digits[1:]
    exp_sign = "+" if exponent >= 0 else ""
    return sign + normalized + "e" + exp_sign + str(exponent)


def _canonical(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if type(value) in (int, float):
        return _number(value)
    if isinstance(value, str):
        return _quote(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canonical(item) for item in value) + "]"
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JCS object keys must be strings")
        keys = sorted(value, key=lambda key: key.encode("utf-16-be"))
        return "{" + ",".join(_quote(key) + ":" + _canonical(value[key]) for key in keys) + "}"
    raise ValueError(f"unsupported JCS value type: {type(value).__name__}")


def canonicalize(value: Any) -> bytes:
    return _canonical(value).encode("utf-8")


def artifact_id(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        raise ValueError("artifact payload must be an object")
    clean = dict(payload)
    clean.pop("artifact_id", None)
    digest = hashlib.sha256(canonicalize(clean)).hexdigest()
    return "sha256:" + digest


def attach_artifact_id(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result.pop("artifact_id", None)
    result["artifact_id"] = artifact_id(result)
    return result


def verify_artifact(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict) or not isinstance(payload.get("artifact_id"), str):
        return False
    return payload["artifact_id"] == artifact_id(payload)
