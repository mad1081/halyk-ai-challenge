from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from halyk_agent.extraction.backends import CascadeExtractor


class FakeBackend:
    def __init__(self, name: str, text: str, available: bool = True):
        self.name = name
        self.text = text
        self._available = available

    def available(self) -> bool:
        return self._available

    def extract(self, pdf_path: Path, timeout: float) -> str:
        return self.text


class CascadeTests(unittest.TestCase):
    def test_falls_back_when_first_output_is_low_quality(self) -> None:
        good = "\n".join(
            [
                "# Credit agreement",
                "Borrower account ACC-1001",
                "Section 6.1 contains a financial covenant and supporting values.",
            ]
            * 20
        )
        extractor = CascadeExtractor(
            [FakeBackend("native", "\f"), FakeBackend("ocr", good)]
        )
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "scan.pdf"
            source.write_bytes(b"pdf")
            result = extractor.extract(source)
        self.assertEqual(result.selected_backend, "ocr")
        self.assertTrue(result.quality.passed)
        self.assertEqual([attempt.status for attempt in result.attempts], ["success", "success"])

    def test_records_unavailable_backend(self) -> None:
        good = ("Useful financial document content ACC-1001\n" * 30).strip()
        extractor = CascadeExtractor(
            [FakeBackend("missing", "", available=False), FakeBackend("native", good)]
        )
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "document.pdf"
            source.write_bytes(b"pdf")
            result = extractor.extract(source)
        self.assertEqual(result.attempts[0].status, "unavailable")
        self.assertEqual(result.selected_backend, "native")


if __name__ == "__main__":
    unittest.main()

