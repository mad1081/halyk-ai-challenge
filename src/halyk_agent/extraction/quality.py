from __future__ import annotations

from halyk_agent.models import TextQuality


def assess_text_quality(text: str) -> TextQuality:
    stripped = text.strip()
    characters = len(stripped)
    lines = sum(1 for line in stripped.splitlines() if line.strip())
    alphanumeric = sum(character.isalnum() for character in stripped)
    printable = sum(character.isprintable() or character in "\n\r\t" for character in stripped)
    replacements = stripped.count("\ufffd")
    alphanumeric_ratio = alphanumeric / characters if characters else 0.0
    printable_ratio = printable / characters if characters else 0.0
    replacement_ratio = replacements / characters if characters else 1.0

    reasons: list[str] = []
    if characters < 200:
        reasons.append("too_few_characters")
    if lines < 3:
        reasons.append("too_few_lines")
    if alphanumeric_ratio < 0.35:
        reasons.append("low_alphanumeric_ratio")
    if printable_ratio < 0.85:
        reasons.append("low_printable_ratio")
    if replacement_ratio > 0.005:
        reasons.append("high_replacement_ratio")

    length_score = min(characters / 1200.0, 1.0)
    line_score = min(lines / 20.0, 1.0)
    alpha_score = min(alphanumeric_ratio / 0.65, 1.0)
    printable_score = min(printable_ratio / 0.98, 1.0)
    replacement_score = max(0.0, 1.0 - replacement_ratio / 0.005)
    score = round(
        0.30 * length_score
        + 0.10 * line_score
        + 0.30 * alpha_score
        + 0.15 * printable_score
        + 0.15 * replacement_score,
        4,
    )
    return TextQuality(
        passed=not reasons,
        score=score,
        characters=characters,
        lines=lines,
        alphanumeric_ratio=round(alphanumeric_ratio, 4),
        printable_ratio=round(printable_ratio, 4),
        replacement_ratio=round(replacement_ratio, 6),
        reasons=tuple(reasons),
    )
