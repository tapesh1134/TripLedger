"""Synthetic report intake: validation and redaction before model/API/log use."""

import re
from typing import Any

from mcp_server.schemas import ExpenseReport

EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
DIGITS = re.compile(r"(?<!\w)\+?\d(?:[\d ()-]*\d)?(?!\w)")


def redact(value: Any, counts: dict[str, int] | None = None) -> Any:
    counts = counts if counts is not None else {}
    if isinstance(value, dict):
        return {key: redact(item, counts) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, counts) for item in value]
    if not isinstance(value, str):
        return value

    def email(match: re.Match[str]) -> str:
        counts["emails"] = counts.get("emails", 0) + 1
        return "[REDACTED_EMAIL]"

    def number(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group())
        if len(digits) > 19:
            counts["numeric_sequences"] = counts.get("numeric_sequences", 0) + 1
            return "[REDACTED_NUMERIC_SEQUENCE]"
        if 13 <= len(digits) <= 19:
            counts["card_like"] = counts.get("card_like", 0) + 1
            return "****" + digits[-4:]
        if 10 <= len(digits) <= 12:
            counts["phones"] = counts.get("phones", 0) + 1
            return "[REDACTED_PHONE]"
        return match.group()

    return DIGITS.sub(number, EMAIL.sub(email, value))


def intake(raw: Any) -> tuple[ExpenseReport, dict[str, int]]:
    counts: dict[str, int] = {}
    return ExpenseReport.model_validate(redact(raw, counts)), counts
