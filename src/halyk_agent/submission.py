from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any


def create_draft(template: dict, *, team: str, contact_email: str, model: str) -> dict:
    draft = deepcopy(template)
    draft["team"] = team
    draft["contact_email"] = contact_email
    draft["model"] = model
    return draft


def validate_submission(candidate: dict, template: dict, *, require_answers: bool) -> list[str]:
    errors: list[str] = []
    candidate_answers = candidate.get("answers")
    template_answers = template.get("answers")
    if not isinstance(candidate_answers, dict) or not isinstance(template_answers, dict):
        return ["Both candidate and template must contain an 'answers' object"]
    if set(candidate_answers) != set(template_answers):
        errors.append("Scenario keys do not exactly match submission_template.json")
    for scenario, expected_covenants in template_answers.items():
        actual_covenants = candidate_answers.get(scenario)
        if not isinstance(actual_covenants, dict):
            errors.append(f"{scenario}: missing covenant object")
            continue
        if set(actual_covenants) != set(expected_covenants):
            errors.append(f"{scenario}: covenant keys do not match template")
        for covenant in expected_covenants:
            cell = actual_covenants.get(covenant)
            label = f"{scenario}/{covenant}"
            if not isinstance(cell, dict):
                errors.append(f"{label}: cell must be an object")
                continue
            if set(cell) != {"status", "actual", "evidence_txn_id"}:
                errors.append(f"{label}: cell fields do not match required schema")
                continue
            if require_answers:
                if cell["status"] not in {"COMPLIANT", "BREACH"}:
                    errors.append(f"{label}: invalid status")
                if not isinstance(cell["actual"], (int, float)) or isinstance(cell["actual"], bool):
                    errors.append(f"{label}: actual must be numeric")
                elif cell["actual"] < 0:
                    errors.append(f"{label}: actual must be non-negative")
                evidence = cell["evidence_txn_id"]
                if evidence is not None and not isinstance(evidence, str):
                    errors.append(f"{label}: evidence_txn_id must be a string or null")
    return errors


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)

