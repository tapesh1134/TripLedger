"""Day 4 minimal acceptance checks. Full rule-by-rule verification is Day 5."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

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
            for e in successful
        ):
            problems.append("Receipt unavailable: " + line.line_id)
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
    return (None if problems else decision), problems
