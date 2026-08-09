from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Iterable, Protocol


class TextRecord(Protocol):
    name: str
    text: str


class LedgerTransaction(Protocol):
    txn_id: str
    counterparty: str
    amount: Decimal | None
    currency: str


@dataclass(frozen=True, slots=True)
class FxObservation:
    """An explicit foreign-currency/USD pair recovered from a source document."""

    source_name: str
    foreign_currency: str
    foreign_amount: Decimal
    usd_amount: Decimal
    usd_per_unit: Decimal
    context: str


_NUMBER = r"[+-]?(?:\d{1,3}(?:[\s\u00a0,.'\u2019]\d{3})+|\d+)(?:[.,]\d+)?"
_CURRENCY = r"USD|US\$|\$|EUR|\u20ac|GBP|\u00a3|KZT|\u20b8"
_MONEY = re.compile(
    rf"(?:"
    rf"(?P<prefix_currency>{_CURRENCY})\s*(?P<prefix_amount>{_NUMBER})"
    rf"|"
    rf"(?P<suffix_amount>{_NUMBER})\s*(?P<suffix_currency>{_CURRENCY})"
    rf")",
    re.IGNORECASE,
)
_FX_SIGNALS = (
    "exchange rate",
    "foreign currency",
    "fx rate",
    "settled",
    "settlement",
    "convert",
    "currency",
    "валют",
    "курс",
    "пересчит",
    "урегулирован",
    "доллар",
)
_EXCLUDED_CHARGE = re.compile(
    r"(?:bank\s+)?(?:fee|commission)|банковск\w*\s+комисс|комисс",
    re.IGNORECASE,
)
_CURRENCY_ALIASES = {
    "$": "USD",
    "US$": "USD",
    "USD": "USD",
    "€": "EUR",
    "EUR": "EUR",
    "£": "GBP",
    "GBP": "GBP",
    "₸": "KZT",
    "KZT": "KZT",
}
_CENT = Decimal("0.01")


def extract_fx_observations(records: Iterable[TextRecord]) -> tuple[FxObservation, ...]:
    """Extract explicit FX reference pairs without inventing outside rates.

    A paragraph must contain an FX-related signal and both a USD amount and a
    non-USD amount. This intentionally favors precision over recall: ambiguous
    prose is left for the covenant model rather than converted silently.
    """

    observations: list[FxObservation] = []
    seen: set[tuple[str, str, Decimal, Decimal]] = set()
    for record in records:
        for paragraph in re.split(r"\n\s*\n", record.text):
            folded = paragraph.casefold()
            if not any(signal in folded for signal in _FX_SIGNALS):
                continue
            amounts = _money_amounts(paragraph, exclude_separate_charges=True)
            usd_amounts = [amount for currency, amount in amounts if currency == "USD"]
            foreign_amounts = [
                (currency, amount) for currency, amount in amounts if currency != "USD"
            ]
            # Pairing more than one amount on either side requires document
            # semantics that a regex cannot establish safely.
            if len(usd_amounts) != 1 or len(foreign_amounts) != 1:
                continue
            foreign_currency, foreign_amount = foreign_amounts[0]
            usd_amount = usd_amounts[0]
            if foreign_amount == 0:
                continue
            key = (record.name, foreign_currency, foreign_amount, usd_amount)
            if key in seen:
                continue
            seen.add(key)
            observations.append(
                FxObservation(
                    source_name=record.name,
                    foreign_currency=foreign_currency,
                    foreign_amount=foreign_amount,
                    usd_amount=usd_amount,
                    usd_per_unit=usd_amount / foreign_amount,
                    context=" ".join(paragraph.split()),
                )
            )
    return tuple(observations)


