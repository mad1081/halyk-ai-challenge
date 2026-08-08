from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from halyk_agent.dataset import DatasetError, DatasetLayout, materialize_dataset
from halyk_agent.ledger import LedgerIndex


class DatasetAndLedgerTests(unittest.TestCase):
    def test_discovers_dataset_and_maps_target_accounts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "dataset"
            self._create_dataset(root)
            layout = DatasetLayout.discover(root)
            template = layout.load_template()
            ledger = LedgerIndex.from_csv(layout.ledger_path)
            self.assertEqual(
                ledger.scenario_accounts(tuple(template["answers"])),
                {"P1": "ACC-1001", "P2": "ACC-1002"},
            )
            self.assertIsNone(ledger.by_scenario["P2"][0].amount)

    def test_safely_materializes_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            dataset = base / "source" / "agentic-bank-public"
            self._create_dataset(dataset)
            archive_path = base / "dataset.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                for path in dataset.rglob("*"):
                    if path.is_file():
                        archive.write(path, path.relative_to(dataset.parent))
            layout = materialize_dataset(archive_path, base / "work")
            self.assertEqual(layout.root.name, "agentic-bank-public")

    def test_rejects_zip_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            archive_path = base / "bad.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../escape.txt", "bad")
            with self.assertRaises(DatasetError):
                materialize_dataset(archive_path, base / "work")

    @staticmethod
    def _create_dataset(root: Path) -> None:
        (root / "documents").mkdir(parents=True)
        (root / "documents" / "one.pdf").write_bytes(b"%PDF-test")
        (root / "submission_template.json").write_text(
            json.dumps(
                {
                    "team": "",
                    "contact_email": "",
                    "model": "",
                    "answers": {
                        scenario: {
                            "6.1": {
                                "status": None,
                                "actual": None,
                                "evidence_txn_id": None,
                            }
                        }
                        for scenario in ("P1", "P2")
                    },
                }
            ),
            encoding="utf-8",
        )
        with (root / "master_ledger_2025.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "txn_id",
                    "date",
                    "account_id",
                    "counterparty",
                    "description",
                    "amount",
                    "currency",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "txn_id": "TXN-P1-0001",
                    "date": "2025-01-01",
                    "account_id": "ACC-1001",
                    "counterparty": "A",
                    "description": "Payment",
                    "amount": "-10.00",
                    "currency": "USD",
                }
            )
            writer.writerow(
                {
                    "txn_id": "TXN-P2-0001",
                    "date": "2025-01-02",
                    "account_id": "ACC-1002",
                    "counterparty": "B",
                    "description": "Receipt",
                    "amount": "",
                    "currency": "EUR",
                }
            )


if __name__ == "__main__":
    unittest.main()
