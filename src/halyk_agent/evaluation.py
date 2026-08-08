from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any


@dataclass(frozen=True, slots=True)
class CellScore:
    scenario: str
    covenant: str
    status_score: float
    actual_score: float
    evidence_score: float
    total: float
    relative_error: float | None


def evaluate_submission(candidate: dict, ground_truth: dict) -> dict[str, Any]:
    cells: list[CellScore] = []
    candidate_answers = candidate.get("answers", {})
    scenarios = ground_truth.get("scenarios", {})
    for scenario, scenario_truth in scenarios.items():
        for covenant, truth in scenario_truth.get("covenants", {}).items():
            predicted = candidate_answers.get(scenario, {}).get(covenant, {})
            cells.append(_score_cell(scenario, covenant, predicted, truth))
    if not cells:
        raise ValueError("ground_truth.json contains no covenant cells")
    return {
        "proxy_score": sum(cell.total for cell in cells) / len(cells),
        "status_accuracy": sum(cell.status_score == 0.5 for cell in cells) / len(cells),
        "mean_actual_score": sum(cell.actual_score for cell in cells) / len(cells),
        "mean_evidence_score": sum(cell.evidence_score for cell in cells) / len(cells),
        "cell_count": len(cells),
        "perfect_cell_count": sum(math.isclose(cell.total, 1.0) for cell in cells),
        "note": "Unweighted proxy; organizer difficulty weights are not public.",
        "cells": [asdict(cell) for cell in cells],
    }


def _score_cell(scenario: str, covenant: str, predicted: dict, truth: dict) -> CellScore:
    status_score = 0.5 if predicted.get("status") == truth.get("status") else 0.0
    if status_score == 0:
        return CellScore(scenario, covenant, 0.0, 0.0, 0.0, 0.0, None)

    relative_error = _relative_error(predicted.get("actual"), truth.get("actual"))
    closeness = max(0.0, 1.0 - relative_error / 0.05) if relative_error is not None else 0.0
    actual_score = 0.3 * closeness
    truth_evidence = truth.get("evidence_txn_id")
    if truth_evidence is None:
        evidence_score = 0.2 * closeness
    else:
        evidence_score = 0.2 if predicted.get("evidence_txn_id") == truth_evidence else 0.0
    total = status_score + actual_score + evidence_score
    return CellScore(
        scenario,
        covenant,
        status_score,
        actual_score,
        evidence_score,
        total,
        relative_error,
    )


def _relative_error(predicted: object, truth: object) -> float | None:
    if isinstance(predicted, bool) or not isinstance(predicted, (int, float)):
        return None
    if isinstance(truth, bool) or not isinstance(truth, (int, float)):
        return None
    if not math.isfinite(float(predicted)) or not math.isfinite(float(truth)):
        return None
    if truth == 0:
        return 0.0 if predicted == 0 else math.inf
    return abs(float(predicted) - float(truth)) / abs(float(truth))

