from __future__ import annotations

import unittest

from halyk_agent.stability import (
    _parse_excluded_cells,
    _score_excluding,
    aggregate_stability,
)


def _evaluation(p1_total: float, p2_total: float) -> dict:
    def cell(scenario: str, total: float) -> dict:
        return {
            "scenario": scenario,
            "covenant": "6.1",
            "status_score": 0.5 if total else 0.0,
            "actual_score": 0.3 if total == 1.0 else 0.0,
            "evidence_score": 0.2 if total == 1.0 else 0.0,
            "total": total,
            "relative_error": 0.0 if total == 1.0 else None,
        }

    cells = [cell("P1", p1_total), cell("P2", p2_total)]
    return {
        "proxy_score": sum(item["total"] for item in cells) / 2,
        "cells": cells,
    }


def _submission(p1_status: str, p2_status: str) -> dict:
    return {
        "answers": {
            "P1": {
                "6.1": {
                    "status": p1_status,
                    "actual": 1.0,
                    "evidence_txn_id": None,
                }
            },
            "P2": {
                "6.1": {
                    "status": p2_status,
                    "actual": 2.0,
                    "evidence_txn_id": None,
                }
            },
        }
    }


class StabilityTests(unittest.TestCase):
    def test_aggregate_distinguishes_stable_failure_and_flaky_cell(self) -> None:
        evaluations = [
            _evaluation(0.0, 1.0),
            _evaluation(0.0, 0.0),
            _evaluation(0.0, 1.0),
        ]
        submissions = [
            _submission("BREACH", "COMPLIANT"),
            _submission("BREACH", "BREACH"),
            _submission("BREACH", "COMPLIANT"),
        ]

        result = aggregate_stability(
            evaluations=evaluations,
            submissions=submissions,
            repetitions=3,
            exclusions=set(),
        )

        self.assertIn("P1/6.1", result["stable_failure_cells"])
        self.assertIn("P2/6.1", result["flaky_cells"])
        self.assertEqual(result["cells"]["P2/6.1"]["perfect_count"], 2)
        self.assertEqual(
            result["cells"]["P2/6.1"]["candidate_distribution"][0]["count"],
            2,
        )

    def test_known_issue_is_omitted_only_from_clean_score(self) -> None:
        evaluation = _evaluation(0.0, 1.0)
        exclusions = {("P1", "6.1")}

        self.assertEqual(_score_excluding(evaluation["cells"], exclusions), 1.0)
        result = aggregate_stability(
            evaluations=[evaluation],
            submissions=[_submission("BREACH", "COMPLIANT")],
            repetitions=1,
            exclusions=exclusions,
        )
        self.assertEqual(result["score_statistics"]["mean"], 0.5)
        self.assertEqual(result["clean_score_statistics"]["mean"], 1.0)
        self.assertNotIn("P1/6.1", result["stable_failure_cells"])

    def test_exclusion_parser_requires_scenario_and_covenant(self) -> None:
        self.assertEqual(_parse_excluded_cells(("P4/6.3",)), {("P4", "6.3")})
        with self.assertRaises(ValueError):
            _parse_excluded_cells(("P4",))


if __name__ == "__main__":
    unittest.main()
