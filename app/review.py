"""Run one report or a batch with a real custom LLM and MCP tools."""

import argparse
import asyncio
import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from agent.loop import review
from app.config import ConfigurationError, load_endpoint
from app.intake import intake, redact
from integrations.mcp_client import connect
from integrations.model_client import ModelClient


async def run() -> int:
    parser = argparse.ArgumentParser(
        description="model-driven MCP review and evidence verification"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--report", type=Path)
    group.add_argument("--batch", type=Path)
    parser.add_argument(
        "--queue", action="store_true", help="Save complete validated proposals to mock queue"
    )
    parser.add_argument("--max-steps", type=int, default=12, choices=range(1, 13))
    args = parser.parse_args()
    paths = [args.report] if args.report else sorted(args.batch.glob("*.json"))
    if not paths:
        print(json.dumps({"ok": False, "error": "No report JSON files found."}))
        return 1
    settings = load_endpoint("llm")
    failed = False
    with ModelClient(settings) as model:
        async with connect() as session:
            for path in paths:
                try:
                    report, counts = intake(
                        json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
                    )
                except (OSError, ValueError, ValidationError):
                    print(json.dumps({"status": "invalid_report", "file": path.name}))
                    failed = True
                    continue
                result = await review(
                    report, session, model, settings.model, args.max_steps, args.queue
                )
                result["trace"]["redaction_counts"] = counts
                destination = Path("runtime/reviews") / str(uuid4())
                destination.mkdir(parents=True)
                trace = result.pop("trace")
                (destination / "trace.json").write_text(
                    json.dumps(redact(trace), indent=2), encoding="utf-8"
                )
                (destination / "result.json").write_text(
                    json.dumps(redact(result), indent=2), encoding="utf-8"
                )
                print(json.dumps({**result, "output_directory": str(destination)}, indent=2))
                failed = (
                    failed
                    or result["status"] != "complete"
                    or (args.queue and not result["queued"])
                )
    return 1 if failed else 0


def main() -> int:
    try:
        return asyncio.run(run())
    except ConfigurationError as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1
    except Exception as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_type": type(error).__name__,
                    "hint": "Check .env and database setup; use mock services only for legacy HTTP mode.",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
