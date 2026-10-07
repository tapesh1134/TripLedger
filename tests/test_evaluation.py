import json
from argparse import Namespace

import pytest
from test_policy import golden

from evals.run_eval import ROOT, read_records, run, save_summary, write_json
from evals.scoring import score_case, summarize, usage


def labels():
    return json.loads((ROOT / "evals/ground_truth.json").read_text())


def record(number):
    decision, report, events = golden(number)
    return dict(
        report_id=report.report_id,
        result=dict(status="complete", decision=decision.model_dump(mode="json")),
        trace=dict(tools=events, steps=[dict(usage=dict(tokens_in=100, tokens_out=20))]),
        wall_ms=1000,
    )


@pytest.mark.parametrize("number", range(1, 26))
def test_reference_outcomes_score_correctly(number):
    result = score_case(labels()[number - 1], record(number))
    assert result["passed"], result


def test_incomplete_manager_fallback_is_not_correct_decision():
    partial = dict(result=dict(status="incomplete", decision=dict(decision="manager_review")))
    result = score_case(labels()[23], partial)
    assert not result["passed"] and not result["decision_correct"]


def test_wrong_money_and_unsafe_approval_detected():
    r = record(24)
    r["result"]["decision"]["decision"] = "auto_approve"
    r["result"]["decision"]["reimbursable_total"]["amount"] = "0"
    result = score_case(labels()[23], r)
    assert result["unsafe_auto_approve"] and not result["money_correct"]


def test_retries_do_not_hide_first_failure_or_tokens():
    first = record(1)
    first["result"]["status"] = "incomplete"
    summary = summarize(labels()[:1], [first, record(1)])
    assert summary["first_attempt_pass_rate"] == 0
    assert summary["case_pass_rate"] == 1
    assert summary["all_attempt_usage"]["known_tokens_in"] == 200


def test_pending_and_empty_precision_not_reported_as_perfect():
    summary = summarize(labels(), [])
    assert summary["pending_cases"] == 25 and summary["case_pass_rate"] == 0
    assert summary["rule_precision"] is None


def test_unknown_usage_and_model_failure_preserved():
    r = record(1)
    r["trace"]["steps"][0]["usage"]["tokens_out"] = None
    assert usage(r)["usage_incomplete"]
    r["trace"]["reason"] = "MODEL_API_ERROR"
    assert usage(r)["known_tokens_in"] == 100


def test_wrong_line_rule_and_pagination_counted():
    r = record(24)
    r["result"]["decision"]["findings"][0]["line_id"] = "L1"
    r["trace"]["tools"] = [e for e in r["trace"]["tools"] if e["args"].get("cursor") != "20"]
    result = score_case(labels()[23], r)
    assert "missing_line_rule_findings" in result["errors"]
    assert "pagination_not_demonstrated" in result["errors"]


def test_saved_summary_is_offline_and_retains_attempts(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    write_json(tmp_path / "manifest.json", dict(labels=labels()[:1]))
    write_json(tmp_path / "attempts/001.json", record(1))
    assert len(read_records(tmp_path)) == 1
    assert save_summary(tmp_path, labels()[:1])["case_pass_rate"] == 1
    assert (tmp_path / "cases.csv").exists()
    assert asyncio.run(run(Namespace(run_dir=tmp_path, score_only=True))) == 0


def test_resume_skips_saved_cases_and_retry_preserves_history(tmp_path, monkeypatch):
    import asyncio
    from contextlib import asynccontextmanager

    import evals.run_eval as runner
    from app.config import EndpointSettings

    calls = []

    @asynccontextmanager
    async def connection():
        yield object()

    async def review_report(report, *args, **kwargs):
        calls.append(report.report_id)
        value = record(int(report.report_id[-2:]))
        if report.report_id == "EVAL-02" and calls.count("EVAL-02") == 1:
            value["result"]["status"] = "incomplete"
        return {**value["result"], "trace": value["trace"]}

    monkeypatch.setattr(runner, "connect", connection)
    monkeypatch.setattr(runner, "review", review_report)
    monkeypatch.setattr(
        runner,
        "load_endpoint",
        lambda _: EndpointSettings(
            url="https://example.test/v1/chat/completions", model="test", api_key="not-a-key"
        ),
    )
    args = Namespace(
        run_dir=tmp_path,
        cases=["EVAL-01", "EVAL-02"],
        score_only=False,
        resume=False,
        retry_failed=False,
        max_steps=12,
    )
    assert asyncio.run(run(args)) == 1
    args.resume = True
    assert asyncio.run(run(args)) == 1
    assert len(calls) == 2
    args.retry_failed = True
    assert asyncio.run(run(args)) == 0
    assert calls == ["EVAL-01", "EVAL-02", "EVAL-02"]
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["first_attempt_pass_rate"] == 0.5 and summary["attempts"] == 3
    args.max_steps = 11
    with pytest.raises(ValueError, match="changed"):
        asyncio.run(run(args))


def test_prohibited_expense_delta_feedback_gives_exact_correction():
    from decimal import Decimal

    from test_policy import resources

    from app.assembler import validate_candidate

    decision, report, events = golden(21)
    decision.reconciliation[0].delta = Decimal("20.00")
    policy = dict(
        minimum_auto_approval_confidence=".85", auto_approval_ceiling="2500", resources=resources()
    )
    candidate, errors = validate_candidate(
        decision.model_dump(mode="json"),
        report,
        events,
        decision.meta.model_dump(mode="json"),
        policy,
    )
    assert candidate is None
    assert any("expected delta=0.00" in e and "Policy disallowance" in e for e in errors)
    decision.reconciliation[0].delta = Decimal("0.00")
    candidate, errors = validate_candidate(
        decision.model_dump(mode="json"),
        report,
        events,
        decision.meta.model_dump(mode="json"),
        policy,
    )
    assert not errors and candidate is not None
    assert candidate.disallowed_total.amount == Decimal("20.00")
