"""All-or-none publication for three-slot, N-ticket prediction batches.

This is an offline publication primitive. It requires a fully verified
three-slot Champion generation and never publishes partial slot output.
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable

from .storage import FileSystemObjectStore, StorageError
from .subset_model.artifact import canonicalize, parse_json_strict
from .subset_model.lifecycle import ChampionLifecycle, LifecycleError


BATCH_SCHEMA = "lottery.prediction-batch/v1"


class BatchPublicationError(RuntimeError):
    """Raised when a complete legal batch cannot be prepared or published."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _validate_ticket(ticket: Any) -> dict[str, list[int]]:
    if not isinstance(ticket, dict) or set(ticket) != {"front", "back"}:
        raise BatchPublicationError("sampler must return ticket objects with exactly front and back")
    front, back = ticket["front"], ticket["back"]
    if (not isinstance(front, list) or len(front) != 5
            or any(type(value) is not int or not 1 <= value <= 35 for value in front)
            or front != sorted(set(front))):
        raise BatchPublicationError("front ticket must contain five unique ascending integers in 1..35")
    if (not isinstance(back, list) or len(back) != 2
            or any(type(value) is not int or not 1 <= value <= 12 for value in back)
            or back != sorted(set(back))):
        raise BatchPublicationError("back ticket must contain two unique ascending integers in 1..12")
    return {"front": list(front), "back": list(back)}