def build_fx_normalization(
    records: Iterable[TextRecord], transactions: Iterable[LedgerTransaction]
) -> str:
    """Render deterministic FX arithmetic for unambiguously linked ledger rows.

    The source pair is linked to a transaction only when its paragraph names
    that transaction's counterparty. Multiple observations are acceptable when
    they imply the same rate; conflicting rates are surfaced but never chosen.
    """

    observations = extract_fx_observations(records)
    if not observations:
        return ""

    normalized: list[str] = []
    references: dict[tuple[str, str, Decimal, Decimal], FxObservation] = {}
    for transaction in transactions:
        currency = transaction.currency.strip().upper()
        if transaction.amount is None or currency == "USD":
            continue
        candidates = [
            observation
            for observation in observations
            if observation.foreign_currency == currency
            and _mentions_counterparty(observation.context, transaction.counterparty)
        ]
        if not candidates:
            continue
        for observation in candidates:
            references[
                (
                    observation.source_name,
                    observation.foreign_currency,
                    observation.foreign_amount,
                    observation.usd_amount,
                )
            ] = observation

        rates = {observation.usd_per_unit for observation in candidates}
        if len(rates) != 1:
            rendered_rates = ", ".join(
                sorted(_format_decimal(rate) for rate in rates)
            )
            normalized.append(
                f"- {transaction.txn_id}: original="
                f"{_format_decimal(transaction.amount)} {currency}; "
                f"CONFLICT: multiple applicable USD/{currency} rates "
                f"({rendered_rates}); no normalized amount was calculated."
            )
            continue

        rate = next(iter(rates))
        magnitude = abs(transaction.amount)
        exact_matches = [
            observation
            for observation in candidates
            if observation.foreign_amount == magnitude
        ]
        if exact_matches:
            converted_magnitude = exact_matches[0].usd_amount
            method = (
                "exact reference-amount match: "
                f"{_format_decimal(magnitude)} {currency} -> "
                f"{_format_decimal(converted_magnitude)} USD"
            )
        else:
            converted_magnitude = (magnitude * rate).quantize(
                _CENT, rounding=ROUND_HALF_UP
            )
            method = (
                f"{_format_decimal(magnitude)} * {_format_decimal(rate)} "
                f"USD/{currency}"
            )
        converted = converted_magnitude.copy_sign(transaction.amount)
        sources = ",".join(sorted({item.source_name for item in candidates}))
        normalized.append(
            f"- {transaction.txn_id}: original="
            f"{_format_decimal(transaction.amount)} {currency}; "
            f"calculation={method}; normalized_usd={_format_decimal(converted)}; "
            f"source={sources}."
        )

    if not normalized:
        return ""

    reference_lines = [
        "- "
        f"source={observation.source_name}; "
        f"{_format_decimal(observation.foreign_amount)} "
        f"{observation.foreign_currency} -> "
        f"{_format_decimal(observation.usd_amount)} USD; "
        f"rate={_format_decimal(observation.usd_per_unit)} "
        f"USD/{observation.foreign_currency}."
        for observation in sorted(
            references.values(),
            key=lambda item: (
                item.source_name.casefold(),
                item.foreign_currency,
                item.foreign_amount,
                item.usd_amount,
            ),
        )
    ]
    return (
        "A reference pair defines a unit exchange rate. Its USD amount is the "
        "value of the reference foreign amount only; never substitute that USD "
        "amount for a ledger row whose foreign amount differs. Preserve the "
        "ledger sign. Treat conflicts as unresolved.\n"
        "REFERENCE FX RATE OBSERVATIONS:\n"
        + "\n".join(reference_lines)
        + "\nNORMALIZED NON-USD LEDGER ROWS:\n"
        + "\n".join(normalized)
        + "\n"
    )


def _money_amounts(
    text: str, *, exclude_separate_charges: bool = False
) -> list[tuple[str, Decimal]]:
    amounts: list[tuple[str, Decimal]] = []
    for match in _MONEY.finditer(text):
        if exclude_separate_charges:
            prefix = text[max(0, match.start() - 96) : match.start()]
            if _EXCLUDED_CHARGE.search(prefix):
                continue
        currency_token = match.group("prefix_currency") or match.group(
            "suffix_currency"
        )
        amount_token = match.group("prefix_amount") or match.group("suffix_amount")
        try:
            amount = _parse_decimal(amount_token)
        except InvalidOperation:
            continue
        currency = _CURRENCY_ALIASES[currency_token.upper()]
        amounts.append((currency, abs(amount)))
    return amounts


def _parse_decimal(value: str) -> Decimal:
    normalized = value.strip().replace("\u00a0", "").replace(" ", "")
    normalized = normalized.replace("'", "").replace("\u2019", "")
    if "," in normalized and "." in normalized:
        if normalized.rfind(".") > normalized.rfind(","):
            normalized = normalized.replace(",", "")
        else:
            normalized = normalized.replace(".", "").replace(",", ".")
    elif "," in normalized:
        head, tail = normalized.rsplit(",", 1)
        normalized = head + ("" if len(tail) == 3 else ".") + tail
    elif "." in normalized:
        head, tail = normalized.rsplit(".", 1)
        if len(tail) == 3:
            normalized = head + tail
    return Decimal(normalized)


def _mentions_counterparty(context: str, counterparty: str) -> bool:
    context_key = _normalize_name(context)
    counterparty_key = _normalize_name(counterparty)
    return bool(counterparty_key) and counterparty_key in context_key


def _normalize_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _format_decimal(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"
