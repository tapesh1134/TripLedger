"""integration commands. No model, embedding, or agent call is needed."""

import argparse
import json
import logging
from datetime import date, timedelta
from pathlib import Path

from mcp_server.backend import Backend, BackendError
from mcp_server.fx import fx_convert


def main() -> int:
    parser = argparse.ArgumentParser(description="TripLedger integrations")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo")
    commands.add_parser("retry-demo")
    queue = commands.add_parser("queue-example")
    queue.add_argument("--file", default="examples/decision.json")
    fx = commands.add_parser("fx")
    fx.add_argument("--amount", default="100")
    fx.add_argument("--from-ccy", default="USD")
    fx.add_argument("--to-ccy", default="EUR")
    fx.add_argument("--date", default="2026-04-09")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("mcp_server.backend").setLevel(logging.INFO)
    backend = None
    try:
        if args.command == "fx":
            print(
                json.dumps(fx_convert(args.amount, args.from_ccy, args.to_ccy, args.date), indent=2)
            )
            return 0
        backend = Backend()
        if args.command == "demo":
            employee = backend.get_employee("EMP-2231")
            trip = backend.get_trip("TRP-8890")
            start = (date.fromisoformat(trip["start_date"]) - timedelta(days=2)).isoformat()
            end = (date.fromisoformat(trip["end_date"]) + timedelta(days=2)).isoformat()
            first = backend.list_card_transactions("EMP-2231", start, end)
            transactions = backend.all_card_transactions("EMP-2231", start, end)
            settled = backend.list_settled_lines("EMP-2231")
            print(
                json.dumps(
                    {
                        "employee": employee,
                        "trip": trip,
                        "first_page_count": len(first["items"]),
                        "first_page_next_cursor": first["next_cursor"],
                        "all_pages_count": len(transactions),
                        "hotel_found_after_pagination": any(
                            t["merchant_raw"] == "Hotel Ascot Milano" for t in transactions
                        ),
                        "settled_lines": settled,
                        "retries": backend.http.retry_count,
                    },
                    indent=2,
                )
            )
        elif args.command == "retry-demo":
            for _ in range(12):
                backend.list_card_transactions("EMP-2231", "2026-04-07", "2026-04-14")
            print(json.dumps({"successful_calls": 12, "retries": backend.http.retry_count}))
        elif args.command == "queue-example":
            decision = json.loads(Path(args.file).read_text(encoding="utf-8"))
            print(json.dumps(backend.save_decision(decision), indent=2))
        return 0
    except BackendError as error:
        print(json.dumps(error.envelope(), indent=2))
        return 1
    except (OSError, ValueError):
        print(
            json.dumps(
                {"ok": False, "error": "Invalid local input or inaccessible data/cache file."}
            )
        )
        return 1
    finally:
        if backend:
            backend.close()


if __name__ == "__main__":
    raise SystemExit(main())
