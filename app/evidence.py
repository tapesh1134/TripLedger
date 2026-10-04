"""Citations are identifiers grounded in input or successful tool responses."""

from typing import Any

from mcp_server.schemas import Decision, ExpenseReport

POLICY_URI = "tripledger://policy/expense-policy"


def event_refs(event: dict[str, Any]) -> list[dict[str, str]]:
    if not event.get("result", {}).get("ok"):
        return []
    name, data = event["name"], event["result"]["data"]
    refs: list[dict[str, str]] = []

    def add(source: str, ref: str) -> None:
        refs.append({"source": source, "ref": ref})

    if name == "get_employee":
        add("employee", data["employee_id"])
    elif name == "get_trip":
        add("trip", data["trip_id"])
    elif name == "list_card_transactions":
        for item in data["items"]:
            add("card_transaction", item["txn_id"])
    elif name == "list_settled_lines":
        for item in data["items"]:
            add("settled_line", item["report_id"] + ":line:" + item["line_id"])
    elif name == "read_receipt":
        add("read_receipt", event["args"]["file_path"])
        add("read_receipt", data["ref"])
    elif name == "compute_totals":
        add(name, data["calc_id"])
    elif name == "fx_convert":
        add(name, data["calc_id"])
    elif name == "match_transactions":
        for pair in data["pairs"]:
            add(name, "pair:" + pair["line_id"] + ":" + pair["txn_id"])
    return refs


def input_refs(report: ExpenseReport) -> list[dict[str, str]]:
    refs = [{"source": "report", "ref": report.report_id}]
    for line in report.line_items:
        refs += [
            {"source": "report", "ref": report.report_id + sep + line.line_id}
            for sep in (":line:", "/")
        ]
    for uri in (POLICY_URI, "tripledger://policy/per-diem", "tripledger://reference/mcc-codes"):
        refs.append({"source": "policy", "ref": uri})
    for fragment in [f"R-{i:02}" for i in range(1, 11)] + [
        "receipt_threshold",
        "auto_approval_ceiling",
        "minimum_auto_approval_confidence",
    ]:
        refs.append({"source": "policy", "ref": POLICY_URI + "#" + fragment})
    return refs


def validate_evidence(
    decision: Decision, report: ExpenseReport, events: list[dict[str, Any]]
) -> list[str]:
    refs = input_refs(report) + [r for event in events for r in event_refs(event)]
    allowed = {(r["source"], r["ref"]) for r in refs}
    aliases = {
        "get_employee": "employee",
        "get_trip": "trip",
        "list_card_transactions": "card_transaction",
        "receipt": "read_receipt",
        "list_settled_lines": "settled_line",
    }
    errors = []
    evidence_groups = [x.evidence for x in decision.findings] + [
        x.evidence for x in decision.duplicate_candidates
    ]
    for group in evidence_groups:
        for evidence in group:
            if (aliases.get(evidence.source, evidence.source), evidence.ref) not in allowed:
                errors.append(
                    "Unverified evidence citation: " + evidence.source + ":" + evidence.ref
                )
    lines = {line.line_id for line in report.line_items}
    for finding in decision.findings:
        if finding.line_id is not None and finding.line_id not in lines:
            errors.append("Finding refers to a missing report line.")
    settled = {
        (x["report_id"], x["line_id"])
        for e in events
        if e["name"] == "list_settled_lines" and e["result"].get("ok")
        for x in e["result"]["data"]["items"]
    }
    for duplicate in decision.duplicate_candidates:
        if (
            duplicate.line_id not in lines
            or (
                duplicate.matched_report_id == report.report_id
                and (
                    duplicate.matched_line_id not in lines
                    or duplicate.matched_line_id == duplicate.line_id
                )
            )
            or (
                duplicate.matched_report_id != report.report_id
                and (duplicate.matched_report_id, duplicate.matched_line_id) not in settled
            )
        ):
            errors.append("Duplicate candidate refers to unseen or identical lines.")
    return errors
