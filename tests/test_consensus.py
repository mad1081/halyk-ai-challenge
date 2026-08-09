from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from halyk_agent.consensus import build_consensus_submission


class ConsensusTests(unittest.TestCase):
    def test_core_majority_then_evidence_majority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            answers = [
                ("BREACH", 1.234, "TXN-X-1"),
                ("BREACH", 1.23, "TXN-X-1"),
                ("BREACH", 1.23, None),
                ("COMPLIANT", 0.8, None),
            ]
            for index, (status, actual, evidence) in enumerate(answers, start=1):
                path = root / "repetitions" / f"{index:03d}" / "submission.json"
                path.parent.mkdir(parents=True)
                path.write_text(
                    json.dumps(
                        {
                            "team": "eval",
                            "contact_email": "eval@example.com",
                            "model": "solver-model",
                            "answers": {
                                "X": {
                                    "6.1": {
                                        "status": status,
                                        "actual": actual,
                                        "evidence_txn_id": evidence,
                                    }
                                }
                            },
                        }
                    ),
                    encoding="utf-8",
                )

            output = root / "submission.json"
            report = build_consensus_submission(
                stability_provider_dir=root,
                output_path=output,
                team="Ship Happens",
                contact_email="zhasserik2019@gmail.com",
            )
            result = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(
                result["answers"]["X"]["6.1"],
                {
                    "status": "BREACH",
                    "actual": 1.23,
                    "evidence_txn_id": "TXN-X-1",
                },
            )
            self.assertEqual(report["sample_count"], 4)

    def test_core_tie_fails_instead_of_guessing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, status in enumerate(("BREACH", "COMPLIANT"), start=1):
                path = root / "repetitions" / f"{index:03d}" / "submission.json"
                path.parent.mkdir(parents=True)
                path.write_text(
                    json.dumps(
                        {
                            "team": "eval",
                            "contact_email": "eval@example.com",
                            "model": "solver-model",
                            "answers": {
                                "X": {
                                    "6.1": {
                                        "status": status,
                                        "actual": 1.0,
                                        "evidence_txn_id": None,
                                    }
                                }
                            },
                        }
                    ),
                    encoding="utf-8",
                )

            with self.assertRaisesRegex(ValueError, "Unresolved core consensus tie"):
                build_consensus_submission(
                    stability_provider_dir=root,
                    output_path=root / "submission.json",
                    team="Ship Happens",
                    contact_email="zhasserik2019@gmail.com",
                )
