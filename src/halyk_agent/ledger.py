from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

from halyk_agent.models import Transaction


TXN_PATTERN = re.compile(r"^TXN-([^-]+)-")
REQUIRED_COLUMNS = {
    "txn_id",
    "date",
    "account_id",
    "counterparty",
    "description",
    "amount",
    "currency",
}


class LedgerError(ValueError):
    """Raised when ledger rows cannot be interpreted safely."""


class LedgerIndex:
    def __init__(self, transactions: tuple[Transaction, ...]):
        self.transactions = transactions
        by_scenario: dict[str, list[Transaction]] = {}
        for transaction in transactions:
            by_scenario.setdefault(transaction.scenario_id, []).append(transaction)
        self.by_scenario = {key: tuple(value) for key, value in by_scenario.items()}

    @classmethod
    def from_csv(cls, path: Path) -> "LedgerIndex":
        transactions: list[Transaction] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = REQUIRED_COLUMNS.difference(reader.fieldnames or ())
            if missing:
                raise LedgerError(f"Ledger is missing columns: {', '.join(sorted(missing))}")
            for line_number, row in enumerate(reader, start=2):
                transactions.append(_parse_transaction(row, line_number))
        if not transactions:
            raise LedgerError("Ledger contains no transactions")
        return cls(tuple(transactions))

    def scenario_accounts(self, scenarios: list[str] | tuple[str, ...]) -> dict[str, str]:
        result: dict[str, str] = {}
        for scenario in scenarios:
            rows = self.by_scenario.get(scenario, ())
            accounts = sorted({row.account_id for row in rows})
            if not rows:
                raise LedgerError(f"No ledger rows found for target scenario {scenario}")
            if len(accounts) != 1:
                raise LedgerError(
                    f"Scenario {scenario} maps to {len(accounts)} accounts: {accounts}"
                )
            result[scenario] = accounts[0]
        return result

    def summary(self, target_scenarios: tuple[str, ...]) -> dict:
        target_set = set(target_scenarios)
        currencies: dict[str, int] = {}
        for row in self.transactions:
            currencies[row.currency] = currencies.get(row.currency, 0) + 1
        target_rows = sum(len(self.by_scenario.get(scenario, ())) for scenario in target_set)
        return {
            "row_count": len(self.transactions),
            "scenario_count": len(self.by_scenario),
            "account_count": len({row.account_id for row in self.transactions}),
            "target_scenario_count": len(target_scenarios),
            "target_row_count": target_rows,
            "distractor_row_count": len(self.transactions) - target_rows,
            "missing_amount_count": sum(row.amount is None for row in self.transactions),
            "date_min": min(row.date for row in self.transactions).isoformat(),
            "date_max": max(row.date for row in self.transactions).isoformat(),
            "currencies": dict(sorted(currencies.items())),
        }


def _parse_transaction(row: dict[str, str], line_number: int) -> Transaction:
    txn_id = (row.get("txn_id") or "").strip()
    match = TXN_PATTERN.match(txn_id)
    if not match:
        raise LedgerError(f"Invalid txn_id at ledger line {line_number}: {txn_id!r}")
    amount_text = (row.get("amount") or "").strip()
    try:
        transaction_date = date.fromisoformat((row.get("date") or "").strip())
        amount = Decimal(amount_text) if amount_text else None
    except (ValueError, InvalidOperation) as exc:
        raise LedgerError(f"Invalid date/amount at ledger line {line_number}: {exc}") from exc
    currency = (row.get("currency") or "").strip().upper()
    if not currency:
        raise LedgerError(f"Missing currency at ledger line {line_number}")
    return Transaction(
        txn_id=txn_id,
        scenario_id=match.group(1),
        date=transaction_date,
        account_id=(row.get("account_id") or "").strip(),
        counterparty=(row.get("counterparty") or "").strip(),
        description=(row.get("description") or "").strip(),
        amount=amount,
        currency=currency,
    )
