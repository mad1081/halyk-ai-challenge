from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import unittest

from halyk_agent.fx import build_fx_normalization, extract_fx_observations
from halyk_agent.models import Transaction


@dataclass(frozen=True)
class Record:
    name: str
    text: str


def transaction(amount: str, *, counterparty: str = "Rheinland Katalyse GmbH") -> Transaction:
    return Transaction(
        txn_id="TXN-X-0001",
        scenario_id="X",
        date=date(2025, 5, 7),
        account_id="ACC-1",
        counterparty=counterparty,
        description="Catalyst servicing",
        amount=Decimal(amount),
        currency="EUR",
    )


class FxNormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.record = Record(
            "audit.md",
            "## Валютные курсы\n\n"
            "Расчёты с контрагентом «Rheinland Katalyse GmbH»: "
            "счёт на сумму 72,146.75 EUR урегулирован платежом "
            "в долларах США в размере $83,690.23.",
        )

    def test_different_target_amount_uses_derived_unit_rate(self) -> None:
        result = build_fx_normalization(
            (self.record,), (transaction("-612884.25"),)
        )

        self.assertIn("rate=1.16 USD/EUR", result)
        self.assertIn("612884.25 * 1.16 USD/EUR", result)
        self.assertIn("normalized_usd=-710945.73", result)
        self.assertNotIn("normalized_usd=-83690.23", result)
        self.assertIn("never substitute that USD amount", result)

    def test_exact_reference_amount_uses_corresponding_usd_and_preserves_sign(self) -> None:
        positive = build_fx_normalization(
            (self.record,), (transaction("72146.75"),)
        )
        negative = build_fx_normalization(
            (self.record,), (transaction("-72146.75"),)
        )

        self.assertIn("exact reference-amount match", positive)
        self.assertIn("normalized_usd=83690.23", positive)
        self.assertIn("normalized_usd=-83690.23", negative)

    def test_conflicting_rates_are_reported_but_not_applied(self) -> None:
        conflicting = Record(
            "second-audit.md",
            "FX rate settlement with Rheinland Katalyse GmbH: "
            "100 EUR converted to $120.",
        )
        first = Record(
            "first-audit.md",
            "FX rate settlement with Rheinland Katalyse GmbH: "
            "100 EUR converted to $110.",
        )

        result = build_fx_normalization(
            (first, conflicting), (transaction("-250"),)
        )

        self.assertIn("CONFLICT", result)
        self.assertIn("1.1", result)
        self.assertIn("1.2", result)
        self.assertNotIn("normalized_usd=", result)

    def test_no_explicit_pair_or_counterparty_link_produces_no_annotation(self) -> None:
        no_pair = Record(
            "policy.md",
            "Foreign-currency transactions use the rate applicable on settlement.",
        )
        wrong_party = transaction(
            "-612884.25", counterparty="Unrelated Supplier LLP"
        )

        self.assertEqual(build_fx_normalization((no_pair,), (transaction("-1"),)), "")
        self.assertEqual(build_fx_normalization((self.record,), (wrong_party,)), "")

    def test_extractor_accepts_european_number_separators(self) -> None:
        record = Record(
            "european.md",
            "FX settlement for Rheinland Katalyse GmbH: "
            "72 146,75 EUR converted to USD 83 690,23.",
        )

        observations = extract_fx_observations((record,))

        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].foreign_amount, Decimal("72146.75"))
        self.assertEqual(observations[0].usd_amount, Decimal("83690.23"))
        self.assertEqual(observations[0].usd_per_unit, Decimal("1.16"))

    def test_separate_bank_commission_does_not_hide_settlement_pair(self) -> None:
        record = Record(
            "treasury.md",
            "Расчёты с контрагентом «Rheinland Katalyse GmbH»: "
            "счёт на сумму 76,384.20 EUR урегулирован платежом "
            "в долларах США в размере $82,638.45, отражённым за вычетом "
            "банковской комиссии в размере $1,384.17, которая не входит "
            "в пересчитываемую сумму.",
        )

        result = build_fx_normalization(
            (record,), (transaction("-410297.69"),)
        )

        self.assertIn("normalized_usd=-443892.39", result)
        self.assertNotIn("1384.17 USD/EUR", result)


if __name__ == "__main__":
    unittest.main()
