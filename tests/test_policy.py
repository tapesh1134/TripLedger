"""provenance, independent policy and receipt extraction regressions."""

import json
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from test_agent import ScriptedModel, backend, load_report, run_review  # noqa: F401

from app.assembler import validate_candidate
from app.evidence import validate_evidence
from app.policy_guard import verify_policy
from integrations.model_client import ModelResponse
from integrations.receipt_vision import extract_receipt
from mcp_server.dispatch import execute
from mcp_server.schemas import Decision, Evidence

ROOT = Path(__file__).resolve().parents[1]


def resources():
    return {
        f"tripledger://{kind}/{name}": (ROOT / f"mcp_server/resources/{file}").read_text()
        for kind, name, file in [
            ("policy", "expense-policy", "expense-policy.md"),
            ("policy", "per-diem", "per-diem.json"),
            ("reference", "mcc-codes", "mcc-codes.json"),
        ]
    }


def golden(number):
    report = load_report(number)
    seed = json.loads((ROOT / "mock_systems/seed/evaluation-data.json").read_text())
    events = []

    def event(name, args, data):
        events.append(dict(name=name, args=args, result=dict(ok=True, data=data)))

    employee = next(x for x in seed["employees"] if x["employee_id"] == report.employee_id)
    trip = next(x for x in seed["trips"] if x["trip_id"] == report.trip_id)
    txns = [x for x in seed["transactions"] if x["employee_id"] == report.employee_id]
    old = [x for x in seed["settled_lines"] if x["employee_id"] == report.employee_id]
    event("get_employee", {"employee_id": report.employee_id}, employee)
    event("get_trip", {"trip_id": report.trip_id}, trip)
    event("list_settled_lines", {"employee_id": report.employee_id, "months": 12}, {"items": old})
    for start in range(0, max(1, len(txns)), 20):
        args = {"employee_id": report.employee_id, "from": "2026-04-04", "to": "2026-04-14"}
        if start:
            args["cursor"] = str(start)
        event(
            "list_card_transactions",
            args,
            {
                "items": txns[start : start + 20],
                "next_cursor": str(start + 20) if start + 20 < len(txns) else None,
            },
        )
    lines = report.model_dump(mode="json")["line_items"]
    for line in lines:
        if line["receipt_file"]:
            args = {"file_path": line["receipt_file"]}
            events.append(
                dict(name="read_receipt", args=args, result=execute("read_receipt", args))
            )
    args = {
        "lines": [
            {
                k: v
                for k, v in line.items()
                if k in {"line_id", "date", "merchant", "amount", "currency", "category"}
            }
            for line in lines
        ],
        "transactions": txns,
    }
    events.append(
        dict(name="match_transactions", args=args, result=execute("match_transactions", args))
    )
    caps = []
    if number in (2, 5, 17, 19, 22):
        caps = [dict(line_id="L1", rule_id="R-03", kind="cap_excess", limit="120.00", quantity=3)]
    if number in (9, 21):
        caps = [dict(line_id="L1", rule_id="R-07", kind="whole_line")]
    args = {
        "lines": [
            {k: v for k, v in line.items() if k in {"line_id", "amount", "currency"}}
            for line in lines
        ],
        "caps": caps,
        "base_currency": "EUR",
    }
    result = execute("compute_totals", args)
    events.append(dict(name="compute_totals", args=args, result=result))
    totals = result["data"]
    cases = {
        3: [("R-01", "L1", "query")],
        4: [("R-02", "L1", "query")],
        5: [("R-03", "L1", "blocking")],
        6: [("R-04", "L1", "query")],
        7: [("R-05", "L1", "blocking")],
        8: [("R-06", "L1", "query")],
        9: [("R-07", "L1", "blocking")],
        10: [("R-08", "L2", "blocking")],
        11: [("R-08", "L1", "blocking")],
        12: [("R-09", None, "query")],
        13: [("R-10", None, "advisory")],
        18: [("R-02", "L1", "query")],
        19: [("R-03", "L1", "blocking")],
        20: [("R-02", "L1", "query")],
        21: [("R-07", "L1", "blocking")],
        22: [("R-03", "L1", "blocking"), ("R-02", "L1", "query")],
        24: [("R-02", "L21", "query")],
        25: [("DATA-QUALITY", "L1", "query")],
    }
    findings = [
        dict(
            rule_id=rule,
            line_id=lid,
            severity=severity,
            observed="Synthetic expected fact",
            permitted="See policy",
            excess=None,
            evidence=[dict(source="report", ref=report.report_id)],
        )
        for rule, lid, severity in cases.get(number, [])
    ]
    reconciliation = [
        dict(
            line_id=line.line_id,
            status="matched",
            transaction_id=txns[i]["txn_id"] if txns else None,
            delta="0.00" if txns else None,
        )
        for i, line in enumerate(report.line_items)
    ]
    if number in (4, 18, 20, 22):
        reconciliation[0]["status"] = "missing_receipt"
    if number == 24:
        reconciliation[-1]["status"] = "missing_receipt"
    if number == 25:
        reconciliation[0]["status"] = "missing_transaction"
    duplicate = []
    if number in (10, 11):
        duplicate = [
            dict(
                line_id="L2" if number == 10 else "L1",
                matched_line_id="L1" if number == 10 else "OLD-L1",
                matched_report_id=report.report_id if number == 10 else "OLD-EVAL-11",
                evidence=[dict(source="report", ref=report.report_id)],
            )
        ]
    meta = dict(
        model="scripted-test",
        policy_version="2026-Q2-demo-3",
        prompt_hash="test",
        tokens_in=0,
        tokens_out=0,
        steps=1,
        latency_ms=0,
        created_at="2026-10-04T00:00:00Z",
    )
    decision = Decision.model_validate(
        dict(
            report_id=report.report_id,
            decision="manager_review" if findings else "auto_approve",
            confidence=0.95,
            reimbursable_total=dict(amount=totals["reimbursable"], currency="EUR"),
            disallowed_total=dict(amount=totals["disallowed"], currency="EUR"),
            reconciliation=reconciliation,
            findings=findings,
            duplicate_candidates=duplicate,
            draft_query_to_submitter="Please provide the missing evidence." if findings else "",
            meta=meta,
        )
    )
    return decision, report, events


