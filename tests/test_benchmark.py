from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from halyk_agent.benchmark import DocumentCatalog, benchmark_schema


class BenchmarkTests(unittest.TestCase):
    def test_document_catalog_retrieves_by_account_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "one.md").write_text(
                "Borrower account ACC-7801", encoding="utf-8"
            )
            (directory / "two.md").write_text(
                "Borrower account ACC-7802", encoding="utf-8"
            )
            catalog = DocumentCatalog.from_directory(directory)

            self.assertEqual(
                [record.name for record in catalog.for_account("acc-7801")],
                ["one.md"],
            )

    def test_schema_requires_each_covenant_and_no_extra_keys(self) -> None:
        schema = benchmark_schema(("6.1", "6.2", "6.3"))
        decisions = schema["properties"]["decisions"]
        self.assertEqual(decisions["required"], ["6.1", "6.2", "6.3"])
        self.assertFalse(decisions["additionalProperties"])
        self.assertEqual(
            decisions["properties"]["6.1"]["properties"]["status"]["enum"],
            ["COMPLIANT", "BREACH"],
        )


if __name__ == "__main__":
    unittest.main()
