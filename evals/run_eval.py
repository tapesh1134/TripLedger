"""Resumable, sequential live evaluation. Labels never enter the agent context."""

import argparse
import asyncio
import csv
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent.loop import review
from app.config import load_endpoint
from app.intake import intake, redact
from evals.scoring import score_case, summarize
from integrations.mcp_client import connect
from integrations.model_client import ModelClient

ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def fingerprint() -> str:
    digest = hashlib.sha256()
    for folder in (
        "app",
        "agent",
        "integrations",
        "mcp_server",
        "evals",
        "receipts",
        "mock_systems",
    ):
        for path in sorted((ROOT / folder).rglob("*")):
            if (
                path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix in {".py", ".json", ".md", ".png", ".jpg"}
            ):
                digest.update(str(path.relative_to(ROOT)).encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


def read_records(directory: Path) -> list[dict[str, Any]]:
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted((directory / "attempts").glob("*.json"))
    ]


def save_summary(directory: Path, labels: list[dict[str, Any]]) -> dict[str, Any]:
    summary = summarize(labels, read_records(directory))
    write_json(directory / "summary.json", summary)
    with (directory / "cases.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = [
            "report_id",
            "passed",
            "complete",
            "decision_correct",
            "money_correct",
            "unsafe_auto_approve",
            "actual_decision",
            "errors",
        ]
        writer = csv.DictWriter(stream, fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summary["cases"])
    lines = [
        "# TripLedger evaluation",
        "",
        "Live-run scores; pending and incomplete cases count as failures.",
        "",
    ]
    for key in (
        "selected_cases",
        "attempted_cases",
        "attempts",
        "case_pass_rate",
        "first_attempt_pass_rate",
        "decision_accuracy",
        "money_accuracy",
        "unsafe_auto_approvals",
        "rule_precision",
        "rule_recall",
    ):
        lines.append(f"- {key}: {summary[key]}")
    lines += [
        "",
        "Latency includes all attempts; tokens are known reported usage, not billing.",
        "See summary.json for latency, usage and per-case errors.",
    ]
    (directory / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


async def run(args: argparse.Namespace) -> int:
    directory = args.run_dir
    labels = json.loads((ROOT / "evals/ground_truth.json").read_text(encoding="utf-8"))
    manifest_path = directory / "manifest.json"
    if args.score_only:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        labels = manifest["labels"]
        summary = save_summary(directory, labels)
        print(json.dumps(summary, indent=2))
        return 0
    if args.cases:
        selected = set(args.cases)
        if selected - {x["report_id"] for x in labels}:
            raise ValueError("Unknown case ID; use EVAL-01 through EVAL-25.")
        labels = [x for x in labels if x["report_id"] in selected]
    settings = load_endpoint("llm")
    config = dict(
        endpoint=settings.url,
        timeout=settings.timeout,
        retries=settings.retries,
        runtime_options={
            k: os.getenv(k, "")
            for k in (
                "VISION_MODEL",
                "RECEIPT_VISION_ENABLED",
                "POLICY_RESOURCE_DIR",
                "RECEIPT_ROOT",
                "CARD_BASE_URL",
                "HR_BASE_URL",
                "TRAVEL_BASE_URL",
                "LEDGER_BASE_URL",
            )
        },
        model=settings.model,
        temperature=settings.temperature,
        extra_body=settings.extra_body,
        max_steps=args.max_steps,
        project_hash=fingerprint(),
    )
    # Only a digest is saved: endpoint URLs and optional provider fields can contain secrets.
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    if manifest_path.exists():
        if not args.resume:
            raise ValueError("Run directory exists; use --resume or a new --run-dir.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["config_hash"] != config_hash or manifest["labels"] != labels:
            raise ValueError("Project/model/selection changed. Use a new run directory.")
    else:
        if args.resume:
            raise ValueError("No manifest to resume; omit --resume for the first run.")
        if directory.exists() and any(directory.iterdir()):
            raise ValueError("Use an empty directory for a new evaluation.")
        write_json(
            manifest_path,
            dict(
                version=1,
                created_at=datetime.now(UTC).isoformat(),
                model=settings.model,
                config_hash=config_hash,
                labels=labels,
            ),
        )
    records = read_records(directory)
    latest = {r["report_id"]: r for r in records}
    with ModelClient(settings) as model:
        for label in labels:
            rid = label["report_id"]
            if rid in latest and (
                not args.retry_failed or score_case(label, latest[rid])["passed"]
            ):
                print(json.dumps(dict(report_id=rid, skipped=True)), flush=True)
                continue
            print(json.dumps(dict(report_id=rid, status="running")), flush=True)
            started = time.perf_counter()
            report, counts = intake(
                json.loads((ROOT / label["report"]).read_text(encoding="utf-8"))
            )
            try:
                async with connect() as session:
                    outcome = await review(
                        report, session, model, settings.model, args.max_steps, queue=False
                    )
                trace = outcome.pop("trace")
                trace["redaction_counts"] = counts
            except Exception as error:
                outcome = dict(status="incomplete", queued=False, error_type=type(error).__name__)
                trace = dict(reason="EVALUATION_RUNNER_ERROR", steps=[], tools=[])
            record = dict(
                report_id=rid,
                result=outcome,
                trace=trace,
                wall_ms=round((time.perf_counter() - started) * 1000),
                created_at=datetime.now(UTC).isoformat(),
            )
            name = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f") + "-" + str(uuid4())
            write_json(directory / "attempts" / (name + ".json"), redact(record))
            summary = save_summary(directory, labels)
            print(json.dumps(score_case(label, record)), flush=True)
    summary = save_summary(directory, labels)
    print(json.dumps({k: v for k, v in summary.items() if k != "cases"}, indent=2))
    print("Results: " + str(directory / "SUMMARY.md"))
    return 0 if summary["case_pass_rate"] == 1 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate TripLedger with your custom LLM")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--score-only", action="store_true")
    parser.add_argument("--max-steps", type=int, default=12, choices=range(1, 13))
    args = parser.parse_args()
    if args.retry_failed and not args.resume:
        parser.error("--retry-failed requires --resume")
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        print(
            "Interrupted. Saved attempts remain; resume using the same selection and run directory."
        )
        return 130
    except (ValueError, OSError) as error:
        print(
            json.dumps(
                {
                    "error_type": type(error).__name__,
                    "hint": str(error)
                    if isinstance(error, ValueError)
                    else "Check run directory and files.",
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