@pytest.mark.parametrize("number", range(1, 26))
def test_independent_policy_accepts_expected_fixture_outcomes(number):
    decision, report, events = golden(number)
    _, errors = validate_candidate(
        decision.model_dump(mode="json"),
        report,
        events,
        decision.meta.model_dump(mode="json"),
        dict(
            minimum_auto_approval_confidence=".85",
            auto_approval_ceiling="2500",
            resources=resources(),
        ),
    )
    assert not errors, errors


@pytest.mark.parametrize(
    "number", [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 18, 19, 20, 21, 22, 24, 25]
)
def test_omitted_policy_findings_cannot_auto_approve(number):
    decision, report, events = golden(number)
    decision.decision = "auto_approve"
    decision.findings = []
    errors = verify_policy(decision, report, events, resources())
    assert any("requires manager_review" in e for e in errors)


def test_blocked_receipt_citation_is_rejected():
    decision, report, events = golden(24)
    decision.findings[0].evidence.append(
        Evidence(source="read_receipt", ref="receipts/EVAL-24/L21.jpg:OUTSIDE_REPORT_SCOPE")
    )
    decision = Decision.model_validate(decision.model_dump(mode="json"))
    events.append(
        dict(
            name="read_receipt",
            args={"file_path": "receipts/EVAL-24/L21.jpg"},
            result={"ok": False, "error": {"code": "OUTSIDE_REPORT_SCOPE"}},
        )
    )
    assert any("Unverified evidence" in e for e in validate_evidence(decision, report, events))


def test_tampered_cap_and_excess_rejected():
    decision, report, events = golden(5)
    decision.findings[0].excess = Decimal("999")
    decision = Decision.model_validate(decision.model_dump(mode="json"))
    events[-1]["args"]["caps"][0]["limit"] = "999.00"
    errors = verify_policy(decision, report, events, resources())
    assert any("Unverified cap" in e for e in errors)
    assert any("Finding excess" in e for e in errors)


