from __future__ import annotations

import unittest

from halyk_agent.evaluation import evaluate_submission


class EvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.truth = {
            "scenarios": {
                "P1": {
                    "covenants": {
                        "6.1": {
                            "status": "COMPLIANT",
                            "actual": 100.0,
                            "evidence_txn_id": None,
                        },
                        "6.2": {
                            "status": "BREACH",
                            "actual": 200.0,
                            "evidence_txn_id": "TXN-P1-0001",
                        },
                    }
                }
            }
        }

    def test_exact_submission_scores_one(self) -> None:
        candidate = {
            "answers": {
                "P1": {
                    "6.1": {"status": "COMPLIANT", "actual": 100.0, "evidence_txn_id": None},
                    "6.2": {
                        "status": "BREACH",
                        "actual": 200.0,
                        "evidence_txn_id": "TXN-P1-0001",
                    },
                }
            }
        }
        result = evaluate_submission(candidate, self.truth)
        self.assertEqual(result["proxy_score"], 1.0)
        self.assertEqual(result["perfect_cell_count"], 2)

    def test_wrong_status_zeroes_entire_cell(self) -> None:
        candidate = {
            "answers": {
                "P1": {
                    "6.1": {"status": "BREACH", "actual": 100.0, "evidence_txn_id": None},
                    "6.2": {
                        "status": "BREACH",
                        "actual": 200.0,
                        "evidence_txn_id": "TXN-P1-0001",
                    },
                }
            }
        }
        result = evaluate_submission(candidate, self.truth)
        self.assertEqual(result["cells"][0]["total"], 0.0)

    def test_two_point_five_percent_error_halves_numeric_components(self) -> None:
        candidate = {
            "answers": {
                "P1": {
                    "6.1": {"status": "COMPLIANT", "actual": 102.5, "evidence_txn_id": None},
                    "6.2": {
                        "status": "BREACH",
                        "actual": 205.0,
                        "evidence_txn_id": "TXN-P1-0001",
                    },
                }
            }
        }
        result = evaluate_submission(candidate, self.truth)
        self.assertAlmostEqual(result["cells"][0]["total"], 0.75)
        self.assertAlmostEqual(result["cells"][1]["total"], 0.85)


if __name__ == "__main__":
    unittest.main()

