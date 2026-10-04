"""Independent checks for the supplied teaching policy, using Decimal tools.

No inference from free-form descriptions: uncertain facts require manual review.
"""

import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from mcp_server.matching import normalize_merchant
from mcp_server.schemas import Decision, ExpenseReport
from mcp_server.tools_compute import compute_totals, money


def verify_policy(
    decision: Decision,
    report: ExpenseReport,
    events: list[dict[str, Any]],
    resources: dict[str, str],
) -> list[str]:
    allowances = json.loads(resources["tripledger://policy/per-diem"])
    codes = json.loads(resources["tripledger://reference/mcc-codes"])["codes"]
    controls = allowances["controls"]
    good = [e for e in events if e["result"].get("ok")]
    errors: list[str] = []
    required: list[tuple[str, str | None, str, str]] = []

    def require(rule: str, line: str | None, severity: str, reason: str) -> None:
        required.append((rule, line, severity, reason))

    def latest(name: str) -> dict[str, Any]:
        found = [e for e in good if e["name"] == name]
        return found[-1]["result"]["data"] if found else {}

    employee, trip = latest("get_employee"), latest("get_trip")
    computed = [e for e in good if e["name"] == "compute_totals"]
    if not employee or not trip or not computed:
        return []  # Assembler already rejects incomplete essential evidence.
    if report.base_currency != allowances["currency"]:
        return ["Policy currency differs from report base currency; no decision can be verified."]
    if trip.get("employee_id") != report.employee_id:
        errors.append("Trip belongs to another employee.")
    last = computed[-1]
    calc_lines = {x["line_id"]: x for x in last["args"]["lines"]}
    if set(calc_lines) != {line.line_id for line in report.line_items}:
        return []  # Existing coverage check reports the defect.
    amounts = {lid: Decimal(str(value["amount"])) for lid, value in calc_lines.items()}
    band = allowances["cities"].get(trip["city"], {}).get(employee["grade"])
    transactions = {
        t["txn_id"]: t
        for e in good
        if e["name"] == "list_card_transactions"
        for t in e["result"]["data"]["items"]
    }
    receipts = {
        e["args"]["file_path"]: e["result"]["data"] for e in good if e["name"] == "read_receipt"
    }
    reconciliation = {x.line_id: x for x in decision.reconciliation}
    caps: list[dict[str, Any]] = []
    expected_excess: dict[tuple[str, str], Decimal] = {}
    hotels = [x for x in report.line_items if x.category == "hotel"]
    meals: dict[str, list[Any]] = defaultdict(list)
    seen: dict[tuple[str, str, Decimal, str], str] = {}
    settled = latest("list_settled_lines").get("items", [])
    known_duplicates: set[tuple[str, str, str]] = set()
    declared_nights = [x.hotel_nights for x in hotels if x.hotel_nights is not None]
    invalid_nights = bool(declared_nights and sum(declared_nights) > trip["hotel_nights"])
    for line in report.line_items:
        lid = line.line_id
        item = reconciliation.get(lid)
        if item is None:
            continue
        start = date.fromisoformat(trip["start_date"])
        end = date.fromisoformat(trip["end_date"])
        grace = timedelta(days=controls["travel_grace_days"])
        if not start - grace <= line.date <= end + grace:
            require("R-01", lid, "query", "Expense is outside booked dates plus travel grace.")
        receipt = receipts.get(line.receipt_file or "")
        needs_receipt = amounts[lid] >= Decimal(controls["receipt_threshold"])
        receipt_problem = None
        if needs_receipt and not receipt:
            receipt_problem = "Required receipt is missing or extraction failed."
        elif line.receipt_file and not receipt:
            receipt_problem = "Attached receipt could not be verified."
        elif receipt:
            if Decimal(str(receipt["confidence"])) < Decimal(controls["receipt_min_confidence"]):
                receipt_problem = "Receipt extraction confidence is below the review threshold."
            elif (
                Decimal(receipt["total"]) != line.amount
                or receipt["currency"] != line.currency
                or receipt["date"] != line.date.isoformat()
                or normalize_merchant(receipt["merchant"]) != normalize_merchant(line.merchant)
            ):
                receipt_problem = "Receipt fields differ from the claim; reconcile manually."
        if receipt_problem:
            require("R-02", lid, "query", receipt_problem)
            if item.status not in {
                "missing_receipt",
                "amount_mismatch",
                "duplicate",
                "missing_transaction",
            }:
                errors.append(
                    "Receipt problem requires an unresolved reconciliation status: " + lid
                )
        txn = transactions.get(item.transaction_id or "")
        if not txn:
            require("DATA-QUALITY", lid, "query", "No verified card transaction supports the line.")
        else:
            category = codes.get(txn.get("mcc", ""))
            if category is None:
                require("R-07", lid, "query", "Unknown merchant category requires manual review.")
            elif category["prohibited"]:
                require(
                    "R-07", lid, "blocking", "Prohibited merchant category; disallow whole line."
                )
                caps.append(dict(line_id=lid, rule_id="R-07", kind="whole_line"))
                expected_excess[("R-07", lid)] = money(amounts[lid])
            # A model may not select a genuine transaction for a different employee.
            if txn.get("employee_id") != report.employee_id:
                errors.append("Transaction belongs to another employee: " + lid)
        if line.category == "hotel":
            nights = (
                line.hotel_nights
                if line.hotel_nights is not None
                else (trip["hotel_nights"] if len(hotels) == 1 else None)
            )
            if invalid_nights or (nights is not None and nights > trip["hotel_nights"]):
                nights = None
            if not band or not nights:
                require("R-03", lid, "query", "Hotel allowance or per-line nights are unknown.")
            else:
                cap = dict(
                    line_id=lid,
                    rule_id="R-03",
                    kind="cap_excess",
                    limit=band["hotel_nightly"],
                    quantity=nights,
                )
                caps.append(cap)
                evaluation = compute_totals([calc_lines[lid]], [cap], report.base_currency)
                expected_excess[("R-03", lid)] = Decimal(evaluation["disallowed"])
                if Decimal(evaluation["disallowed"]) > 0:
                    require("R-03", lid, "blocking", "Hotel exceeds the resource-backed allowance.")
        if line.category == "flight":
            flights = trip.get("flights", [])
            if not flights:
                require("R-05", lid, "query", "Flight entitlement evidence is missing.")
            for flight in flights:
                if (
                    flight["cabin"].lower() != "economy"
                    and employee["grade"] not in controls["premium_grades"]
                    and Decimal(str(flight["duration_hours"])) <= Decimal(controls["premium_hours"])
                ):
                    require(
                        "R-05", lid, "blocking", "Premium cabin entitlement is not established."
                    )
        if line.category == "meals":
            meals[line.date.isoformat()].append(line)
            if line.is_client_dinner is None or line.attendee_count is None or not band:
                require("R-04", lid, "query", "Meal type, attendee count or allowance is unknown.")
            else:
                limit = (
                    band["client_dinner_per_head"]
                    if line.is_client_dinner
                    else band["meals_daily_per_head"]
                )
                quantity = line.attendee_count if line.is_client_dinner else 1
                result = compute_totals(
                    [calc_lines[lid]],
                    [
                        dict(
                            line_id=lid,
                            rule_id="R-04",
                            kind="cap_excess",
                            limit=limit,
                            quantity=quantity,
                        )
                    ],
                    report.base_currency,
                )
                expected_excess[("R-04", lid)] = Decimal(result["disallowed"])
                if Decimal(result["disallowed"]) > 0:
                    require("R-04", lid, "query", "Meal exceeds the applicable per-head allowance.")
            if line.alcohol_amount is None or line.is_client_dinner is None:
                require("R-06", lid, "query", "Alcohol amount or dinner type is unknown.")
            elif line.alcohol_amount > line.amount:
                errors.append("Alcohol amount exceeds the line total: " + lid)
            elif line.alcohol_amount > 0 and (
                not line.is_client_dinner
                or line.alcohol_amount * Decimal("100")
                > line.amount * Decimal(controls["alcohol_percent"])
            ):
                require(
                    "R-06", lid, "query", "Alcohol exceeds the client-dinner policy entitlement."
                )
        fingerprint = (
            normalize_merchant(line.merchant),
            line.date.isoformat(),
            line.amount,
            line.currency,
        )
        matches = []
        if fingerprint in seen:
            matches.append((report.report_id, seen[fingerprint]))
        seen[fingerprint] = lid
        for old in settled:
            if fingerprint == (
                normalize_merchant(old["merchant"]),
                old["date"],
                Decimal(old["amount"]),
                old["currency"],
            ):
                matches.append((old["report_id"], old["line_id"]))
        for rid, old_lid in matches:
            require(
                "R-08", lid, "blocking", "Same merchant, date, currency and amount already claimed."
            )
            known_duplicates.add((lid, rid, old_lid))
    for day_lines in meals.values():
        if len(day_lines) > 1 and band:
            if any(line.is_client_dinner is not False for line in day_lines):
                for line in day_lines:
                    require(
                        "R-04",
                        line.line_id,
                        "query",
                        "Multiple meals with client attendance need daily allocation review.",
                    )
            else:
                total = compute_totals(
                    [calc_lines[x.line_id] for x in day_lines], [], report.base_currency
                )
                if Decimal(total["reimbursable"]) > Decimal(band["meals_daily_per_head"]):
                    for line in day_lines:
                        require(
                            "R-04",
                            line.line_id,
                            "query",
                            "Combined meals exceed the daily allowance.",
                        )
    if (report.submitted_at.date() - date.fromisoformat(trip["end_date"])).days > controls[
        "submission_days"
    ]:
        require("R-09", None, "query", "Submission exceeds the allowed age.")
    expected = compute_totals(list(calc_lines.values()), caps, report.base_currency)
    if Decimal(expected["reimbursable"]) > Decimal(controls["auto_approval_ceiling"]):
        require("R-10", None, "advisory", "Total exceeds auto-approval ceiling.")
    if money(decision.reimbursable_total.amount) != Decimal(expected["reimbursable"]) or money(
        decision.disallowed_total.amount
    ) != Decimal(expected["disallowed"]):
        errors.append(
            "Policy-derived totals disagree. Re-run compute_totals with verified_caps="
            + json.dumps(caps)
        )
    # Reject invented caps even when their effect happens to be zero.
    allowed_caps = {json.dumps(cap, sort_keys=True) for cap in caps}
    for cap in last["args"].get("caps", []):
        clean = {k: v for k, v in cap.items() if v is not None}
        if clean.get("kind") == "whole_line":
            clean.pop("quantity", None)
        elif "quantity" not in clean:
            clean["quantity"] = 1
        if "limit" in clean:
            clean["limit"] = str(Decimal(str(clean["limit"])).quantize(Decimal(".01")))
        if json.dumps(clean, sort_keys=True) not in allowed_caps:
            errors.append("Unverified cap. Use policy-derived caps: " + json.dumps(caps))
    actual_duplicates = {
        (x.line_id, x.matched_report_id, x.matched_line_id) for x in decision.duplicate_candidates
    }
    if actual_duplicates != known_duplicates:
        errors.append(
            "Duplicate candidates must match the verified set: "
            + json.dumps(sorted(known_duplicates))
        )
    for rule, required_lid, severity, reason in required:
        if not any(
            f.rule_id == rule and f.line_id == required_lid and f.severity == severity
            for f in decision.findings
        ):
            errors.append(
                f"Required finding {rule} line={required_lid} severity={severity}: {reason}"
            )
    required_keys = {(rule, lid) for rule, lid, _, _ in required}
    for finding in decision.findings:
        if (finding.rule_id.startswith("R-") or finding.rule_id == "DATA-QUALITY") and (
            finding.rule_id,
            finding.line_id,
        ) not in required_keys:
            errors.append(
                "Unsupported policy finding: " + finding.rule_id + ":" + str(finding.line_id)
            )
        if finding.excess is not None and (
            finding.line_id is None
            or expected_excess.get((finding.rule_id, finding.line_id)) != finding.excess
        ):
            errors.append("Finding excess lacks a verified rule calculation: " + finding.rule_id)
    if decision.decision == "audit_hold":
        errors.append("This teaching policy does not define audit_hold; use manager_review.")
    if decision.decision == "auto_approve" and (
        required or decision.reimbursable_total.amount >= Decimal(controls["auto_approval_ceiling"])
    ):
        errors.append("Independent policy check requires manager_review.")
    if (
        any(severity == "query" for _, _, severity, _ in required)
        and not decision.draft_query_to_submitter.strip()
    ):
        errors.append("Provide a neutral draft request for the unresolved information.")
    return list(dict.fromkeys(errors))