def test_failed_attached_receipt_allows_honest_manager_review():
    decision, report, events = golden(22)
    receipt = next(e for e in events if e["name"] == "read_receipt")
    receipt["result"] = {"ok": False, "error": {"code": "VISION_API_ERROR"}}
    _, errors = validate_candidate(
        decision.model_dump(mode="json"),
        report,
        events,
        decision.meta.model_dump(mode="json"),
        dict(
            minimum_auto_approval_confidence=".85",
            auto_approval_ceiling="2500",
            resources=resources(),
        ),
    )
    assert not errors, errors


class ReceiptCorrectionModel(ScriptedModel):
    invalid_citation = True

    def complete(self, messages, tools=None):
        response = super().complete(messages, tools)
        if response.message.get("content"):
            decision = json.loads(response.message["content"])
            decision["decision"] = "manager_review"
            decision["reconciliation"][-1]["status"] = "missing_receipt"
            decision["draft_query_to_submitter"] = "Please provide the receipt for L21."
            evidence = [dict(source="report", ref="EVAL-24:line:L21")]
            if self.invalid_citation:
                evidence.append(
                    dict(source="read_receipt", ref="receipts/EVAL-24/L21.jpg:OUTSIDE_REPORT_SCOPE")
                )
                self.invalid_citation = False
            decision["findings"] = [
                dict(
                    rule_id="R-02",
                    severity="query",
                    line_id="L21",
                    observed="Missing receipt for EUR 25.",
                    permitted="Receipt required at EUR 25.",
                    excess=None,
                    evidence=evidence,
                )
            ]
            response.message["content"] = json.dumps(decision)
        return response


def test_real_mcp_feedback_corrects_the_users_receipt_citation(backend):  # noqa: F811
    report = load_report(24)
    result = run_review(backend, report, ReceiptCorrectionModel(report))
    assert result["status"] == "complete", result["trace"]
    assert result["decision"]["reimbursable_total"]["amount"] == "45.00"
    assert any(
        "Unverified evidence" in str(s.get("validation_feedback")) for s in result["trace"]["steps"]
    )


def configure_vision(monkeypatch):
    monkeypatch.setenv("RECEIPT_VISION_ENABLED", "true")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LLM_ENDPOINT_URL", "")
    monkeypatch.setenv("LLM_API_KEY", "synthetic-key")
    monkeypatch.setenv("LLM_MODEL", "synthetic-vision")


def test_vision_request_and_structured_response(monkeypatch):
    configure_vision(monkeypatch)
    from integrations.receipt_vision import ModelClient

    seen = []

    def respond(self, body):
        seen.append(body)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            dict(
                                merchant="Cab company 1",
                                date="2026-04-09",
                                currency="EUR",
                                total="20.00",
                                tax="0.00",
                                confidence=0.98,
                            )
                        )
                    }
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 30},
        }

    monkeypatch.setattr(ModelClient, "_post", respond)
    result = extract_receipt(ROOT / "receipts/samples/sample-taxi.png")
    assert result["ok"] and result["data"]["total"] == "20.00"
    assert seen[0]["messages"][1]["content"][1]["image_url"]["url"].startswith(
        "data:image/jpeg;base64,"
    )
    assert "base64" not in json.dumps(result)


@pytest.mark.parametrize(
    "content,code",
    [("garbage", "RECEIPT_EXTRACTION_INVALID"), ('{"unreadable":true}', "RECEIPT_UNREADABLE")],
)
def test_bad_vision_output_not_fabricated(monkeypatch, content, code):
    configure_vision(monkeypatch)
    from integrations.receipt_vision import ModelClient

    monkeypatch.setattr(
        ModelClient,
        "complete",
        lambda *args, **kwargs: ModelResponse({"content": content}, {}, "test"),
    )
    assert extract_receipt(ROOT / "receipts/samples/sample-taxi.png")["error"]["code"] == code


def test_vision_corrupt_image_and_path_escape(monkeypatch, tmp_path):
    configure_vision(monkeypatch)
    path = tmp_path / "bad.png"
    path.write_bytes(b"not an image")
    assert extract_receipt(path)["error"]["code"] == "INVALID_RECEIPT_IMAGE"
    assert (
        execute("read_receipt", {"file_path": "../.env"})["error"]["code"]
        == "RECEIPT_PATH_NOT_ALLOWED"
    )


