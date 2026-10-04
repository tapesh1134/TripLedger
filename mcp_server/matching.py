"""Deterministic candidate scoring. No model call and no final match decision."""

import re
import unicodedata
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any

from mcp_server.tool_contracts import MatchArgs


def normalize_merchant(text: str) -> str:
    cleaned = unicodedata.normalize("NFKD", text.casefold())
    cleaned = "".join(c for c in cleaned if not unicodedata.combining(c))
    if re.match(r"^uber\b", cleaned):
        return "uber"
    cleaned = re.sub(r"https?://\S+|www\.\S+", " ", cleaned)
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", cleaned)
    return " ".join(word for word in cleaned.split() if word not in {"ltd", "limited", "bv", "inc"})


def match_transactions(
    lines: list[dict[str, Any]], transactions: list[dict[str, Any]]
) -> dict[str, Any]:
    args = MatchArgs.model_validate({"lines": lines, "transactions": transactions})
    pairs: list[dict[str, Any]] = []
    matched_lines: set[str] = set()
    matched_transactions: set[str] = set()
    for line in args.lines:
        for txn in args.transactions:
            if line.currency != txn.currency:
                continue  # FX is explicit; never compare different currency amounts.
            days = abs((line.date - txn.posted_date).days)
            if days > 3:
                continue
            left, right = normalize_merchant(line.merchant), normalize_merchant(txn.merchant_raw)
            merchant = SequenceMatcher(None, left, right).ratio() if left and right else 0.0
            if merchant < 0.45:
                continue
            delta = abs(line.amount - txn.amount)
            denominator = max(line.amount, txn.amount)
            ratio = delta / denominator if denominator else Decimal("0")
            tolerance = Decimal("0.20") if line.category in {"taxi", "meals"} else Decimal("0.02")
            if ratio > tolerance:
                continue
            amount_score = Decimal("1") - ratio
            date_score = 1 - days / 4
            score = round(0.55 * merchant + 0.30 * float(amount_score) + 0.15 * date_score, 4)
            if score < 0.70:
                continue
            pairs.append(
                {
                    "line_id": line.line_id,
                    "txn_id": txn.txn_id,
                    "score": score,
                    "amount_delta": str(delta),
                    "currency": line.currency,
                    "reasons": [
                        f"merchant_similarity={merchant:.4f}",
                        f"date_gap_days={days}",
                        "amount_exact" if delta == 0 else "amount_within_matching_tolerance",
                    ],
                }
            )
            matched_lines.add(line.line_id)
            matched_transactions.add(txn.txn_id)
    pairs.sort(key=lambda x: (-float(x["score"]), str(x["line_id"]), str(x["txn_id"])))
    counts: dict[str, int] = {}
    kept = []
    for pair in pairs:
        lid = pair["line_id"]
        counts[lid] = counts.get(lid, 0) + 1
        if counts[lid] <= 3:
            kept.append(pair)
    dropped = len(pairs) - len(kept)
    pairs = kept
    matched_lines = {x["line_id"] for x in pairs}
    matched_transactions = {x["txn_id"] for x in pairs}
    return {
        "candidates_omitted": dropped,
        "pairs": pairs,
        "unmatched_lines": [x.line_id for x in args.lines if x.line_id not in matched_lines],
        "unmatched_transactions": [
            x.txn_id for x in args.transactions if x.txn_id not in matched_transactions
        ],
        "note": (
            "Top 3 candidates per line; shared IDs require adjudication. "
            "Omitted candidates may exist."
        ),
    }
