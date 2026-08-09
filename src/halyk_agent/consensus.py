from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from halyk_agent.submission import validate_submission, write_json


def build_consensus_submission(
    *,
    stability_provider_dir: Path,
    output_path: Path,
    team: str,
    contact_email: str,
) -> dict[str, Any]:
    """Build a leakage-free per-cell majority from independent solver samples."""

    paths = sorted(stability_provider_dir.glob("repetitions/*/submission.json"))
    if not paths:
        raise ValueError(f"No repetition submissions found in {stability_provider_dir}")
    submissions = [json.loads(path.read_text(encoding="utf-8-sig")) for path in paths]
    consensus = deepcopy(submissions[0])
    consensus["team"] = team
    consensus["contact_email"] = contact_email
    evidence_ties: list[str] = []
    support: dict[str, Any] = {}

    for scenario, covenant_map in consensus["answers"].items():
        for covenant in covenant_map:
            all_candidates = [item["answers"][scenario][covenant] for item in submissions]
            candidates = [
                item
                for item in all_candidates
                if item.get("status") in {"COMPLIANT", "BREACH"}
                and isinstance(item.get("actual"), (int, float))
                and not isinstance(item.get("actual"), bool)
            ]
            if len(candidates) <= len(submissions) // 2:
                raise ValueError(
                    f"Insufficient completed samples for {scenario}/{covenant}: "
                    f"{len(candidates)}/{len(submissions)}"
                )
            core_labels = [
                json.dumps(
                    {"status": item["status"], "actual": round(float(item["actual"]), 2)},
                    sort_keys=True,
                )
                for item in candidates
            ]
            core_counts = Counter(core_labels)
            best_count = max(core_counts.values())
            winners = sorted(label for label, count in core_counts.items() if count == best_count)
            cell_key = f"{scenario}/{covenant}"
            if len(winners) != 1:
                raise ValueError(f"Unresolved core consensus tie for {cell_key}: {core_counts}")
            winning_core = json.loads(winners[0])
            winning_candidates = [
                item
                for item, label in zip(candidates, core_labels, strict=True)
                if label == winners[0]
            ]

            if winning_core["status"] == "COMPLIANT":
                evidence = None
                evidence_count = len(winning_candidates)
            else:
                evidence_counts = Counter(
                    item.get("evidence_txn_id") for item in winning_candidates
                )
                evidence_count = max(evidence_counts.values())
                evidence_winners = [
                    value for value, count in evidence_counts.items() if count == evidence_count
                ]
                if len(evidence_winners) > 1:
                    evidence_ties.append(cell_key)
                    evidence = None if None in evidence_winners else sorted(evidence_winners)[0]
                else:
                    evidence = evidence_winners[0]

            consensus["answers"][scenario][covenant] = {
                "status": winning_core["status"],
                "actual": winning_core["actual"],
                "evidence_txn_id": evidence,
            }
            support[cell_key] = {
                "core_support": best_count,
                "sample_count": len(candidates),
                "ignored_incomplete_samples": len(all_candidates) - len(candidates),
                "evidence_support_within_winning_core": evidence_count,
            }

    errors = validate_submission(consensus, submissions[0], require_answers=True)
    if errors:
        raise ValueError("Invalid consensus submission: " + "; ".join(errors))
    write_json(output_path, consensus)
    report = {
        "sample_count": len(submissions),
        "model": consensus["model"],
        "evidence_ties_resolved_conservatively": evidence_ties,
        "support": support,
    }
    write_json(output_path.with_suffix(".consensus-report.json"), report)
    return report
