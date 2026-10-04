"""Scripted model responses test orchestration; no live LLM accuracy claim."""

import asyncio
import copy
import json
import threading
from pathlib import Path

import pytest

from agent.loop import review
from app.assembler import validate_candidate
from app.intake import intake, redact
from evals.validate_fixtures import validate
from integrations.mcp_client import connect
from integrations.model_client import ModelResponse, ProviderError
from mock_systems.service import MockServer

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def backend(tmp_path):
    data = json.loads((ROOT / "mock_systems/seed/day4-data.json").read_text())
    servers = [
        MockServer(role, data, 0, tmp_path / "queue.sqlite3", fail_every=0, travel_delay=0)
        for role in ("card", "travel", "hr", "ledger")
    ]
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield {f"{s.role.upper()}_BASE_URL": f"http://127.0.0.1:{s.server_port}" for s in servers}
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


def load_report(number=1):
    return intake(json.loads((ROOT / f"evals/reports/EVAL-{number:02}.json").read_text()))[0]


class ScriptedModel:
    def __init__(self, report, reverse=False, wrong_total=False):
        self.report = report
        self.reverse = reverse
        self.wrong_total = wrong_total
        self.calls = {}
        self.round = 0

    def complete(self, messages, tools=None):
        assert len(tools) == 8
        assert "save_decision" not in {t["function"]["name"] for t in tools}
        self.round += 1
        outputs = [
            (self.calls[m["tool_call_id"]], json.loads(m["content"]))
            for m in messages
            if m["role"] == "tool"
        ]
        seen = {name for name, result in outputs if result["ok"]}
        report = self.report
        lines = report.model_dump(mode="json")["line_items"]
        requests = []
        if not outputs:
            requests = [
                ("get_employee", {"employee_id": report.employee_id}),
                ("get_trip", {"trip_id": report.trip_id}),
                ("list_settled_lines", {"employee_id": report.employee_id, "months": 12}),
                (
                    "list_card_transactions",
                    {"employee_id": report.employee_id, "from": "2026-04-07", "to": "2026-04-14"},
                ),
            ]
            if self.reverse:
                requests.reverse()
        else:
            pages = [r["data"] for n, r in outputs if n == "list_card_transactions" and r["ok"]]
            if pages[-1]["next_cursor"] is not None:
                requests = [
                    (
                        "list_card_transactions",
                        {
                            "employee_id": report.employee_id,
                            "from": "2026-04-07",
                            "to": "2026-04-14",
                            "cursor": pages[-1]["next_cursor"],
                        },
                    )
                ]
            elif "compute_totals" not in seen:
                requests = [
                    (
                        "match_transactions",
                        {
                            "lines": [
                                {
                                    k: v
                                    for k, v in line.items()
                                    if k
                                    in {
                                        "line_id",
                                        "date",
                                        "merchant",
                                        "amount",
                                        "currency",
                                        "category",
                                    }
                                }
                                for line in lines
                            ],
                            "transactions": [t for page in pages for t in page["items"]],
                        },
                    ),
                    (
                        "compute_totals",
                        {
                            "lines": [
                                {
                                    k: v
                                    for k, v in line.items()
                                    if k in {"line_id", "amount", "currency"}
                                }
                                for line in lines
                            ],
                            "caps": [],
                            "base_currency": "EUR",
                        },
                    ),
                ]
        if requests:
            calls = []
            for i, (name, args) in enumerate(requests):
                cid = f"call-{self.round}-{i}"
                self.calls[cid] = name
                calls.append(
                    {
                        "id": cid,
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)},
                    }
                )
            message = {"content": None, "tool_calls": calls}
        else:
            totals = next(r["data"] for n, r in outputs if n == "compute_totals" and r["ok"])
            pairs = next(
                r["data"]["pairs"] for n, r in outputs if n == "match_transactions" and r["ok"]
            )
            final = dict(
                report_id=report.report_id,
                decision="auto_approve",
                confidence=0.99,
                reimbursable_total={"amount": totals["reimbursable"], "currency": "EUR"},
                disallowed_total={"amount": totals["disallowed"], "currency": "EUR"},
                reconciliation=[
                    dict(
                        line_id=line.line_id,
                        status="matched",
                        transaction_id=next(
                            p["txn_id"] for p in pairs if p["line_id"] == line.line_id
                        ),
                        delta="0.00",
                    )
                    for line in report.line_items
                ],
                findings=[],
                duplicate_candidates=[],
                draft_query_to_submitter="",
            )
            if self.wrong_total:
                final["reimbursable_total"]["amount"] = "999.00"
                self.wrong_total = False
            message = {"content": json.dumps(final)}
        return ModelResponse(message, {"tokens_in": 10, "tokens_out": 5}, "scripted-test")


