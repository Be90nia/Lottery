from datetime import datetime, timezone
import hashlib
import tempfile
import unittest
from pathlib import Path

from lottery.prospective import ProspectiveLedger, ProspectiveLedgerError


def sha(label):
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def score_result(value):
    return lambda record, subset: {
        "artifact_sha256": record["artifact_sha256"],
        "normalization_verified": True,
        "log_probability": value,
    }


def outcome_metadata(source, retrieved="2026-11-20T13:30:00+00:00"):
    url = "https://example.test/official/draw/26131"
    return {
        "source_object_ref": f"evidence/{source}.bin",
        "requested_url": url,
        "final_url": url,
        "retrieved_at_utc": retrieved,
        "evidence_locator": "draw_id=26131;page=1",
    }


class ProspectiveLedgerTests(unittest.TestCase):
    def register_expectation(self, **overrides):
        values = {
            "target_draw_id": "26131",
            "target_draw_at_utc": "2026-11-20T13:00:00+00:00",
            "target_cutoff_utc": "2026-11-20T12:00:00+00:00",
            "target_cutoff_timezone_source": "official_schedule/v1",
            "expected_at_utc": self.now.isoformat(),
            "zone": "front",
            "population_key": "pooled-equipment-blind",
            "front_artifact_sha256": sha("artifact-front"),
            "back_artifact_sha256": sha("artifact-back"),
            "active_registry_snapshot_id": sha("registry-snapshot"),
            "lifecycle_state": "champion",
            "model_spec_sha256": sha("model-spec"),
            "training_snapshot_sha256": sha("training-snapshot"),
            "training_first_draw_id": "09054",
            "training_last_draw_id": "26130",
            "training_row_count": 2948,
            "training_last_draw_date": "2026-11-19",
            "registry_generation": 7,
            "forecast_policy_version": "prospective-v1",
            "scoring_policy_version": "exact-set-nll/v1",
            "model_family": "complete_subset_exponential",
            "code_commit": "a" * 40,
            "runtime": "CPython 3.12",
            "source_evidence_manifest_sha256": sha("source-evidence"),
        }
        values.update(overrides)
        return self.ledger.register_expected_forecast(**values)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = datetime.fromisoformat("2026-11-20T10:00:00+00:00")
        self.ledger = ProspectiveLedger(
            Path(self.temp.name) / "prospective.jsonl", clock=lambda: self.now
        )
        self.register_expectation()
        self.forecast = self.ledger.issue_forecast(
            target_draw_id="26131",
            target_draw_at_utc="2026-11-20T13:00:00+00:00",
            target_cutoff_utc="2026-11-20T12:00:00+00:00",
            target_cutoff_timezone_source="official_schedule/v1",
            issued_at_utc="2026-11-20T10:00:00+00:00",
            artifact_sha256=sha("artifact-front"),
            distribution_sha256=sha("distribution-front"),
            front_artifact_sha256=sha("artifact-front"),
            back_artifact_sha256=sha("artifact-back"),
            front_distribution_sha256=sha("distribution-front"),
            back_distribution_sha256=sha("distribution-back"),
            active_registry_snapshot_id=sha("registry-snapshot"),
            lifecycle_state="champion",
            model_spec_sha256=sha("model-spec"),
            zone="front",
            population_key="pooled-equipment-blind",
            training_snapshot_sha256=sha("training-snapshot"),
            training_first_draw_id="09054",
            training_row_count=2948,
            training_last_draw_id="26130",
            training_last_draw_date="2026-11-19",
            registry_generation=7,
            forecast_policy_version="prospective-v1",
            scoring_policy_version="exact-set-nll/v1",
            model_family="complete_subset_exponential",
            code_commit="a" * 40,
            runtime="CPython 3.12",
            source_evidence_manifest_sha256=sha("source-evidence"),
        )

    def tearDown(self):
        self.temp.cleanup()

    def record_official_outcome(self, *, front=None, source="official-source-v1", supersedes=None, observed="2026-11-20T14:00:00+00:00"):
        return self.ledger.record_outcome(
            draw_id="26131",
            observed_at_utc=observed,
            authority="official_validated",
            source_evidence_sha256=sha(source),
            **outcome_metadata(source),
            parser_version="official-parser/v1",
            front_numbers=front or [1, 2, 3, 4, 5],
            back_numbers=[1, 2],
            evidence_verifier=lambda candidate, expected: (
                candidate["draw_id"] == expected["draw_id"]
                and candidate["source_evidence_sha256"] == expected["source_evidence_sha256"]
            ),
            supersedes_outcome_id=supersedes,
        )

    def test_expectation_cannot_be_backdated_after_cutoff(self):
        self.now = datetime.fromisoformat("2026-11-20T12:01:00+00:00")
        with self.assertRaisesRegex(ProspectiveLedgerError, "recorded after its cutoff"):
            self.register_expectation(
                target_draw_id="26132",
                target_draw_at_utc="2026-11-20T13:00:00+00:00",
                target_cutoff_utc="2026-11-20T12:00:00+00:00",
                expected_at_utc="2026-11-20T10:00:00+00:00",
                front_artifact_sha256=sha("late-expectation-front"),
                back_artifact_sha256=sha("late-expectation-back"),
                active_registry_snapshot_id=sha("late-expectation-registry"),
                training_snapshot_sha256=sha("late-expectation-training"),
            )

    def test_forecast_is_bound_to_artifact_target_zone_and_cutoff(self):
        self.assertEqual(self.forecast["status"], "eligible")
        self.assertEqual(self.forecast["target_draw_id"], "26131")
        self.assertEqual(self.forecast["training_last_draw_id"], "26130")
        self.assertEqual(self.forecast["zone"], "front")
        self.assertEqual(self.ledger.snapshot()["forecasts"][self.forecast["forecast_id"]], self.forecast)

    def test_late_forecast_and_training_leakage_are_recorded_ineligible(self):
        self.register_expectation(
            target_draw_id="26132",
            target_draw_at_utc="2026-11-21T13:00:00+00:00",
            target_cutoff_utc="2026-11-21T12:00:00+00:00",
            expected_at_utc=self.now.isoformat(),
            zone="back",
            front_artifact_sha256=sha("front-artifact-late"),
            back_artifact_sha256=sha("artifact-late"),
            active_registry_snapshot_id=sha("registry-snapshot-late"),
            model_spec_sha256=sha("model-spec"),
            training_snapshot_sha256=sha("training-late"),
            training_last_draw_id="26131",
            training_last_draw_date="2026-11-20",
            code_commit="b" * 40,
            source_evidence_manifest_sha256=None,
        )
        self.now = datetime.fromisoformat("2026-11-21T13:00:00+00:00")
        late = self.ledger.issue_forecast(
            target_draw_id="26132",
            target_draw_at_utc="2026-11-21T13:00:00+00:00",
            target_cutoff_utc="2026-11-21T12:00:00+00:00",
            target_cutoff_timezone_source="official_schedule/v1",
            issued_at_utc="2026-11-21T11:00:00+00:00",
            artifact_sha256=sha("artifact-late"),
            distribution_sha256=sha("distribution-late"),
            front_artifact_sha256=sha("front-artifact-late"),
            back_artifact_sha256=sha("artifact-late"),
            front_distribution_sha256=sha("front-distribution-late"),
            back_distribution_sha256=sha("distribution-late"),
            active_registry_snapshot_id=sha("registry-snapshot-late"),
            lifecycle_state="champion",
            model_spec_sha256=sha("model-spec"),
            zone="back",
            population_key="pooled-equipment-blind",
            training_snapshot_sha256=sha("training-late"),
            training_first_draw_id="09054",
            training_row_count=2948,
            training_last_draw_id="26132",
            training_last_draw_date="2026-11-20",
            registry_generation=7,
            forecast_policy_version="prospective-v1",
            scoring_policy_version="exact-set-nll/v1",
            model_family="complete_subset_exponential",
            code_commit="b" * 40,
            runtime="CPython 3.12",
        )
        self.assertEqual(late["status"], "ineligible")
        self.assertIn("forecast_recorded_after_cutoff", late["reason_codes"])
        self.assertIn("training_draw_not_before_target", late["reason_codes"])
        with self.assertRaisesRegex(ProspectiveLedgerError, "ineligible forecast"):
            self.ledger.score_forecast(
                forecast_id=late["forecast_id"], outcome_id="0" * 64,
                scorer_version="score-v1", log_probability=score_result(-1.0),
            )

    def test_forecast_cannot_be_issued_without_prior_expectation(self):
        with self.assertRaisesRegex(ProspectiveLedgerError, "pre-registered before issuance"):
            self.ledger.issue_forecast(
                target_draw_id="26133",
                target_draw_at_utc="2026-11-22T13:00:00+00:00",
                target_cutoff_utc="2026-11-22T12:00:00+00:00",
                target_cutoff_timezone_source="official_schedule/v1",
                issued_at_utc="2026-11-22T10:00:00+00:00",
                artifact_sha256=sha("artifact-26133-front"),
                distribution_sha256=sha("distribution-26133-front"),
                front_artifact_sha256=sha("artifact-26133-front"),
                back_artifact_sha256=sha("artifact-26133-back"),
                front_distribution_sha256=sha("distribution-26133-front"),
                back_distribution_sha256=sha("distribution-26133-back"),
                active_registry_snapshot_id=sha("registry-26133"),
                lifecycle_state="champion",
                model_spec_sha256=sha("model-spec-26133"),
                zone="front",
                population_key="pooled-equipment-blind",
                training_snapshot_sha256=sha("training-26133"),
                training_first_draw_id="09054",
                training_row_count=2948,
                training_last_draw_id="26132",
                training_last_draw_date="2026-11-21",
                registry_generation=7,
                forecast_policy_version="prospective-v1",
                scoring_policy_version="exact-set-nll/v1",
                model_family="complete_subset_exponential",
                code_commit="d" * 40,
                runtime="CPython 3.12",
            )

    def test_expected_forecast_schedule_exposes_unresolved_denominator(self):
        self.register_expectation(
            target_draw_id="26132",
            target_draw_at_utc="2026-11-21T13:00:00+00:00",
            target_cutoff_utc="2026-11-21T12:00:00+00:00",
            expected_at_utc=self.now.isoformat(),
            front_artifact_sha256=sha("front-expected-26132"),
            back_artifact_sha256=sha("back-expected-26132"),
            active_registry_snapshot_id=sha("registry-26132"),
            model_spec_sha256=sha("model-spec-26132"),
            training_snapshot_sha256=sha("training-26132"),
            training_last_draw_id="26131",
            training_last_draw_date="2026-11-20",
            code_commit="c" * 40,
        )
        report = self.ledger.coverage_report()
        self.assertEqual(report["expected_forecast_records"], 2)
        self.assertEqual(report["forecast_records"], 1)
        self.assertEqual(report["unresolved_expected_forecasts"], 1)
        self.assertEqual(report["by_zone"]["front"]["unresolved"], 1)

    def test_missing_forecast_at_cutoff_is_immutable_terminal_record(self):
        kwargs = {
            "target_draw_id": "26132",
            "target_draw_at_utc": "2026-11-21T13:00:00+00:00",
            "target_cutoff_utc": "2026-11-21T12:00:00+00:00",
            "target_cutoff_timezone_source": "official_schedule/v1",
            "expected_at_utc": self.now.isoformat(),
            "checked_at_utc": "2026-11-21T12:01:00+00:00",
            "zone": "front",
            "population_key": "pooled-equipment-blind",
            "front_artifact_sha256": sha("missing-front-artifact"),
            "back_artifact_sha256": sha("missing-back-artifact"),
            "active_registry_snapshot_id": sha("missing-registry"),
            "lifecycle_state": "champion",
            "model_spec_sha256": sha("missing-model-spec"),
            "training_snapshot_sha256": sha("missing-training"),
            "training_first_draw_id": "09054",
            "training_last_draw_id": "26131",
            "training_row_count": 2948,
            "training_last_draw_date": "2026-11-20",
            "registry_generation": 7,
            "forecast_policy_version": "prospective-v1",
            "scoring_policy_version": "exact-set-nll/v1",
            "model_family": "complete_subset_exponential",
            "code_commit": "a" * 40,
            "runtime": "CPython 3.12",
        }
        kwargs["expected_at_utc"] = self.now.isoformat()
        self.ledger.register_expected_forecast(**{
            key: value for key, value in kwargs.items() if key != "checked_at_utc"
        })
        self.now = datetime.fromisoformat("2026-11-21T11:59:00+00:00")
        with self.assertRaisesRegex(ProspectiveLedgerError, "before the ledger clock reaches cutoff"):
            self.ledger.record_missing_forecast(**kwargs)
        self.now = datetime.fromisoformat(kwargs["checked_at_utc"])
        first = self.ledger.record_missing_forecast(**kwargs)
        self.assertEqual(first["status"], "missing_at_cutoff")
        self.assertEqual(first["reason_codes"], ["forecast_missing_at_cutoff"])
        self.assertEqual(self.ledger.record_missing_forecast(**kwargs), first)
        report = self.ledger.coverage_report()
        self.assertEqual(report["expected_forecast_records"], 2)
        self.assertEqual(report["forecast_records"], 2)
        self.assertEqual(report["unresolved_expected_forecasts"], 0)
        self.assertEqual(report["forecast_missing_at_cutoff"], 1)
        self.assertEqual(report["ineligible"], 1)
        self.assertEqual(report["by_zone"]["front"]["missing_at_cutoff"], 1)
        changed = dict(kwargs, checked_at_utc="2026-11-21T12:02:00+00:00")
        with self.assertRaisesRegex(ProspectiveLedgerError, "duplicate artifact"):
            self.ledger.record_missing_forecast(**changed)

    def test_forecast_key_cannot_be_rewritten(self):
        self.now = datetime.fromisoformat("2026-11-20T10:01:00+00:00")
        with self.assertRaisesRegex(ProspectiveLedgerError, "immutable record"):
            self.ledger.issue_forecast(
                target_draw_id="26131",
                target_draw_at_utc="2026-11-20T13:00:00+00:00",
                target_cutoff_utc="2026-11-20T12:00:00+00:00",
                target_cutoff_timezone_source="official_schedule/v1",
                issued_at_utc="2026-11-20T10:01:00+00:00",
                artifact_sha256=sha("artifact-front"),
                distribution_sha256=sha("changed-distribution"),
                front_artifact_sha256=sha("artifact-front"),
                back_artifact_sha256=sha("artifact-back"),
                front_distribution_sha256=sha("changed-distribution"),
                back_distribution_sha256=sha("distribution-back"),
                active_registry_snapshot_id=sha("registry-snapshot"),
                lifecycle_state="champion",
                model_spec_sha256=sha("model-spec"),
                zone="front",
                population_key="pooled-equipment-blind",
                training_snapshot_sha256=sha("training-snapshot"),
                training_first_draw_id="09054",
                training_row_count=2948,
                training_last_draw_id="26130",
                training_last_draw_date="2026-11-19",
                registry_generation=7,
                forecast_policy_version="prospective-v1",
                scoring_policy_version="exact-set-nll/v1",
                model_family="complete_subset_exponential",
                code_commit="a" * 40,
                runtime="CPython 3.12",
                source_evidence_manifest_sha256=sha("source-evidence"),
            )

    def test_non_authoritative_outcome_is_preserved_but_not_scored(self):
        outcome = self.ledger.record_outcome(
            draw_id="26131",
            observed_at_utc="2026-11-20T14:00:00+00:00",
            authority="third_party",
            source_evidence_sha256=sha("third-party"),
            **outcome_metadata("third-party"),
            parser_version="third-party-parser/v1",
            front_numbers=[1, 2, 3, 4, 5],
            back_numbers=[1, 2],
            reason_code="official_source_blocked",
        )
        with self.assertRaisesRegex(ProspectiveLedgerError, "only authoritative"):
            self.ledger.score_forecast(
                forecast_id=self.forecast["forecast_id"],
                outcome_id=outcome["outcome_id"],
                scorer_version="score-v1",
                log_probability=score_result(-1.0),
            )

    def test_exact_set_score_is_one_forecast_zone_record_and_idempotent(self):
        outcome = self.record_official_outcome()
        score = self.ledger.score_forecast(
            forecast_id=self.forecast["forecast_id"],
            outcome_id=outcome["outcome_id"],
            scorer_version="exact-set-v1",
            log_probability=score_result(-10.5),
        )
        self.assertEqual(score["negative_log_score"], 10.5)
        self.assertTrue(score["normalization_verified"])
        self.assertRegex(score["evaluation_receipt_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(score["scoring_policy_version"], "exact-set-nll/v1")
        self.assertEqual(score["front_artifact_sha256"], self.forecast["front_artifact_sha256"])
        self.assertEqual(score["back_artifact_sha256"], self.forecast["back_artifact_sha256"])
        self.assertAlmostEqual(score["uniform_negative_log_score"], 12.6904475)
        self.assertAlmostEqual(score["candidate_minus_uniform_nll"], 10.5 - score["uniform_negative_log_score"])
        retry = self.ledger.score_forecast(
            forecast_id=self.forecast["forecast_id"],
            outcome_id=outcome["outcome_id"],
            scorer_version="exact-set-v1",
            log_probability=score_result(-10.5),
        )
        self.assertEqual(score, retry)
        self.assertEqual(self.ledger.coverage_report()["score_revisions"], 1)

    def test_score_evaluation_failures_are_retained_without_penalty(self):
        outcome = self.record_official_outcome()
        for _ in range(2):
            with self.assertRaisesRegex(ProspectiveLedgerError, "probability evaluation failed"):
                self.ledger.score_forecast(
                    forecast_id=self.forecast["forecast_id"],
                    outcome_id=outcome["outcome_id"],
                    scorer_version="failing-scorer-v1",
                    attempt_id="failed-attempt-001",
                    log_probability=lambda record, subset: (_ for _ in ()).throw(RuntimeError("optimizer unavailable")),
                )
        snapshot = self.ledger.snapshot()
        self.assertEqual(len(snapshot["scores"]), 0)
        self.assertEqual(len(snapshot["score_failures"]), 1)
        failure = next(iter(snapshot["score_failures"].values()))
        self.assertEqual(failure["failure_code"], "artifact_probability_evaluation_failed")
        self.assertEqual(failure["status"], "score_failed")
        self.assertEqual(self.ledger.coverage_report()["score_failed_attempts"], 1)

    def test_score_requires_bound_artifact_and_normalization_verification(self):
        outcome = self.record_official_outcome()
        with self.assertRaisesRegex(ProspectiveLedgerError, "full-support normalization"):
            self.ledger.score_forecast(
                forecast_id=self.forecast["forecast_id"],
                outcome_id=outcome["outcome_id"],
                scorer_version="unverified-normalization-v1",
                log_probability=lambda record, subset: {
                    "artifact_sha256": sha("wrong-artifact"),
                    "normalization_verified": False,
                    "log_probability": -10.5,
                },
            )
        snapshot = self.ledger.snapshot()
        self.assertEqual(len(snapshot["scores"]), 0)
        self.assertEqual(len(snapshot["score_failures"]), 1)
        self.assertEqual(
            next(iter(snapshot["score_failures"].values()))["failure_code"],
            "artifact_normalization_or_identity_unverified",
        )

    def test_positive_or_nonfinite_log_probability_is_rejected(self):
        outcome = self.record_official_outcome()
        for value in (0.01, 0.0, float("nan"), float("inf"), False):
            with self.assertRaisesRegex(ProspectiveLedgerError, "finite and strictly negative|probability evaluation failed|log probability is invalid"):
                self.ledger.score_forecast(
                    forecast_id=self.forecast["forecast_id"],
                    outcome_id=outcome["outcome_id"],
                    scorer_version=f"bad-{value}",
                    log_probability=score_result(value),
                )

    def test_outcome_correction_timestamp_cannot_move_backwards(self):
        first = self.record_official_outcome()
        with self.assertRaisesRegex(ProspectiveLedgerError, "cannot move backwards"):
            self.record_official_outcome(
                front=[6, 7, 8, 9, 10],
                source="out-of-order-correction",
                supersedes=first["outcome_id"],
                observed="2026-11-20T13:59:59+00:00",
            )
        self.assertEqual(self.ledger.snapshot()["latest_outcome_by_draw"]["26131"], first["outcome_id"])

    def test_outcome_correction_appends_new_version_and_new_score(self):
        first = self.record_official_outcome()
        first_score = self.ledger.score_forecast(
            forecast_id=self.forecast["forecast_id"],
            outcome_id=first["outcome_id"],
            scorer_version="exact-set-v1",
            log_probability=score_result(-10.5),
        )
        retry = self.record_official_outcome()
        self.assertEqual(first, retry)
        corrected = self.record_official_outcome(
            front=[6, 7, 8, 9, 10],
            source="official-correction-v2",
            supersedes=first["outcome_id"],
            observed="2026-11-21T09:00:00+00:00",
        )
        with self.assertRaisesRegex(ProspectiveLedgerError, "superseded outcome"):
            self.ledger.score_forecast(
                forecast_id=self.forecast["forecast_id"],
                outcome_id=first["outcome_id"],
                scorer_version="exact-set-v2",
                log_probability=score_result(-9.0),
            )
        second_score = self.ledger.score_forecast(
            forecast_id=self.forecast["forecast_id"],
            outcome_id=corrected["outcome_id"],
            scorer_version="exact-set-v1",
            log_probability=score_result(-11.0),
        )
        snapshot = self.ledger.snapshot()
        self.assertIn(first["outcome_id"], snapshot["outcomes"])
        self.assertIn(corrected["outcome_id"], snapshot["outcomes"])
        self.assertIn(first["outcome_id"], snapshot["superseded_outcome_ids"])
        self.assertIn(first_score["score_id"], snapshot["scores"])
        self.assertIn(second_score["score_id"], snapshot["scores"])
        self.assertEqual(self.ledger.coverage_report()["score_revisions"], 2)

    def test_duplicate_outcome_retry_is_idempotent(self):
        first = self.record_official_outcome()
        second = self.record_official_outcome()
        self.assertEqual(first, second)
        self.assertEqual(len(self.ledger.snapshot()["outcomes"]), 1)

    def test_invalid_subset_and_missing_official_verifier_fail_closed(self):
        with self.assertRaisesRegex(ProspectiveLedgerError, "front outcome"):
            self.ledger.record_outcome(
                draw_id="26131",
                observed_at_utc="2026-11-20T14:00:00+00:00",
                authority="official_validated",
                source_evidence_sha256=sha("bad-result"),
                **outcome_metadata("bad-result"),
                parser_version="official-parser/v1",
                front_numbers=[1, 1, 2, 3, 4],
                back_numbers=[1, 2],
                evidence_verifier=lambda candidate, expected: True,
            )
        with self.assertRaisesRegex(ProspectiveLedgerError, "protected evidence verifier"):
            self.ledger.record_outcome(
                draw_id="26131",
                observed_at_utc="2026-11-20T14:00:00+00:00",
                authority="official_validated",
                source_evidence_sha256=sha("no-verifier"),
                **outcome_metadata("no-verifier"),
                parser_version="official-parser/v1",
                front_numbers=[1, 2, 3, 4, 5],
                back_numbers=[1, 2],
            )

    def test_coverage_report_separates_pending_invalid_and_unscored_outcomes(self):
        self.assertEqual(self.ledger.coverage_report()["outcome_pending"], 1)
        self.ledger.record_outcome(
            draw_id="26131",
            observed_at_utc="2026-11-20T14:00:00+00:00",
            authority="third_party",
            source_evidence_sha256=sha("third-party-coverage"),
            **outcome_metadata("third-party-coverage"),
            parser_version="third-party-parser/v1",
            front_numbers=[1, 2, 3, 4, 5],
            back_numbers=[1, 2],
            reason_code="official_source_blocked",
        )
        self.assertEqual(self.ledger.coverage_report()["outcome_invalid"], 1)
        official = self.record_official_outcome(
            source="official-after-third-party",
            supersedes=self.ledger.snapshot()["latest_outcome_by_draw"]["26131"],
        )
        self.assertEqual(self.ledger.coverage_report()["score_pending"], 1)
        self.ledger.score_forecast(
            forecast_id=self.forecast["forecast_id"],
            outcome_id=official["outcome_id"],
            scorer_version="coverage-test-v1",
            log_probability=score_result(-10.5),
        )
        final_report = self.ledger.coverage_report()
        self.assertEqual(final_report["eligible_pending"], 0)
        self.assertEqual(final_report["by_zone"]["front"]["scored_current"], 1)
        self.assertEqual(final_report["by_population_key"]["pooled-equipment-blind"]["scored_current"], 1)
        self.assertEqual(final_report["by_model_family"]["complete_subset_exponential"]["scored_current"], 1)

    def test_ledger_hash_chain_detects_tampering(self):
        self.record_official_outcome()
        raw = self.ledger.path.read_bytes()
        self.ledger.path.write_bytes(raw.replace(b"official_validated", b"third_party_validated", 1))
        with self.assertRaisesRegex(ProspectiveLedgerError, "hash chain failed"):
            self.ledger.snapshot()


if __name__ == "__main__":
    unittest.main()
