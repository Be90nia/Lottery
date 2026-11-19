import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from lottery.tickets import generate_ticket_candidates


def draw(index, front=None, back=None):
    return {
        "draw_id": f"26{index:03d}",
        "draw_date": f"2026-01-{index:02d}",
        "front_numbers": front or [1, 2, 3, 4, 5],
        "back_numbers": back or [1, 2],
        "source_id": "fixture",
    }


class TicketCandidateTests(unittest.TestCase):
    def setUp(self):
        self.rows = [draw(i) for i in range(1, 8)]

    def test_returns_three_distinct_strategy_lanes_and_legal_tickets(self):
        result = generate_ticket_candidates(self.rows, tickets_per_strategy=4)
        self.assertEqual(set(result["strategies"]), {"uniform", "expanding", "ewma"})
        self.assertEqual(result["total_tickets"], 12)
        self.assertEqual(result["tickets_per_strategy"], 4)
        self.assertEqual(len(result["generation_run_id"]), 64)
        self.assertEqual(set(result["strategy_metadata"]), {"uniform", "expanding", "ewma"})
        for strategy, tickets in result["strategies"].items():
            self.assertEqual(result["strategy_metadata"][strategy]["ticket_count"], 4)
            self.assertEqual(result["strategy_metadata"][strategy]["training_cutoff_draw_id"], self.rows[-1]["draw_id"])
            self.assertEqual(len(tickets), 4)
            for ticket in tickets:
                self.assertEqual(len(ticket["ticket_id"]), 24)
                self.assertEqual(len(ticket["front_numbers"]), 5)
                self.assertEqual(len(set(ticket["front_numbers"])), 5)
                self.assertTrue(all(1 <= n <= 35 for n in ticket["front_numbers"]))
                self.assertEqual(len(ticket["back_numbers"]), 2)
                self.assertEqual(len(set(ticket["back_numbers"])), 2)
                self.assertTrue(all(1 <= n <= 12 for n in ticket["back_numbers"]))

    def test_seed_is_reproducible(self):
        first = generate_ticket_candidates(self.rows, tickets_per_strategy=3, seed=91)
        second = generate_ticket_candidates(self.rows, tickets_per_strategy=3, seed=91)
        self.assertEqual(first["strategies"], second["strategies"])
        self.assertEqual(first["generation_run_id"], second["generation_run_id"])

    def test_duplicate_tickets_are_preserved_under_with_replacement_sampling(self):
        def repeated_sample(_weights, count, _rng):
            return [1, 2, 3, 4, 5] if count == 5 else [1, 2]

        with patch("lottery.tickets._weighted_sample_without_replacement", side_effect=repeated_sample):
            result = generate_ticket_candidates(self.rows, tickets_per_strategy=3)
        for tickets in result["strategies"].values():
            self.assertEqual(len(tickets), 3)
            self.assertEqual(
                len({(tuple(t["front_numbers"]), tuple(t["back_numbers"])) for t in tickets}),
                1,
            )
            self.assertEqual(len({t["ticket_id"] for t in tickets}), 3)

    def test_invalid_configuration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "positive integer"):
            generate_ticket_candidates(self.rows, tickets_per_strategy=0)
        with self.assertRaisesRegex(ValueError, "finite and positive"):
            generate_ticket_candidates(self.rows, alpha=float("nan"))
        with self.assertRaisesRegex(ValueError, "finite and positive"):
            generate_ticket_candidates(self.rows, half_life=0)
        with self.assertRaisesRegex(ValueError, "finite and positive"):
            generate_ticket_candidates(self.rows, alpha=True)
        with self.assertRaisesRegex(ValueError, "finite and positive"):
            generate_ticket_candidates(self.rows, half_life=False)


    def test_cli_reads_dataset_and_writes_auditable_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dataset = root / "draws.jsonl"
            output = root / "tickets.json"
            dataset.write_text(
                "".join(json.dumps(row) + "\n" for row in self.rows),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable, "scripts/generate_tickets.py", str(dataset),
                    "--tickets", "2", "--seed", "77", "--output", str(output),
                ],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["dataset"]["trust_status"], "not_authenticated_by_this_tool")
            self.assertEqual(
                report["dataset"]["sha256"],
                hashlib.sha256(dataset.read_bytes()).hexdigest(),
            )
            self.assertEqual(len(report["strategies"]["uniform"]), 2)
            self.assertEqual(len(report["strategies"]["expanding"]), 2)
            self.assertEqual(len(report["strategies"]["ewma"]), 2)

    def test_generation_limit_is_enforced(self):
        with self.assertRaisesRegex(ValueError, "1..100"):
            generate_ticket_candidates(self.rows, tickets_per_strategy=101)

    def test_duplicate_draws_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            generate_ticket_candidates([self.rows[0], self.rows[0]])


if __name__ == "__main__":
    unittest.main()
