"""Build a fail-closed LOT-063 schedule from one verified lifecycle snapshot.

No registry pointers are mutated. Trust in target calendars and canonical inventory
is injected; content hashes alone are integrity checks, not source authentication.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
from typing import Any, Callable

from .prospective_schedule import SCHEDULE_SCHEMA, validate_schedule
from .subset_model.artifact import canonicalize
from .subset_model.lifecycle import ChampionLifecycle, LifecycleError

TARGET_SCHEMA = "lottery.prospective-target-manifest/v1"
INVENTORY_SCHEMA = "lottery.canonical-draw-inventory/v1"
POLICY_VERSION = "prospective-exact-set/v1"
SCORING_VERSION = "exact-set-nll/v1"


class RegistryScheduleError(ValueError):
    """A registry, artifact, target manifest, or inventory is not eligible."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _content_id(value: dict[str, Any], field: str) -> str:
    supplied = value.get(field)
    body = {key: item for key, item in value.items() if key != field}
    expected = "sha256:" + _sha(canonicalize(body))
    if supplied != expected:
        raise RegistryScheduleError(f"{field} does not match canonical content")
    return expected


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise RegistryScheduleError(f"{field} must be an ISO-8601 timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RegistryScheduleError(f"{field} is malformed") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise RegistryScheduleError(f"{field} must include a timezone")
    return result.astimezone(timezone.utc)


def _load_canonical(path: str | Path) -> dict[str, Any]:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise RegistryScheduleError(f"duplicate JSON key: {key}")
            value[key] = item
        return value
    try:
        raw = Path(path).read_bytes()
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegistryScheduleError("cannot read canonical JSON input") from exc
    if not isinstance(value, dict) or canonicalize(value) != raw:
        raise RegistryScheduleError("input must be a canonical JSON object")
    return value


def _artifact_model_spec(artifact: dict[str, Any]) -> str:
    body = {
        "model_family": artifact["model_family"],
        "zone": artifact["zone"],
        "population_size": artifact["population_size"],
        "selection_size": artifact["selection_size"],
        "model_configuration": artifact["model_configuration"],
        "model_configuration_hash": artifact["model_configuration_hash"],
        "feature_schema_hash": artifact["feature_schema_hash"],
    }
    return "sha256:" + _sha(canonicalize(body))


def _training_fields(artifact: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    training = artifact.get("training")
    if not isinstance(training, dict):
        raise RegistryScheduleError("artifact has no verified training envelope")
    first_id = training.get("first_draw_id")
    last_id = training.get("last_draw_id")
    row_count = artifact.get("training_row_count")
    if (not isinstance(first_id, str) or not re.fullmatch(r"\d{5}", first_id)
            or not isinstance(last_id, str) or not re.fullmatch(r"\d{5}", last_id)
            or first_id > last_id or type(row_count) is not int or row_count < 300):
        raise RegistryScheduleError("artifact training range or minimum history is invalid")
    dates = inventory["draw_dates"]
    if first_id not in dates or last_id not in dates:
        raise RegistryScheduleError("training draw ID has no canonical inventory date crosswalk")
    return {
        "training_snapshot_sha256": artifact["training_snapshot_sha256"],
        "training_first_draw_id": first_id,
        "training_last_draw_id": last_id,
        "training_row_count": row_count,
        "training_last_draw_date": dates[last_id],
    }


def _candidate(slot: dict[str, Any], field: str) -> tuple[str, str] | None:
    artifact_id = slot.get(field)
    if artifact_id is None:
        return None
    validation = slot.get("validation", {}).get(artifact_id)
    if not validation or validation.get("eligible") is not True:
        raise RegistryScheduleError("registered challenger has not passed retrospective eligibility")
    return artifact_id, ("challenger" if field == "challenger_artifact_id" else "shadow")


def _registry_slots(snapshot: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    slots: dict[str, dict[str, dict[str, Any]]] = {}
    for key, slot in snapshot.get("slots", {}).items():
        population = slot.get("population_key")
        zone = slot.get("zone")
        if not isinstance(population, str) or zone not in ("front", "back"):
            raise RegistryScheduleError("registry contains malformed population/zone slot")
        if key != f"{population}|{zone}":
            raise RegistryScheduleError("registry slot key does not match its contents")
        if zone in slots.setdefault(population, {}):
            raise RegistryScheduleError("duplicate registry population/zone")
        if slot.get("suspended") is True:
            raise RegistryScheduleError(f"suspended lifecycle slot: {key}")
        slots[population][zone] = slot
    return slots


def build_registry_schedule(
    lifecycle: ChampionLifecycle,
    target_manifest: dict[str, Any],
    inventory: dict[str, Any],
    *,
    now: datetime,
    code_commit: str,
    runtime: str | None = None,
    target_manifest_verifier: Callable[[dict[str, Any]], bool] | None = None,
    inventory_verifier: Callable[[dict[str, Any]], bool] | None = None,
    schedule_attestor: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    schedule_verifier: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    """Create Champion + validated challenger-shadow expectations, or fail before writes."""
    if (target_manifest_verifier is None or inventory_verifier is None
            or schedule_attestor is None or schedule_verifier is None):
        raise RegistryScheduleError("protected target, inventory and schedule signing/verifier callbacks are required")
    if target_manifest_verifier(target_manifest) is not True:
        raise RegistryScheduleError("target manifest authority verifier rejected the evidence")
    if inventory_verifier(inventory) is not True:
        raise RegistryScheduleError("canonical inventory verifier rejected the crosswalk")
    target_manifest_id = _content_id(target_manifest, "manifest_id")
    inventory_id = _content_id(inventory, "inventory_id")
    if target_manifest.get("schema") != TARGET_SCHEMA or target_manifest.get("authority") != "official_verified":
        raise RegistryScheduleError("target manifest must be official_verified and use the supported schema")
    if inventory.get("schema") != INVENTORY_SCHEMA or inventory.get("authority") != "official_verified":
        raise RegistryScheduleError("inventory must be official_verified and use the supported schema")
    draw_dates = inventory.get("draw_dates")
    if not isinstance(draw_dates, dict) or not draw_dates:
        raise RegistryScheduleError("canonical inventory draw_dates must be a non-empty mapping")
    inventory = {**inventory, "draw_dates": draw_dates}
    if not re.fullmatch(r"[0-9a-f]{40}", code_commit):
        raise RegistryScheduleError("code_commit must be a full Git SHA")
    if now.tzinfo is None or now.utcoffset() is None:
        raise RegistryScheduleError("now must be timezone-aware")
    generated = now.astimezone(timezone.utc)
    targets = target_manifest.get("targets")
    if not isinstance(targets, list) or not targets:
        raise RegistryScheduleError("target manifest must contain explicit targets")
    target_ids = []
    for target in targets:
        if not isinstance(target, dict):
            raise RegistryScheduleError("target manifest entry must be an object")
        draw_id = target.get("target_draw_id")
        if not isinstance(draw_id, str) or not re.fullmatch(r"\d{5}", draw_id):
            raise RegistryScheduleError("target_draw_id must be a five-digit official draw ID")
        expected = _timestamp(target.get("expected_at_utc"), "expected_at_utc")
        cutoff = _timestamp(target.get("target_cutoff_utc"), "target_cutoff_utc")
        draw_at = _timestamp(target.get("target_draw_at_utc"), "target_draw_at_utc")
        if not expected < cutoff < draw_at or generated >= cutoff:
            raise RegistryScheduleError("target chronology must satisfy generated/expected < cutoff < draw")
        if draw_id not in draw_dates:
            raise RegistryScheduleError(f"target draw {draw_id} is absent from canonical inventory")
        if not isinstance(target.get("target_cutoff_timezone_source"), str) or not target["target_cutoff_timezone_source"].strip():
            raise RegistryScheduleError("target cutoff timezone source is required")
        target_ids.append(draw_id)
    if len(target_ids) != len(set(target_ids)):
        raise RegistryScheduleError("target manifest contains duplicate draw IDs")

    snapshot = lifecycle.snapshot()
    snapshot_hash = _sha(canonicalize(snapshot))
    grouped = _registry_slots(snapshot)
    if not grouped:
        raise RegistryScheduleError("registry has no Champion slots")
    records: list[dict[str, Any]] = []
    for population_key, pair in sorted(grouped.items()):
        if set(pair) != {"front", "back"}:
            raise RegistryScheduleError(f"population {population_key} lacks a complete front/back pair")
        champions = {}
        candidates = {}
        for zone in ("front", "back"):
            slot = pair[zone]
            champion_id = slot.get("champion_artifact_id")
            if not champion_id:
                raise RegistryScheduleError(f"population {population_key} has no {zone} Champion")
            champions[zone] = (champion_id, "champion")
            challenger = _candidate(slot, "challenger_artifact_id")
            shadow = _candidate(slot, "shadow_artifact_id")
            if challenger and shadow:
                raise RegistryScheduleError("slot cannot contain both challenger and shadow candidates")
            candidates[zone] = challenger or shadow
        candidate_presence = [candidates[z] is not None for z in ("front", "back")]
        if any(candidate_presence) and not all(candidate_presence):
            raise RegistryScheduleError(f"population {population_key} has an incomplete front/back challenger pair")
        pairs = [("champion", champions)]
        if all(candidate_presence):
            if candidates["front"][1] != candidates["back"][1]:
                raise RegistryScheduleError("front/back candidate lifecycle roles differ")
            pairs.append(("shadow", {z: candidates[z] for z in ("front", "back")}))
        for lifecycle_state, artifact_pair in pairs:
            loaded = {}
            for zone in ("front", "back"):
                artifact_id = artifact_pair[zone][0]
                artifact = lifecycle._load_artifact(artifact_id)
                if artifact.get("zone") != zone:
                    raise RegistryScheduleError("artifact zone does not match its registry slot")
                if artifact.get("model_family") not in ("complete_subset_exponential", "conditional_poisson"):
                    raise RegistryScheduleError("unsupported model family")
                loaded[zone] = (artifact_id, artifact, _training_fields(artifact, inventory))
            if loaded["front"][1]["model_family"] != loaded["back"][1]["model_family"]:
                raise RegistryScheduleError("front/back artifacts use incompatible model families")
            if loaded["front"][1]["training_snapshot_sha256"] != loaded["back"][1]["training_snapshot_sha256"]:
                raise RegistryScheduleError("front/back artifacts must bind the same training snapshot")
            model_spec = "sha256:" + _sha(canonicalize({
                "front": _artifact_model_spec(loaded["front"][1]),
                "back": _artifact_model_spec(loaded["back"][1]),
                "model_family": loaded["front"][1]["model_family"],
                "lifecycle_state": lifecycle_state,
            }))
            for target in targets:
                for zone in ("front", "back"):
                    artifact_id, artifact, training = loaded[zone]
                    if artifact["training_cutoff_draw_id"] >= target["target_draw_id"]:
                        raise RegistryScheduleError("training cutoff is not strictly before target draw")
                    records.append({
                        "target_draw_id": target["target_draw_id"],
                        "target_draw_at_utc": target["target_draw_at_utc"],
                        "target_cutoff_utc": target["target_cutoff_utc"],
                        "target_cutoff_timezone_source": target["target_cutoff_timezone_source"],
                        "expected_at_utc": target["expected_at_utc"],
                        "zone": zone,
                        "population_key": population_key,
                        "front_artifact_sha256": loaded["front"][0][7:],
                        "back_artifact_sha256": loaded["back"][0][7:],
                        "active_registry_snapshot_id": snapshot_hash,
                        "lifecycle_state": lifecycle_state,
                        "model_spec_sha256": model_spec[7:],
                        **training,
                        "registry_generation": snapshot["generation"],
                        "forecast_policy_version": POLICY_VERSION,
                        "scoring_policy_version": SCORING_VERSION,
                        "model_family": artifact["model_family"],
                        "code_commit": code_commit,
                        "runtime": runtime or f"{platform.python_implementation()} {platform.python_version()}",
                        "source_evidence_manifest_sha256": target_manifest_id[7:],
                    })
    schedule = {
        "schema": SCHEDULE_SCHEMA,
        "lot042_accessed": False,
        "generated_at_utc": generated.isoformat(),
        "expected_forecasts": records,
    }
    schedule["schedule_id"] = "sha256:" + _sha(canonicalize(schedule))
    validate_schedule(schedule)
    # Detect a registry generation/pointer race during artifact and target preflight.
    after = lifecycle.snapshot()
    if _sha(canonicalize(after)) != snapshot_hash:
        raise RegistryScheduleError("Champion registry changed while schedule was being built")
    schedule["provenance"] = {
        "target_manifest_id": target_manifest_id,
        "inventory_id": inventory_id,
        "registry_snapshot_sha256": snapshot_hash,
    }
    # A protected signer attests the exact schedule payload before the schedule
    # content ID is calculated. A digest alone is not an authenticity proof.
    signed_payload = dict(schedule)
    attestation = schedule_attestor(signed_payload)
    if (
        not isinstance(attestation, dict)
        or not isinstance(attestation.get("key_id"), str) or not attestation["key_id"]
        or not isinstance(attestation.get("signature"), str) or not attestation["signature"]
        or attestation.get("payload_sha256") != _sha(canonicalize(signed_payload))
    ):
        raise RegistryScheduleError("protected schedule attestor returned an invalid payload-bound signature")
    schedule["trust_attestation"] = attestation
    schedule["schedule_id"] = "sha256:" + _sha(canonicalize(schedule))
    validate_schedule(schedule)
    if schedule_verifier(schedule) is not True:
        raise RegistryScheduleError("protected schedule signature verifier rejected the built schedule")
    return schedule


def assert_registry_unchanged(
    lifecycle: ChampionLifecycle,
    schedule: dict[str, Any],
    *,
    schedule_verifier: Callable[[dict[str, Any]], bool] | None = None,
) -> None:
    """Verify signature and registry immediately before registration/issuance."""
    attestation = schedule.get("trust_attestation")
    unsigned_payload = {
        key: value for key, value in schedule.items()
        if key not in ("schedule_id", "trust_attestation")
    }
    if (
        not isinstance(attestation, dict)
        or not isinstance(attestation.get("key_id"), str) or not attestation["key_id"]
        or not isinstance(attestation.get("signature"), str) or not attestation["signature"]
        or attestation.get("payload_sha256") != _sha(canonicalize(unsigned_payload))
    ):
        raise RegistryScheduleError("schedule trust attestation is missing or not bound to the unsigned payload")
    if schedule_verifier is None or schedule_verifier(schedule) is not True:
        raise RegistryScheduleError("protected schedule signature verifier is absent or rejected the schedule")
    provenance = schedule.get("provenance")
    if not isinstance(provenance, dict) or not re.fullmatch(
        r"[0-9a-f]{64}", str(provenance.get("registry_snapshot_sha256", ""))
    ):
        raise RegistryScheduleError("schedule lacks registry snapshot provenance")
    snapshot = lifecycle.snapshot()
    if (
        snapshot.get("generation") != schedule["expected_forecasts"][0]["registry_generation"]
        or _sha(canonicalize(snapshot)) != provenance["registry_snapshot_sha256"]
    ):
        raise RegistryScheduleError("registry changed after schedule construction; rebuild schedule")
