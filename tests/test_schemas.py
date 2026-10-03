import json
from pathlib import Path

import pytest

from mcp_server.schemas import Decision, ExpenseReport

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_valid_report():
    report = ExpenseReport.model_validate_json((EXAMPLES / "report.json").read_text())
    assert len(report.line_items) == 3


def test_valid_decision():
    decision = Decision.model_validate_json((EXAMPLES / "decision.json").read_text())
    assert decision.decision == "manager_review"


def test_invalid_report_duplicate_ids():
    report = json.loads((EXAMPLES / "report.json").read_text())
    report["line_items"][1]["line_id"] = "L1"
    with pytest.raises(ValueError, match="unique"):
        ExpenseReport.model_validate(report)


def test_reject_unknown_fields():
    report = json.loads((EXAMPLES / "report.json").read_text())
    report["unknown"] = True
    with pytest.raises(ValueError):
        ExpenseReport.model_validate(report)


@pytest.mark.parametrize("field,value", [("decision", "approved"), ("confidence", 1.1)])
def test_invalid_decision(field, value):
    decision = json.loads((EXAMPLES / "decision.json").read_text())
    decision[field] = value
    with pytest.raises(ValueError):
        Decision.model_validate(decision)


def test_findings_require_evidence():
    decision = json.loads((EXAMPLES / "decision.json").read_text())
    decision["findings"][0]["evidence"] = []
    with pytest.raises(ValueError):
        Decision.model_validate(decision)
