from decimal import Decimal

import pytest

from mcp_server.tools_compute import compute_totals


def line(amount, line_id="L1", currency="EUR"):
    return {"line_id": line_id, "amount": amount, "currency": currency}


def cap(limit="100", line_id="L1", quantity=1):
    return {
        "line_id": line_id,
        "rule_id": "R-03",
        "kind": "cap_excess",
        "limit": limit,
        "quantity": quantity,
    }


def test_decimal_sum():
    result = compute_totals([line("0.10"), line("0.20", "L2")], [], "EUR")
    assert result["reimbursable"] == "0.30"
    assert result["disallowed"] == "0.00"


def test_hotel_disallows_only_excess():
    result = compute_totals([line("412.00")], [cap("120.00", quantity=3)], "EUR")
    assert result["reimbursable"] == "360.00"
    assert result["disallowed"] == "52.00"
    assert result["per_line"][0]["evaluations"][0]["effective_limit"] == "360.00"


def test_prohibited_disallows_entire_line():
    result = compute_totals(
        [line("75.50")], [{"line_id": "L1", "rule_id": "R-07", "kind": "whole_line"}], "EUR"
    )
    assert result["reimbursable"] == "0.00"
    assert result["disallowed"] == "75.50"


def test_overlapping_rules_do_not_double_count():
    result = compute_totals(
        [line("150")],
        [cap("100"), cap("80"), {"line_id": "L1", "rule_id": "R-07", "kind": "whole_line"}],
        "EUR",
    )
    assert result["reimbursable"] == "0.00"
    assert result["disallowed"] == "150.00"


def test_multiple_caps_use_strictest_allowance():
    result = compute_totals([line("150")], [cap("100"), cap("80")], "EUR")
    assert result["reimbursable"] == "80.00"
    assert result["disallowed"] == "70.00"


@pytest.mark.parametrize("amount", ["99.99", "100.00"])
def test_at_or_below_cap(amount):
    result = compute_totals([line(amount)], [cap()], "EUR")
    assert result["reimbursable"] == amount
    assert result["disallowed"] == "0.00"


def test_round_half_up_each_line_before_summing():
    result = compute_totals([line("1.005"), line("2.005", "L2")], [], "EUR")
    assert result["reimbursable"] == "3.02"


def test_conservation_of_money_across_lines():
    result = compute_totals(
        [line("412"), line("38.40", "L2"), line("96", "L3")], [cap("120", quantity=3)], "EUR"
    )
    assert Decimal(result["reimbursable"]) + Decimal(result["disallowed"]) == Decimal("546.40")
    assert sum(Decimal(x["reimbursable"]) for x in result["per_line"]) == Decimal("494.40")


@pytest.mark.parametrize("amount", ["-1", "NaN", "Infinity", "not-money", "1e100"])
def test_reject_invalid_amount(amount):
    with pytest.raises(ValueError):
        compute_totals([line(amount)], [], "EUR")


def test_reject_mixed_currency():
    with pytest.raises(ValueError, match="base_currency"):
        compute_totals([line("10", currency="USD")], [], "EUR")


def test_reject_duplicate_line_ids():
    with pytest.raises(ValueError, match="duplicate"):
        compute_totals([line("10"), line("20")], [], "EUR")


def test_reject_unknown_cap_target():
    with pytest.raises(ValueError, match="unknown"):
        compute_totals([line("10")], [cap(line_id="missing")], "EUR")


@pytest.mark.parametrize(
    "bad_cap",
    [
        {"line_id": "L1", "rule_id": "R-03", "kind": "cap_excess"},
        {"line_id": "L1", "rule_id": "R-07", "kind": "whole_line", "limit": "10"},
        {"line_id": "L1", "rule_id": "R-03", "kind": "cap_excess", "limit": "-1"},
        {"line_id": "L1", "rule_id": "R-03", "kind": "cap_excess", "limit": "10", "quantity": 0},
    ],
)
def test_reject_invalid_cap(bad_cap):
    with pytest.raises(ValueError):
        compute_totals([line("20")], [bad_cap], "EUR")


def test_zero_amount_and_zero_cap():
    result = compute_totals([line("0"), line("12", "L2")], [cap("0", "L2")], "EUR")
    assert result["reimbursable"] == "0.00"
    assert result["disallowed"] == "12.00"
