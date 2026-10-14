from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


def money(value):
    return format(value.quantize(CENT, rounding=ROUND_HALF_UP), ".2f")


def calculate(report, rules, receipts, duplicates, rate):
    """Only deterministic code decides numeric totals. Rates are report-date evidence."""
    findings = []
    lines = []
    total = Decimal("0")
    allowed_total = Decimal("0")
    seen_receipts = set()

    def finding(code, line, detail):
        findings.append({"code": code, "lineId": line, "detail": detail})

    for line in report["lines"]:
        amount = Decimal(str(line["amount"]))
        allowed = amount
        line_id = line["lineId"]
        currency = line["currency"]
        rid = line.get("receiptId")
        rule = next(
            (
                r
                for r in rules
                if r["category"].lower() == line["category"].lower()
                and r["currency"] == currency
            ),
            None,
        )
        if not rule:
            finding(
                "NO_CATEGORY_RULE",
                line_id,
                "No structured limit for this category/currency. Manager must inspect policy text.",
            )
        if not (report["startDate"] <= line["date"] <= report["endDate"]):
            finding(
                "OUTSIDE_TRIP",
                line_id,
                "Expense date is outside the submitted trip dates.",
            )
        if rid and rid in seen_receipts:
            finding(
                "REUSED_RECEIPT",
                line_id,
                "The same receipt is attached to multiple lines; verify allocation.",
            )
        if rid:
            seen_receipts.add(rid)
        if rid and any(
            d.get("sha256") == receipts.get(rid, {}).get("sha256") for d in duplicates
        ):
            finding(
                "POTENTIAL_DUPLICATE",
                line_id,
                "Receipt hash appears in another submitted or approved report.",
            )
        if not rid and (not rule or rule.get("receiptRequired")):
            finding("MISSING_RECEIPT", line_id, "Required receipt was not attached.")
        extracted = receipts.get(rid, {}) if rid else {}
        if rid and not extracted.get("verified"):
            finding(
                "RECEIPT_UNVERIFIED",
                line_id,
                "Receipt could not be extracted with sufficient confidence; inspect the image.",
            )
        if extracted.get("verified"):
            if extracted.get("currency") != currency or abs(
                Decimal(str(extracted["amount"])) - amount
            ) > Decimal("0.01"):
                finding(
                    "RECEIPT_MISMATCH",
                    line_id,
                    "Receipt amount/currency differs from the claimed line.",
                )
            if extracted.get("date") and extracted["date"] != line["date"]:
                finding(
                    "RECEIPT_DATE_MISMATCH",
                    line_id,
                    "Receipt date differs from the claimed date.",
                )
        if rule:
            multiplier = 1
            if rule["basis"] == "PER_NIGHT":
                multiplier = line.get("hotelNights")
            elif rule["basis"] == "PER_ATTENDEE":
                multiplier = line.get("attendeeCount")
            if multiplier is None:
                finding(
                    "MISSING_POLICY_FACT",
                    line_id,
                    "Hotel nights or attendee count is needed to calculate the cap.",
                )
            else:
                cap = Decimal(str(rule["limit"])) * Decimal(multiplier)
                if amount > cap:
                    allowed = cap
                    finding(
                        "CAP_EXCEEDED",
                        line_id,
                        f"Claim {currency} {money(amount)} exceeds limit {money(cap)}.",
                    )
        fx = Decimal(str(rate(line["date"], currency, report["baseCurrency"])))
        converted = (amount * fx).quantize(CENT, rounding=ROUND_HALF_UP)
        permitted = (allowed * fx).quantize(CENT, rounding=ROUND_HALF_UP)
        total += converted
        allowed_total += permitted
        lines.append(
            {
                "lineId": line_id,
                "claimed": money(converted),
                "reimbursable": money(permitted),
                "disallowed": money(converted - permitted),
                "fxRate": str(fx),
                "sourceCurrency": currency,
            }
        )
    finding(
        "EXTERNAL_RECONCILIATION_UNAVAILABLE",
        None,
        "Corporate card transactions and authoritative travel bookings are not connected. Verify them manually.",
    )
    return {
        "currency": report["baseCurrency"],
        "claimedTotal": money(total),
        "reimbursableTotal": money(allowed_total),
        "disallowedTotal": money(total - allowed_total),
        "findings": findings,
        "lines": lines,
        "recommendation": "MANAGER_REVIEW",
    }
