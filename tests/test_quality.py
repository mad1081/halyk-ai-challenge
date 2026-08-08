from __future__ import annotations

import unittest

from halyk_agent.extraction.quality import assess_text_quality


class TextQualityTests(unittest.TestCase):
    def test_rejects_empty_scan_output(self) -> None:
        quality = assess_text_quality("\f\n")
        self.assertFalse(quality.passed)
        self.assertIn("too_few_characters", quality.reasons)

    def test_accepts_substantive_multilingual_text(self) -> None:
        text = "\n".join(
            [
                "# Кредитный договор",
                "Заёмщик: Test Company JSC",
                "Счёт: ACC-1001",
                "Ковенант 6.1 устанавливает ограничение финансового показателя.",
                "Бұл құжатта қарыз алушы туралы қосымша мәлімет берілген.",
            ]
            * 10
        )
        quality = assess_text_quality(text)
        self.assertTrue(quality.passed)
        self.assertGreater(quality.score, 0.7)


if __name__ == "__main__":
    unittest.main()