def test_transport_timeout_has_safe_specific_message():
    from app.config import EndpointSettings
    from integrations.model_client import ModelClient, ProviderError

    def fail(request):
        raise httpx.ReadTimeout("DO NOT PRINT THIS URL OR KEY", request=request)

    with ModelClient(
        EndpointSettings(
            url="https://example.test/v1/chat/completions",
            model="test",
            api_key="secret",
            retries=0,
        ),
        transport=httpx.MockTransport(fail),
    ) as client:
        with pytest.raises(ProviderError, match="API request timed out") as caught:
            client.complete([])
        assert "secret" not in str(caught.value) and "DO NOT PRINT" not in str(caught.value)


def test_low_confidence_receipt_cannot_auto_approve():
    decision, report, events = golden(2)
    next(e for e in events if e["name"] == "read_receipt")["result"]["data"]["confidence"] = 0.4
    errors = verify_policy(decision, report, events, resources())
    assert any("R-02" in e for e in errors)
    assert any("requires manager_review" in e for e in errors)


def test_report_cannot_invent_extra_hotel_nights():
    decision, report, events = golden(5)
    report.line_items[0].hotel_nights = 30
    errors = verify_policy(decision, report, events, resources())
    assert any("Unverified cap" in e for e in errors)
    assert any("Hotel allowance or per-line nights" in e for e in errors)


def test_unknown_vision_fields_return_error(monkeypatch):
    configure_vision(monkeypatch)
    from integrations.receipt_vision import ModelClient

    text = json.dumps(
        dict(
            merchant="Cab company 1",
            date="2026-04-09",
            currency="EUR",
            total="20.00",
            tax="30.00",
            confidence=0.99,
        )
    )
    monkeypatch.setattr(
        ModelClient,
        "complete",
        lambda *args, **kwargs: ModelResponse({"content": text}, {}, "test"),
    )
    assert (
        extract_receipt(ROOT / "receipts/samples/sample-taxi.png")["error"]["code"]
        == "RECEIPT_EXTRACTION_INVALID"
    )


def test_oversized_image_rejected_before_api(monkeypatch, tmp_path):
    configure_vision(monkeypatch)
    path = tmp_path / "large.png"
    with path.open("wb") as stream:
        stream.truncate(5_000_001)
    assert extract_receipt(path)["error"]["code"] == "RECEIPT_TOO_LARGE"


def test_missing_receipt_cannot_hide_unique_exact_card_match():
    decision, report, events = golden(24)
    decision.reconciliation[-1].status = "missing_transaction"
    decision.reconciliation[-1].transaction_id = None
    decision.reconciliation[-1].delta = None
    _, errors = validate_candidate(
        decision.model_dump(mode="json"),
        report,
        events,
        decision.meta.model_dump(mode="json"),
        dict(
            minimum_auto_approval_confidence=".85",
            auto_approval_ceiling="2500",
            resources=resources(),
        ),
    )
    assert any("Unused unique exact card match for L21: TX-EVAL-24-20" in e for e in errors)


def test_stale_missing_transaction_finding_rejected_after_linking():
    from mcp_server.schemas import Finding

    decision, report, events = golden(24)
    decision.findings.append(
        Finding(
            rule_id="DATA-QUALITY",
            line_id="L21",
            severity="query",
            observed="No transaction",
            permitted="Needs transaction",
            excess=None,
            evidence=[Evidence(source="card_transaction", ref="TX-EVAL-24-20")],
        )
    )
    assert any(
        "Unsupported policy finding: DATA-QUALITY:L21" in e
        for e in verify_policy(decision, report, events, resources())
    )


def test_contested_exact_match_is_not_forcibly_assigned():
    decision, report, events = golden(10)
    decision.reconciliation[-1].status = "duplicate"
    decision.reconciliation[-1].transaction_id = None
    decision.reconciliation[-1].delta = None
    _, errors = validate_candidate(
        decision.model_dump(mode="json"),
        report,
        events,
        decision.meta.model_dump(mode="json"),
        dict(
            minimum_auto_approval_confidence=".85",
            auto_approval_ceiling="2500",
            resources=resources(),
        ),
    )
    assert not any("Unused unique exact" in e for e in errors)
