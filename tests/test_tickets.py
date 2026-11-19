import unittest

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
        for tickets in result["strategies"].values():
            self.assertEqual(len(tickets), 4)
            for ticket in tickets:
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

    def test_invalid_configuration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "positive integer"):
            generate_ticket_candidates(self.rows, tickets_per_strategy=0)
        with self.assertRaisesRegex(ValueError, "finite and positive"):
            generate_ticket_candidates(self.rows, alpha=float("nan"))
        with self.assertRaisesRegex(ValueError, "finite and positive"):
            generate_ticket_candidates(self.rows, half_life=0)

    def test_duplicate_draws_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            generate_ticket_candidates([self.rows[0], self.rows[0]])


if __name__ == "__main__":
    unittest.main()
