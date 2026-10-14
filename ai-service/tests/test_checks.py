from decimal import Decimal
from app.checks import calculate


def report(amount="360", currency="EUR"):
    return {
        "baseCurrency": "EUR",
        "startDate": "2026-10-01",
        "endDate": "2026-10-04",
        "lines": [
            {
                "lineId": "L1",
                "date": "2026-10-02",
                "category": "hotel",
                "amount": amount,
                "currency": currency,
                "hotelNights": 3,
            }
        ],
    }


def test_cap_and_exact_totals():
    result = calculate(
        report(),
        [
            {
                "category": "hotel",
                "currency": "EUR",
                "limit": "100",
                "basis": "PER_NIGHT",
                "receiptRequired": True,
            }
        ],
        {},
        [],
        lambda *args: Decimal(1),
    )
    assert result["reimbursableTotal"] == "300.00"
    assert result["disallowedTotal"] == "60.00"
    assert {"CAP_EXCEEDED", "MISSING_RECEIPT"} <= {
        f["code"] for f in result["findings"]
    }


def test_missing_facts_do_not_invent_cap():
    r = report()
    r["lines"][0].pop("hotelNights")
    result = calculate(
        r,
        [
            {
                "category": "hotel",
                "currency": "EUR",
                "limit": "100",
                "basis": "PER_NIGHT",
                "receiptRequired": False,
            }
        ],
        {},
        [],
        lambda *args: 1,
    )
    assert "MISSING_POLICY_FACT" in {f["code"] for f in result["findings"]}


def test_fx_rounding_is_deterministic():
    result = calculate(
        report("10.005", "USD"), [], {}, [], lambda *args: Decimal("0.9")
    )
    assert result["claimedTotal"] == "9.00"
    assert result["recommendation"] == "MANAGER_REVIEW"


def test_untrusted_receipt_cannot_change_amount():
    r = report()
    r["lines"][0]["receiptId"] = "receipt1"
    result = calculate(
        r,
        [],
        {
            "receipt1": {
                "verified": True,
                "amount": "0",
                "currency": "EUR",
                "date": "2026-10-02",
            }
        },
        [],
        lambda *args: 1,
    )
    assert result["claimedTotal"] == "360.00"
    assert "RECEIPT_MISMATCH" in {f["code"] for f in result["findings"]}
