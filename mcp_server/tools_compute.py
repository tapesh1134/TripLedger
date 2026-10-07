"""Exact arithmetic, with no network, LLM, policy constants, or float operations."""

from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any

from mcp_server.schemas import ComputeRequest

CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def compute_totals(
    lines: list[dict[str, Any]], caps: list[dict[str, Any]], base_currency: str
) -> dict[str, Any]:
    """Return exact two-decimal strings and line-level evidence.

    All inputs must already be in base_currency (use fx_convert before calculation).
    R-03 style: disallow only amount exceeding limit * quantity.
    R-07 style: disallow the entire line. Overlapping caps never double-count.
    This is a generic calculator, not a policy evaluator or approval engine.
    """
    request = ComputeRequest.model_validate(
        {"lines": lines, "caps": caps, "base_currency": base_currency}
    )
    ids = [line.line_id for line in request.lines]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate compute line_id")
    if any(cap.line_id not in ids for cap in request.caps):
        raise ValueError("cap references an unknown line_id")
    if any(line.currency != request.base_currency for line in request.lines):
        raise ValueError("convert every line to base_currency before compute_totals")

    with localcontext() as context:
        context.prec = 40
        total_allowed = Decimal("0.00")
        total_disallowed = Decimal("0.00")
        per_line: list[dict[str, Any]] = []
        for line in request.lines:
            original = money(line.amount)
            allowed = original
            evaluations: list[dict[str, Any]] = []
            for cap in (item for item in request.caps if item.line_id == line.line_id):
                if cap.kind == "whole_line":
                    permitted = Decimal("0.00")
                    effective_limit: Decimal | None = None
                else:
                    assert cap.limit is not None  # Guaranteed by Cap validation.
                    effective_limit = money(cap.limit * Decimal(cap.quantity))
                    permitted = min(original, effective_limit)
                allowed = min(allowed, permitted)
                evaluations.append(
                    {
                        "rule_id": cap.rule_id,
                        "kind": cap.kind,
                        "effective_limit": (
                            str(effective_limit) if effective_limit is not None else None
                        ),
                        "excess": str(original - permitted),
                    }
                )
            disallowed = original - allowed
            total_allowed += allowed
            total_disallowed += disallowed
            per_line.append(
                {
                    "line_id": line.line_id,
                    "amount": str(original),
                    "reimbursable": str(allowed),
                    "disallowed": str(disallowed),
                    "evaluations": evaluations,
                }
            )
        return {
            "currency": request.base_currency,
            "reimbursable": str(total_allowed),
            "disallowed": str(total_disallowed),
            "per_line": per_line,
        }
