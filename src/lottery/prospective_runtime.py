"""Issue a prospective forecast only from a registered, registry-bound schedule slot."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .prospective import ProspectiveLedger
from .prospective_evaluator import FrozenArtifactEvaluator
from .prospective_registry import assert_registry_unchanged
from .prospective_schedule import validate_schedule
from .subset_model.lifecycle import ChampionLifecycle


def issue_registered_forecast(
    lifecycle: ChampionLifecycle,
    ledger: ProspectiveLedger,
    schedule: dict[str, Any],
    record: dict[str, Any],
    *,
    now: datetime | None = None,
    evaluator: FrozenArtifactEvaluator | None = None,
) -> dict[str, Any]:
    """Load both frozen distributions, verify normalization, and append one forecast."""
    records = validate_schedule(schedule)
    if record not in records:
        raise ValueError("forecast slot is not a member of the content-addressed schedule")
    if record["lifecycle_state"] not in ("champion", "shadow"):
        raise ValueError("only Champion and shadow evaluation slots may issue forecasts")
    assert_registry_unchanged(lifecycle, schedule)
    issued = now or datetime.now(timezone.utc)
    if issued.tzinfo is None or issued.utcoffset() is None:
        raise ValueError("forecast issue clock must be timezone-aware")
    issued = issued.astimezone(timezone.utc)
    cutoff = datetime.fromisoformat(record["target_cutoff_utc"].replace("Z", "+00:00"))
    if issued >= cutoff:
        raise ValueError("forecast issuance is closed at/after target cutoff")
    expected_at = datetime.fromisoformat(record["expected_at_utc"].replace("Z", "+00:00"))
    if expected_at > issued:
        raise ValueError("forecast cannot be issued before its registered expectation time")

    frozen = evaluator or FrozenArtifactEvaluator(lifecycle)
    front_id = "sha256:" + record["front_artifact_sha256"]
    back_id = "sha256:" + record["back_artifact_sha256"]
    front_distribution = frozen.distribution_sha256(front_id)
    back_distribution = frozen.distribution_sha256(back_id)
    artifact_id = front_id if record["zone"] == "front" else back_id
    distribution_id = front_distribution if record["zone"] == "front" else back_distribution
    return ledger.issue_forecast(
        target_draw_id=record["target_draw_id"],
        target_draw_at_utc=record["target_draw_at_utc"],
        target_cutoff_utc=record["target_cutoff_utc"],
        target_cutoff_timezone_source=record["target_cutoff_timezone_source"],
        issued_at_utc=issued.isoformat(),
        artifact_sha256=artifact_id[7:],
        distribution_sha256=distribution_id,
        front_artifact_sha256=record["front_artifact_sha256"],
        back_artifact_sha256=record["back_artifact_sha256"],
        front_distribution_sha256=front_distribution,
        back_distribution_sha256=back_distribution,
        active_registry_snapshot_id=record["active_registry_snapshot_id"],
        lifecycle_state=record["lifecycle_state"],
        model_spec_sha256=record["model_spec_sha256"],
        zone=record["zone"],
        population_key=record["population_key"],
        training_snapshot_sha256=record["training_snapshot_sha256"],
        training_first_draw_id=record["training_first_draw_id"],
        training_last_draw_id=record["training_last_draw_id"],
        training_row_count=record["training_row_count"],
        training_last_draw_date=record["training_last_draw_date"],
        registry_generation=record["registry_generation"],
        forecast_policy_version=record["forecast_policy_version"],
        scoring_policy_version=record["scoring_policy_version"],
        model_family=record["model_family"],
        code_commit=record["code_commit"],
        runtime=record["runtime"],
        source_evidence_manifest_sha256=record.get("source_evidence_manifest_sha256"),
    )
