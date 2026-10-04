"""Check fixture structure/coverage; this does NOT score LLM accuracy."""

import json
from pathlib import Path

from mcp_server.schemas import ExpenseReport
from mcp_server.tool_contracts import Receipt

ROOT = Path(__file__).resolve().parents[1]


def validate():
    labels = json.loads((ROOT / "evals/labels.json").read_text())
    data = json.loads((ROOT / "mock_systems/seed/day4-data.json").read_text())
    assert len(labels) == 25
    assert {r for case in labels for r in case["expected_rules"]} == {
        f"R-{n:02}" for n in range(1, 11)
    }
    for case in labels:
        report = ExpenseReport.model_validate_json((ROOT / case["report"]).read_bytes())
        assert any(e["employee_id"] == report.employee_id for e in data["employees"])
        assert any(t["trip_id"] == report.trip_id for t in data["trips"])
        count = sum(t["employee_id"] == report.employee_id for t in data["transactions"])
        if case["multipage"]:
            assert count > 20
        for line in report.line_items:
            if line.receipt_file:
                Receipt.model_validate_json((ROOT / line.receipt_file).read_bytes())
    result = dict(
        reports=25,
        rule_count=10,
        injection_cases=sum(c["injection"] for c in labels),
        multipage_cases=sum(c["multipage"] for c in labels),
    )
    assert result["injection_cases"] == 3 and result["multipage_cases"] == 2
    return result


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2))
