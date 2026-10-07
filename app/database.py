"""Database setup and policy indexing: python -m app.database --help."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from psycopg.types.json import Jsonb

from storage.database import connection

ROOT = Path(__file__).resolve().parents[1]


def initialize() -> None:
    with connection() as db:
        # Serialize schema initialization without dropping existing data.
        db.execute("SELECT pg_advisory_xact_lock(741852965)")
        db.execute((ROOT / "storage/schema.sql").read_text(encoding="utf-8"))


def seed(path: Path) -> dict[str, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("synthetic") is not True:
        raise ValueError("Only synthetic demonstration seed data is supported")
    with connection() as db:
        for row in data["employees"]:
            db.execute(
                "INSERT INTO employees VALUES(%s,%s) ON CONFLICT DO NOTHING",
                (row["employee_id"], Jsonb(row)),
            )
        for row in data["trips"]:
            db.execute(
                "INSERT INTO trips VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                (row["trip_id"], row["employee_id"], Jsonb(row)),
            )
        for row in data["transactions"]:
            db.execute(
                "INSERT INTO card_transactions VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    row["txn_id"],
                    row["employee_id"],
                    row["posted_date"],
                    row["amount"],
                    row["currency"],
                    Jsonb(row),
                ),
            )
        for row in data["settled_lines"]:
            key = hashlib.sha256(
                json.dumps([row["report_id"], row["line_id"]]).encode()
            ).hexdigest()
            db.execute(
                "INSERT INTO settled_lines VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (key, row["employee_id"], row["date"], row["settled_at"], Jsonb(row)),
            )
        db.execute(
            "INSERT INTO app_settings VALUES('as_of',%s) ON CONFLICT DO NOTHING",
            (Jsonb(data["as_of"]),),
        )
    return {
        name: len(data[name]) for name in ("employees", "trips", "transactions", "settled_lines")
    }


def status() -> dict[str, Any]:
    with connection() as db:
        extension = db.execute(
            "SELECT extversion FROM pg_extension WHERE extname='vector'"
        ).fetchone()
        counts = db.execute(
            "SELECT (SELECT count(*) FROM employees) AS employees, "
            "(SELECT count(*) FROM card_transactions) AS transactions, "
            "(SELECT count(*) FROM review_jobs) AS review_jobs, "
            "(SELECT count(*) FROM policy_chunks) AS policy_chunks"
        ).fetchone()
    return {"pgvector": extension["extversion"] if extension else None, **counts}


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "seed", "index-policies", "status"])
    parser.add_argument(
        "--seed-file", type=Path, default=ROOT / "mock_systems/seed/evaluation-data.json"
    )
    args = parser.parse_args()
    try:
        if args.command == "init":
            initialize()
            result: Any = {"schema": "ready"}
        elif args.command == "seed":
            result = {"synthetic_seed_records": seed(args.seed_file)}
        elif args.command == "index-policies":
            from storage.policies import index_policies

            result = index_policies()
        else:
            result = status()
        print(json.dumps(result, indent=2))
        return 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "error": type(error).__name__,
                    "hint": "Check DATABASE_URL, database initialization and embedding settings. "
                    "A remote 403 requires embedding model access from your provider.",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