def run_review(env, report, model, **kwargs):
    async def run():
        async with connect(env) as session:
            return await review(report, session, model, "scripted-test-only", **kwargs)

    return asyncio.run(run())


@pytest.mark.parametrize("reverse", [False, True])
def test_clean_real_mcp_with_variable_order(backend, reverse):
    report = load_report()
    result = run_review(backend, report, ScriptedModel(report, reverse), queue=True)
    assert result["status"] == "complete", result["trace"]
    assert result["decision"]["reimbursable_total"]["amount"] == "20.00"
    assert result["queued"]
    assert result["trace"]["tools"][0]["name"] == (
        "list_card_transactions" if reverse else "get_employee"
    )


def test_multipage_and_wrong_total_recovery(backend):
    report = load_report(23)
    result = run_review(backend, report, ScriptedModel(report, wrong_total=True))
    assert result["status"] == "complete", result["trace"]
    assert result["decision"]["reimbursable_total"]["amount"] == "21.00"
    assert not result["queued"]
    events = result["trace"]["tools"]
    assert sum(e["name"] == "list_card_transactions" for e in events) == 2
    assert any(s.get("validation_feedback") for s in result["trace"]["steps"])
    final = result["decision"]
    policy = {"minimum_auto_approval_confidence": ".85", "auto_approval_ceiling": "2500"}
    page_one = [e for e in events if e["args"].get("cursor") != "20"]
    _, errors = validate_candidate(final, report, page_one, final["meta"], policy)
    assert any("Pending transaction page" in error for error in errors)
    altered = copy.deepcopy(final)
    altered["reconciliation"][0]["transaction_id"] = "INVENTED"
    _, errors = validate_candidate(altered, report, events, final["meta"], policy)
    assert any("Unseen transaction" in error for error in errors)


class RepeatingModel:
    def complete(self, messages, tools=None):
        return ModelResponse(
            {
                "tool_calls": [
                    {
                        "id": f"call-{len(messages)}",
                        "type": "function",
                        "function": {
                            "name": "get_employee",
                            "arguments": '{"employee_id":"EVAL-EMP-01"}',
                        },
                    }
                ]
            },
            {},
            "test-repeat",
        )


def test_budget_repeat_detection_and_no_fake_totals(backend):
    result = run_review(backend, load_report(), RepeatingModel(), max_steps=4, queue=True)
    assert result["status"] == "incomplete"
    assert result["decision"]["reimbursable_total"] is None
    assert result["decision"]["confidence"] == 0
    assert not result["queued"]
    assert result["trace"]["tools"][-1]["result"]["error"]["code"] == "REPEATED_TOOL_CALL"


def test_provider_failure_is_partial(backend):
    class FailingModel:
        def complete(self, messages, tools=None):
            raise ProviderError("API HTTP 403: check model access")

    result = run_review(backend, load_report(), FailingModel())
    assert result["trace"]["reason"] == "MODEL_API_ERROR"
    assert not result["queued"]


def test_redaction_preserves_dates_and_money():
    output = redact(
        {
            "text": "a@example.com +44 7700 900123 4111-1111-1111-1111",
            "date": "2026-04-09",
            "amount": "412.00",
        }
    )
    assert "example.com" not in output["text"] and "4111" not in output["text"]
    assert output["date"] == "2026-04-09" and output["amount"] == "412.00"


def test_fixture_coverage_and_receipts():
    assert validate() == {
        "reports": 25,
        "rule_count": 10,
        "injection_cases": 3,
        "multipage_cases": 2,
    }


def test_model_cannot_save_or_read_another_employee(backend):
    class UntrustedModel:
        def complete(self, messages, tools=None):
            calls = [
                {
                    "id": f"blocked-{i}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
                for i, (name, args) in enumerate(
                    [("save_decision", {}), ("get_employee", {"employee_id": "EMP-2231"})]
                )
            ]
            return ModelResponse({"tool_calls": calls}, {}, "scripted-untrusted")

    result = run_review(backend, load_report(), UntrustedModel(), max_steps=1)
    assert not result["queued"]
    assert [e["result"]["error"]["code"] for e in result["trace"]["tools"]] == [
        "TOOL_NOT_AVAILABLE",
        "OUTSIDE_REPORT_SCOPE",
    ]
