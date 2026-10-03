"""Run with python -m app.cli; smoke commands send fixed synthetic text only."""

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.config import load_endpoint
from integrations.model_client import ModelClient, ProviderError
from mcp_server.schemas import ComputeRequest, Decision, ExpenseReport
from mcp_server.tools_compute import compute_totals


def read_json(path: str) -> Any:
    # Parse JSON fractions directly into Decimal; never through binary floating point.
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_float=Decimal)


def main() -> int:
    parser = argparse.ArgumentParser(description="TripLedger Day 1 foundation")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate-report", "validate-decision", "compute"):
        command = commands.add_parser(name)
        command.add_argument("file")
    schema = commands.add_parser("export-schemas")
    schema.add_argument("--directory", default="schemas")
    commands.add_parser("llm-smoke")
    commands.add_parser("embedding-smoke")
    args = parser.parse_args()
    try:
        if args.command == "validate-report":
            report = ExpenseReport.model_validate(read_json(args.file))
            print(json.dumps({"valid": True, "line_items": len(report.line_items)}))
        elif args.command == "validate-decision":
            Decision.model_validate(read_json(args.file))
            print(json.dumps({"valid": True, "scope": "schema only; not policy verification"}))
        elif args.command == "compute":
            request = ComputeRequest.model_validate(read_json(args.file))
            result = compute_totals(
                [line.model_dump() for line in request.lines],
                [cap.model_dump() for cap in request.caps],
                request.base_currency,
            )
            print(json.dumps(result, indent=2))
        elif args.command == "export-schemas":
            destination = Path(args.directory)
            destination.mkdir(parents=True, exist_ok=True)
            for name, model in (
                ("report", ExpenseReport),
                ("decision", Decision),
                ("compute-request", ComputeRequest),
            ):
                (destination / f"{name}.schema.json").write_text(
                    json.dumps(model.model_json_schema(), indent=2) + "\n", encoding="utf-8"
                )
            print("Exported 3 JSON schemas")
        elif args.command == "llm-smoke":
            with ModelClient(load_endpoint("llm")) as client:
                response = client.complete(
                    [
                        {
                            "role": "user",
                            "content": "Synthetic connectivity test. Reply: TripLedger ready.",
                        }
                    ]
                )
            # Deliberately avoid printing untrusted response text.
            print(json.dumps({"ok": True, "usage": response.usage}, indent=2))
        elif args.command == "embedding-smoke":
            with ModelClient(load_endpoint("embedding")) as client:
                embedding = client.embed("Synthetic travel expense connectivity test.")
            print(
                json.dumps(
                    {
                        "ok": True,
                        "dimensions": embedding["dimensions"],
                        "usage": embedding["usage"],
                    },
                    indent=2,
                )
            )
    except ValidationError as error:
        # No input values in diagnostics; they could contain sensitive text.
        problems = [
            {"field": ".".join(map(str, item["loc"])), "type": item["type"]}
            for item in error.errors(include_input=False, include_context=False)
        ]
        print(json.dumps({"ok": False, "validation_errors": problems}), file=sys.stderr)
        return 1
    except ProviderError as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        return 1
    except (ValueError, OSError):
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "Invalid input/config or file. See README and .env.example.",
                }
            ),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
