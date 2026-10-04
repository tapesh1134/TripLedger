"""Schema, provenance, receipt and independent teaching-policy verification."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from app.evidence import validate_evidence
from app.policy_guard import verify_policy
from mcp_server.matching import match_transactions
from mcp_server.schemas import Decision, ExpenseReport


def validate_candidate(
    candidate: dict[str, Any],
    report: ExpenseReport,
    events: list[dict[str, Any]],
    meta: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[Decision | None, list[str]]:
    try:
        decision = Decision.model_validate({**candidate, "meta": meta})
    except ValidationError as error:
        details = [
            ".".join(str(x) for x in e["loc"]) + ": " + e["type"]
            for e in error.errors(include_input=False, include_context=False)
        ]
        return None, ["Final schema: " + detail for detail in details]
    problems = []
    if decision.report_id != report.report_id:
        problems.append("Wrong report_id.")
    line_ids = {x.line_id for x in report.line_items}
    if {x.line_id for x in decision.reconciliation} != line_ids or len(
        decision.reconciliation
    ) != len(line_ids):
        problems.append("Reconciliation must cover every report line exactly once.")
    successful = [e for e in events if e.get("result", {}).get("ok")]
    names = {e["name"] for e in successful}
    for required in (
        "get_employee",
        "get_trip",
        "list_card_transactions",
        "list_settled_lines",
        "match_transactions",
        "compute_totals",
    ):
        if required not in names:
            problems.append("Missing successful tool: " + required)
    pages = [e for e in successful if e["name"] == "list_card_transactions"]
    transactions = {t["txn_id"]: t for e in pages for t in e["result"]["data"]["items"]}
    for page in pages:
        cursor = page["result"]["data"].get("next_cursor")
        if cursor is not None and not any(
            other["args"].get("cursor") == cursor
            and all(
                other["args"].get(key) == page["args"].get(key)
                for key in ("employee_id", "from", "to")
            )
            for other in pages
        ):
            problems.append("Pending transaction page: cursor " + cursor)
    for item in decision.reconciliation:
        if item.transaction_id is not None and item.transaction_id not in transactions:
            problems.append("Unseen transaction ID: " + item.transaction_id)
    # Tool calls are scoped to the report in the loop, but also check response identity.
    if not any(
        e["name"] == "get_employee" and e["result"]["data"].get("employee_id") == report.employee_id
        for e in successful
    ):
        problems.append("Employee evidence does not match the report.")
    if not any(
        e["name"] == "get_trip" and e["result"]["data"].get("trip_id") == report.trip_id
        for e in successful
    ):
        problems.append("Trip evidence does not match the report.")
    trips = [e["result"]["data"] for e in successful if e["name"] == "get_trip"]
    if trips:
        trip = trips[-1]
        start = (date.fromisoformat(trip["start_date"]) - timedelta(days=2)).isoformat()
        end = (date.fromisoformat(trip["end_date"]) + timedelta(days=2)).isoformat()
        if not any(
            e["args"].get("from", "z") <= start
            and e["args"].get("to", "") >= end
            and e["args"].get("cursor") in (None, "0")
            for e in pages
        ):
            problems.append(
                "Card history must start at the first page and cover trip dates +/-2 days."
            )
    if not any(
        e["name"] == "list_settled_lines" and e["args"].get("months", 12) == 12 for e in successful
    ):
        problems.append("Read twelve months of settled history.")
    pairs = {
        (x["line_id"], x["txn_id"])
        for e in successful
        if e["name"] == "match_transactions"
        for x in e["result"]["data"]["pairs"]
    }
    selected = [x.transaction_id for x in decision.reconciliation if x.status == "matched"]
    if len(selected) != len(set(selected)):
        problems.append("A transaction cannot support multiple matched report lines.")
    for item in decision.reconciliation:
        if item.status == "matched" and (item.line_id, item.transaction_id) not in pairs:
            problems.append("Matched reconciliation must use a returned candidate: " + item.line_id)
    for line in report.line_items:
        if line.receipt_file and not any(
            e["name"] == "read_receipt" and e["args"].get("file_path") == line.receipt_file
            for e in events
        ):
            problems.append("Attached receipt has not been attempted: " + line.line_id)
    computations = [e for e in successful if e["name"] == "compute_totals"]
    if computations:
        last = computations[-1]
        data = last["result"]["data"]
        if {x["line_id"] for x in last["args"]["lines"]} != line_ids:
            problems.append("compute_totals must cover every report line.")
        originals = {x.line_id: x for x in report.line_items}
        for line in last["args"]["lines"]:
            original = originals.get(line["line_id"])
            if original is None:
                continue
            if original.currency == report.base_currency:
                if Decimal(str(line["amount"])) != original.amount:
                    problems.append("Calculation input altered report amount: " + original.line_id)
            elif not any(
                e["name"] == "fx_convert"
                and e["args"].get("from_ccy") == original.currency
                and e["args"].get("to_ccy") == report.base_currency
                and e["args"].get("on_date") == original.date.isoformat()
                and Decimal(str(e["args"].get("amount"))) == original.amount
                and Decimal(e["result"]["data"]["amount"]) == Decimal(str(line["amount"]))
                for e in successful
            ):
                problems.append("Missing matching FX result: " + original.line_id)
        if (
            decision.reimbursable_total.amount != Decimal(data["reimbursable"])
            or decision.disallowed_total.amount != Decimal(data["disallowed"])
            or data["currency"] != report.base_currency
            or decision.reimbursable_total.currency != report.base_currency
            or decision.disallowed_total.currency != report.base_currency
        ):
            problems.append(
                "Decision totals must equal the last compute_totals output in base currency."
            )
    if decision.decision == "auto_approve":
        if (
            any(x.severity in {"blocking", "query"} for x in decision.findings)
            or decision.confidence < Decimal(str(policy["minimum_auto_approval_confidence"]))
            or decision.reimbursable_total.amount >= Decimal(str(policy["auto_approval_ceiling"]))
            or decision.duplicate_candidates
            or any(x.status != "matched" for x in decision.reconciliation)
        ):
            problems.append("Auto-approval gate failed; use manager_review.")
    problems.extend(validate_evidence(decision, report, events))
    # Recompute candidate matches from original report lines and fetched cards.
    original_lines = [
        {
            "line_id": x.line_id,
            "date": x.date.isoformat(),
            "merchant": x.merchant,
            "amount": str(x.amount),
            "currency": x.currency,
            "category": x.category,
        }
        for x in report.line_items
    ]
    actual_pairs = match_transactions(original_lines, list(transactions.values()))["pairs"]
    by_pair = {(p["line_id"], p["txn_id"]): p for p in actual_pairs}
    for item in decision.reconciliation:
        if item.status == "missing_transaction" and item.transaction_id is not None:
            problems.append(
                "missing_transaction must not contain a transaction ID: " + item.line_id
            )
        if item.transaction_id is None:
            exact = [p for p in actual_pairs if p["line_id"] == item.line_id and p["score"] == 1.0]
            if len(exact) == 1:
                txn_id = exact[0]["txn_id"]
                contested = any(
                    p["txn_id"] == txn_id and p["line_id"] != item.line_id and p["score"] == 1.0
                    for p in actual_pairs
                )
                assigned = any(x.transaction_id == txn_id for x in decision.reconciliation)
                if not contested and not assigned:
                    problems.append(
                        "Unused unique exact card match for "
                        + item.line_id
                        + ": "
                        + txn_id
                        + ". Link it with the tool delta; a missing receipt does not mean a "
                        "missing transaction. Use missing_receipt when appropriate and remove "
                        "the unsupported missing-transaction DATA-QUALITY finding."
                    )
            continue
        pair = by_pair.get((item.line_id, item.transaction_id))
        if pair is None:
            problems.append(
                "Selected transaction is not supported by original inputs: " + item.line_id
            )
        elif item.delta is not None and item.delta != Decimal(pair["amount_delta"]):
            problems.append(
                "Reconciliation delta disagrees with deterministic matching: " + item.line_id
            )
        elif item.status == "matched" and Decimal(pair["amount_delta"]) != 0:
            problems.append(
                "Nonzero transaction delta needs amount_mismatch and review: " + item.line_id
            )
    if policy.get("resources"):
        problems.extend(verify_policy(decision, report, events, policy["resources"]))
    return (None if problems else decision), problems
