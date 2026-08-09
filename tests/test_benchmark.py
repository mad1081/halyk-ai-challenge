from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from halyk_agent.benchmark import (
    BenchmarkError,
    CATEGORY_PARTITION_POLICY,
    DocumentCatalog,
    SYSTEM_PROMPT,
    _compact_document,
    _discover_scan_image_groups,
    _ocr_account_hint,
    _source_pdf_page_numbers,
    benchmark_schema,
    run_live_benchmark,
)
from halyk_agent.extraction.pipeline import (
    _low_text_page_numbers,
    _parse_pdftohtml_image_analysis,
    _parse_pdfimages_pages,
)


class BenchmarkTests(unittest.TestCase):
    def test_private_generation_requires_submission_identity_before_api(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "documents").mkdir()
            (root / "master_ledger_2025.csv").write_text("placeholder\n", encoding="utf-8")
            (root / "submission_template.json").write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(
                BenchmarkError, "requires both --team and --contact-email"
            ):
                run_live_benchmark(
                    dataset=root,
                    documents_dir=root / "documents",
                    output_dir=root / "run",
                    providers=(),
                    env_file=root / ".env",
                )

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

    def test_final_cutoff_period_applies_across_period_based_metrics(self) -> None:
        self.assertIn("final audit cutoff or performance-period", CATEGORY_PARTITION_POLICY)
        self.assertIn("every period-based covenant", CATEGORY_PARTITION_POLICY)
        self.assertIn("cash or invoice date", CATEGORY_PARTITION_POLICY)
        self.assertNotRegex(CATEGORY_PARTITION_POLICY, r"ACC-|TXN-|P\d+/6\.")

    def test_fx_normalization_preserves_direct_operating_service_category(self) -> None:
        self.assertIn(
            "Foreign-currency normalization changes only the measurement currency and amount",
            CATEGORY_PARTITION_POLICY,
        )
        self.assertIn("never erases or creates the category", CATEGORY_PARTITION_POLICY)
        self.assertIn(
            "direct servicing, maintenance, repair, or process regeneration",
            CATEGORY_PARTITION_POLICY,
        )
        self.assertIn("remains an Operating Expense", CATEGORY_PARTITION_POLICY)
        self.assertIn(
            "Do not demand a separate final reclassification merely because",
            CATEGORY_PARTITION_POLICY,
        )
        self.assertIn(
            "does not roll separately labelled utility, telecom, payroll",
            CATEGORY_PARTITION_POLICY,
        )

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

    def test_digits_cannot_hide_a_missing_native_text_layer(self) -> None:
        digits_only = ("$1,234,567.89 42.75% 2025-12-31 7805-0042 " * 8,)

        self.assertGreater(sum(char.isdigit() for char in digits_only[0]), 40)
        self.assertEqual(sum(char.isalpha() for char in digits_only[0]), 0)
        self.assertEqual(_low_text_page_numbers(digits_only), (1,))

    def test_page_level_replacement_corruption_routes_to_ocr(self) -> None:
        corrupted = (("Readable covenant wording and classifications. " * 20) + "\ufffd" * 8,)

        self.assertGreater(sum(char.isalpha() for char in corrupted[0]), 40)
        self.assertEqual(_low_text_page_numbers(corrupted), (1,))

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

    def test_display_geometry_routes_low_resolution_image_on_text_rich_page(self) -> None:
        pages = ("Selectable covenant and audit text. " * 30,)
        xml = """<pdf2xml><page number="1" width="1000" height="1000">
          <image top="100" left="100" width="650" height="600" src="low-res.png"/>
        </page></pdf2xml>"""

        analysis = _parse_pdftohtml_image_analysis(xml)

        self.assertEqual(_low_text_page_numbers(pages), ())
        self.assertTrue(analysis[0]["routed"])
        self.assertAlmostEqual(analysis[0]["max_image_coverage"], 0.39)
        self.assertIn("displayed_image_coverage", analysis[0]["reasons"])

    def test_display_geometry_routes_tiled_scan_by_union_coverage(self) -> None:
        xml = """<pdf2xml><page number="4" width="1000" height="1000">
          <image top="100" left="100" width="90" height="90" src="tile-1.png"/>
          <image top="100" left="300" width="90" height="90" src="tile-2.png"/>
          <image top="300" left="100" width="90" height="90" src="tile-3.png"/>
          <image top="300" left="300" width="90" height="90" src="tile-4.png"/>
        </page></pdf2xml>"""

        analysis = _parse_pdftohtml_image_analysis(xml)

        self.assertTrue(analysis[0]["routed"])
        self.assertLess(analysis[0]["max_image_coverage"], 0.02)
        self.assertGreater(analysis[0]["union_image_coverage"], 0.03)
        self.assertIn("displayed_image_union_coverage", analysis[0]["reasons"])

    def test_display_geometry_excludes_small_logo(self) -> None:
        xml = """<pdf2xml><page number="2" width="1000" height="1000">
          <image top="20" left="20" width="120" height="80" src="logo.png"/>
        </page></pdf2xml>"""

        analysis = _parse_pdftohtml_image_analysis(xml)

        self.assertFalse(analysis[0]["routed"])
        self.assertEqual(analysis[0]["reasons"], ["below_displayed_image_threshold"])

    def test_full_page_scan_routes_even_with_ocr_text_layer(self) -> None:
        native_pages = ("An OCR layer with plenty of selectable text. " * 40,)
        xml = """<pdf2xml><page number="1" width="1000" height="1000">
          <image top="0" left="0" width="1000" height="1000" src="scan.png"/>
          <text top="20" left="20" width="400" height="20">Selectable OCR text</text>
        </page></pdf2xml>"""

        analysis = _parse_pdftohtml_image_analysis(xml)

        self.assertEqual(_low_text_page_numbers(native_pages), ())
        self.assertTrue(analysis[0]["routed"])
        self.assertEqual(analysis[0]["union_image_coverage"], 1.0)

    def test_scan_page_provenance_uses_original_pdf_numbers(self) -> None:
        paths = (
            Path("scan-example/page-0003.png"),
            Path("scan-example/page-0011.png"),
        )

        self.assertEqual(_source_pdf_page_numbers(paths), (3, 11))


if __name__ == "__main__":
    unittest.main()