class ThreeSlotBatchPublisher:
    def __init__(self, store: FileSystemObjectStore):
        self.store = store

    def publish(
        self,
        *,
        lifecycle: ChampionLifecycle,
        population_keys: list[str],
        approval_verifier: Callable[[dict[str, Any], dict[str, Any]], bool] | None,
        tickets_per_slot: int,
        idempotency_key: str,
        seed_commitment_sha256: str,
        rng_algorithm: str,
        sampler_version: str,
        producer_commit: str,
        producer_runtime: str,
        pointer_name: str,
        expected_pointer_generation: int,
        sampler: Callable[[str, str, str, int], list[dict[str, Any]]],
        actor: str,
    ) -> dict[str, Any]:
        if type(tickets_per_slot) is not int or tickets_per_slot < 1:
            raise BatchPublicationError("tickets_per_slot must be a positive integer")
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise BatchPublicationError("idempotency_key must be a non-empty string")
        if not _is_sha(seed_commitment_sha256):
            raise BatchPublicationError("seed commitment must be a lowercase SHA-256")
        for field, value in (
            ("rng_algorithm", rng_algorithm), ("sampler_version", sampler_version),
            ("producer_commit", producer_commit), ("producer_runtime", producer_runtime),
            ("actor", actor), ("pointer_name", pointer_name),
        ):
            if not isinstance(value, str) or not value:
                raise BatchPublicationError(f"{field} must be a non-empty string")
        if type(expected_pointer_generation) is not int or expected_pointer_generation < 0:
            raise BatchPublicationError("expected_pointer_generation must be a non-negative integer")
        if not callable(sampler):
            raise BatchPublicationError("a deterministic sampler callback is required")

        try:
            resolved = lifecycle.resolve_three_slot_generation(
                population_keys, approval_verifier=approval_verifier
            )
        except LifecycleError as exc:
            raise BatchPublicationError(f"no fully verified three-slot Champion generation: {exc}") from exc
        if (len(resolved["slots"]) != 6
                or len({slot["population_key"] for slot in resolved["slots"]}) != 3
                or {slot["zone"] for slot in resolved["slots"]} != {"front", "back"}):
            raise BatchPublicationError("verified registry snapshot is not exactly three population keys × two zones")
        if len({slot["artifact_id"] for slot in resolved["slots"] if slot["zone"] == "front"}) != 3:
            raise BatchPublicationError("three population slots must not reuse front artifacts")
        if len({slot["artifact_id"] for slot in resolved["slots"] if slot["zone"] == "back"}) != 3:
            raise BatchPublicationError("three population slots must not reuse back artifacts")
        for zone in ("front", "back"):
            contracts = {
                (
                    slot["model_family"], slot["artifact_schema"],
                    slot["feature_schema_hash"], slot["population_size"],
                    slot["selection_size"],
                )
                for slot in resolved["slots"] if slot["zone"] == zone
            }
            if len(contracts) != 1:
                raise BatchPublicationError(
                    f"all three {zone} population artifacts must share one compatible model family/schema contract"
                )

        slots_by_population: dict[str, dict[str, str]] = {};
        for slot in resolved["slots"]:
            slots_by_population.setdefault(slot["population_key"], {})[slot["zone"]] = slot["artifact_id"]
        ordered_populations = sorted(slots_by_population)
        slot_payloads = []
        all_ticket_keys: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
        for population_key in ordered_populations:
            artifacts = slots_by_population[population_key]
            if set(artifacts) != {"front", "back"}:
                raise BatchPublicationError("each population slot requires both front and back artifacts")
            try:
                tickets = sampler(
                    population_key, artifacts["front"], artifacts["back"], tickets_per_slot
                )
            except Exception as exc:
                raise BatchPublicationError(f"sampler failed for population {population_key}") from exc
            if not isinstance(tickets, list) or len(tickets) != tickets_per_slot:
                raise BatchPublicationError(
                    f"sampler returned {len(tickets) if isinstance(tickets, list) else 'non-list'} tickets; "
                    f"expected exactly {tickets_per_slot}"
                )
            legal_tickets = [_validate_ticket(ticket) for ticket in tickets]
            ticket_keys = [(tuple(ticket["front"]), tuple(ticket["back"])) for ticket in legal_tickets]
            all_ticket_keys.extend(ticket_keys)
            slot_payloads.append({
                "population_key": population_key,
                "front_artifact_id": artifacts["front"],
                "back_artifact_id": artifacts["back"],
                "tickets": legal_tickets,
                "duplicate_ticket_count": len(ticket_keys) - len(set(ticket_keys)),
            })

        total = sum(len(slot["tickets"]) for slot in slot_payloads)
        if total != 3 * tickets_per_slot:
            raise BatchPublicationError("complete batch must contain exactly 3N tickets")
        within_slot_duplicates = sum(slot["duplicate_ticket_count"] for slot in slot_payloads)
        total_duplicates = len(all_ticket_keys) - len(set(all_ticket_keys))
        cross_slot_duplicates = total_duplicates - within_slot_duplicates
        # Re-resolve immediately before staging so a registry change during
        # sampling cannot silently bind tickets to a stale or mixed generation.
        try:
            current = lifecycle.resolve_three_slot_generation(
                population_keys, approval_verifier=approval_verifier
            )
        except LifecycleError as exc:
            raise BatchPublicationError("Champion generation changed or failed re-verification") from exc
        if current != resolved:
            raise BatchPublicationError("Champion registry changed during batch generation")

        manifest = {
            "schema": BATCH_SCHEMA,
            "batch_id": _sha(idempotency_key.encode("utf-8")),
            "idempotency_key_sha256": _sha(idempotency_key.encode("utf-8")),
            "registry_generation": resolved["registry_generation"],
            "champion_generation": resolved["champion_generation"],
            "population_keys": ordered_populations,
            "tickets_per_slot": tickets_per_slot,
            "slot_count": 3,
            "total_ticket_count": total,
            "seed_commitment_sha256": seed_commitment_sha256,
            "rng_algorithm": rng_algorithm,
            "sampler_version": sampler_version,
            "producer_commit": producer_commit,
            "producer_runtime": producer_runtime,
            "duplicate_ticket_count": total_duplicates,
            "within_slot_duplicate_ticket_count": within_slot_duplicates,
            "cross_slot_duplicate_ticket_count": cross_slot_duplicates,
            "requested_by": actor,
            "slots": slot_payloads,
        }
        raw = canonicalize(manifest)

        def validate_batch(candidate: bytes) -> bool:
            parsed = parse_json_strict(candidate)
            return (
                canonicalize(parsed) == candidate
                and parsed.get("schema") == BATCH_SCHEMA
                and parsed.get("slot_count") == 3
                and parsed.get("tickets_per_slot") == tickets_per_slot
                and parsed.get("total_ticket_count") == 3 * tickets_per_slot
                and len(parsed.get("slots", [])) == 3
                and all(len(slot.get("tickets", [])) == tickets_per_slot for slot in parsed["slots"])
            )

        try:
            staged = self.store.stage(
                idempotency_key=f"prediction-batch:{idempotency_key}",
                content=raw,
                media_type="application/vnd.lottery.prediction-batch+json",
                schema_version=BATCH_SCHEMA,
                producer_commit=producer_commit,
                producer_runtime=producer_runtime,
            )
            self.store.validate(
                operation_id=staged["operation_id"],
                validator=validate_batch,
                validator_id="three-slot-3N-batch/v1",
            )
            committed = self.store.commit(operation_id=staged["operation_id"])
            pointer = self.store.publish_pointer(
                name=pointer_name,
                operation_id=staged["operation_id"],
                expected_generation=expected_pointer_generation,
            )
        except (StorageError, ValueError) as exc:
            raise BatchPublicationError(f"batch storage/publication failed closed: {exc}") from exc
        return {
            "batch_id": manifest["batch_id"],
            "batch_sha256": _sha(raw),
            "ticket_count": total,
            "registry_generation": resolved["registry_generation"],
            "champion_generation": resolved["champion_generation"],
            "commit_receipt_sha256": _sha(canonicalize(committed)),
            "pointer": pointer,
            "manifest": manifest,
        }
