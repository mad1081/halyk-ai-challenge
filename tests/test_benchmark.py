from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from halyk_agent.benchmark import (
    CATEGORY_PARTITION_POLICY,
    DocumentCatalog,
    SYSTEM_PROMPT,
    _compact_document,
    _discover_scan_image_groups,
    _ocr_account_hint,
    benchmark_schema,
)
from halyk_agent.extraction.pipeline import (
    _low_text_page_numbers,
    _parse_pdfimages_pages,
)


class BenchmarkTests(unittest.TestCase):
    def test_category_partition_policy_requires_primary_evidence(self) -> None:
        self.assertIn("A broad bucket is not an automatic accounting roll-up", CATEGORY_PARTITION_POLICY)
        self.assertIn("row-specific reclassification", CATEGORY_PARTITION_POLICY)
        self.assertIn("generic reference to `related expenses`", CATEGORY_PARTITION_POLICY)
        self.assertIn("social and other taxes", CATEGORY_PARTITION_POLICY)
        self.assertIn("insurance premiums", CATEGORY_PARTITION_POLICY)
        self.assertIn("travel costs", CATEGORY_PARTITION_POLICY)
        self.assertIn("Never classify from the counterparty name", CATEGORY_PARTITION_POLICY)

    def test_category_policy_distinguishes_formula_set_topologies(self) -> None:
        self.assertIn("only among mutually exclusive additive base categories", CATEGORY_PARTITION_POLICY)
        self.assertIn("numerator may be a documented subset of its denominator", CATEGORY_PARTITION_POLICY)
        self.assertIn("signed adjustment bridge", CATEGORY_PARTITION_POLICY)
        self.assertIn("reversing adjustment is intentional", CATEGORY_PARTITION_POLICY)
        self.assertIn("threshold-ineligible adjustment remains in the base", CATEGORY_PARTITION_POLICY)
        self.assertNotIn(
            "partition included transaction IDs into mutually exclusive covenant buckets",
            CATEGORY_PARTITION_POLICY,
        )

    def test_category_policy_keeps_relationship_predicates_covenant_specific(self) -> None:
        self.assertIn("Relationship and status tests are covenant-specific", CATEGORY_PARTITION_POLICY)
        self.assertIn("exact KYC or governing rule designated", CATEGORY_PARTITION_POLICY)
        self.assertIn("do not infer `related party`", CATEGORY_PARTITION_POLICY)
        self.assertIn("subsidiary, restricted, unrestricted", CATEGORY_PARTITION_POLICY)

    def test_category_partition_policy_is_general_not_fixture_specific(self) -> None:
        self.assertNotRegex(CATEGORY_PARTITION_POLICY, r"ACC-|TXN-|P\d+/6\.")
        self.assertIn(CATEGORY_PARTITION_POLICY, SYSTEM_PROMPT)

    def test_compliant_decisions_cannot_claim_counterfactual_evidence(self) -> None:
        self.assertIn(
            "For every COMPLIANT result, `evidence_txn_id` must be null",
            SYSTEM_PROMPT,
        )
        self.assertIn(
            "do not use a hypothetical inclusion or reclassification",
            SYSTEM_PROMPT,
        )

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

    def test_entity_link_adds_group_report_but_rejects_operational_noise(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "agreement.md").write_text(
                "Loan agreement for Example Power Services JSC, account ACC-9001. "
                "Borrower: Example Power Services JSC. Covenant 6.1.",
                encoding="utf-8",
            )
            (directory / "group.md").write_text(
                "CONSOLIDATED ANNUAL REPORT. The Group segment is operated through "
                "Example Power Services JSC. Consolidated financial statements and "
                "capital expenditure note.",
                encoding="utf-8",
            )
            (directory / "noise.md").write_text(
                "Example Power Services JSC operating manual and onboarding "
                "maintenance handbook.",
                encoding="utf-8",
            )
            catalog = DocumentCatalog.from_directory(directory)

            bundle = catalog.for_borrower("ACC-9001")

            self.assertEqual(bundle.primary_entity, "Example Power Services JSC")
            self.assertEqual(
                [record.name for record in bundle.records],
                ["agreement.md", "group.md"],
            )

    def test_compaction_keeps_covenant_and_correction_evidence(self) -> None:
        text = (
            "# Current agreement\n\nBorrower account ACC-9001.\n\n"
            + ("routine operational material " * 200)
            + "\n\nClause 6.1 maximum leverage.\n\n"
            + "The operative threshold stated in the following table is 2.00x.\n\n"
            + ("unrelated facilities notes " * 200)
            + "\n\nFinal auditor reclassification TXN-X-0012 determines the result."
        )

        compact = _compact_document(text, ("6.1",), max_characters=1800)

        self.assertIn("Clause 6.1", compact)
        self.assertIn("operative threshold", compact)
        self.assertIn("TXN-X-0012", compact)
        self.assertLess(len(compact), 2000)

    def test_page_level_scan_detection_does_not_hide_inside_good_document(self) -> None:
        pages = (
            "Text cover page " * 20,
            "",
            "A normal searchable body page " * 20,
        )

        self.assertEqual(_low_text_page_numbers(pages), (2,))

    def test_scan_groups_and_account_hint_support_mixed_pdf_ocr(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            documents = root / "documents"
            documents.mkdir()
            (documents / "abc.md").write_text(
                "Borrower account ACC-9001 and KYC-ACC-9001-2025.",
                encoding="utf-8",
            )
            scan = root / "scan-abc"
            scan.mkdir()
            (scan / "page-0002.png").write_bytes(b"not-a-real-image")

            groups = _discover_scan_image_groups(root)
            catalog = DocumentCatalog.from_directory(documents)

            self.assertEqual(len(groups), 1)
            self.assertEqual([path.name for path in groups[0]], ["page-0002.png"])
            self.assertEqual(_ocr_account_hint(catalog, groups[0]), "ACC-9001")

    def test_large_embedded_image_routes_hybrid_page_but_logo_does_not(self) -> None:
        listing = """
page num type width height color comp bpc enc interp object ID x-ppi y-ppi size ratio
   1   0 image   120  80 rgb 3 8 image yes 1 0 72 72 1K 1%
   2   1 image  1940 3066 gray 1 8 image yes 2 0 308 308 144K 2.5%
   3   2 image   600  400 rgb 3 8 image yes 3 0 150 150 20K 3%
"""

        self.assertEqual(_parse_pdfimages_pages(listing), (2, 3))


if __name__ == "__main__":
    unittest.main()
