from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Transaction:
    txn_id: str
    scenario_id: str
    date: date
    account_id: str
    counterparty: str
    description: str
    # Blank amounts occur in the public ledger and must remain distinguishable
    # from a real zero until the covenant-specific normalization step.
    amount: Decimal | None
    currency: str


@dataclass(frozen=True, slots=True)
class TextQuality:
    passed: bool
    score: float
    characters: int
    lines: int
    alphanumeric_ratio: float
    printable_ratio: float
    replacement_ratio: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["reasons"] = list(self.reasons)
        return result


@dataclass(frozen=True, slots=True)
class ExtractionAttempt:
    backend: str
    status: str
    seconds: float
    quality: TextQuality | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "status": self.status,
            "seconds": self.seconds,
            "quality": self.quality.to_dict() if self.quality else None,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    source: Path
    markdown: str
    selected_backend: str
    quality: TextQuality
    attempts: tuple[ExtractionAttempt, ...]
