"""SQL-backed business evidence, preserving the public MCP response contracts."""

import calendar
import hashlib
from datetime import date
from typing import Any

from psycopg.types.json import Jsonb

from storage.database import connection


class BusinessStore:
    def get_employee(self, employee_id: str) -> Any:
        from mcp_server.backend import BackendError

        with connection() as db:
            row = db.execute(
                "SELECT payload FROM employees WHERE employee_id=%s", (employee_id,)
            ).fetchone()
        if not row:
            raise BackendError("EMPLOYEE_NOT_FOUND")
        return row["payload"]

    def get_trip(self, trip_id: str) -> Any:
        from mcp_server.backend import BackendError

        with connection() as db:
            row = db.execute("SELECT payload FROM trips WHERE trip_id=%s", (trip_id,)).fetchone()
        if not row:
            raise BackendError("TRIP_NOT_FOUND")
        return row["payload"]

    def list_card_transactions(
        self, employee_id: str, start: str, end: str, cursor: str | None = None
    ) -> dict[str, Any]:
        begin, finish = date.fromisoformat(start), date.fromisoformat(end)
        offset = int(cursor or "0")
        if begin > finish or offset < 0 or offset % 20:
            raise ValueError("Invalid card date range or cursor")
        with connection() as db:
            rows = db.execute(
                "SELECT payload FROM card_transactions WHERE employee_id=%s "
                "AND posted_date BETWEEN %s AND %s ORDER BY txn_id LIMIT 21 OFFSET %s",
                (employee_id, begin, finish, offset),
            ).fetchall()
        return {
            "items": [r["payload"] for r in rows[:20]],
            "next_cursor": str(offset + 20) if len(rows) > 20 else None,
        }

    def list_settled_lines(self, employee_id: str, months: int = 12) -> Any:
        if not 1 <= months <= 12:
            raise ValueError("months must be 1..12")
        with connection() as db:
            setting = db.execute("SELECT value FROM app_settings WHERE key='as_of'").fetchone()
            as_of = date.fromisoformat(setting["value"]) if setting else date.today()
            ordinal = as_of.year * 12 + as_of.month - 1 - months
            year, month = ordinal // 12, ordinal % 12 + 1
            cutoff = date(year, month, min(as_of.day, calendar.monthrange(year, month)[1]))
            rows = db.execute(
                "SELECT payload FROM settled_lines WHERE employee_id=%s "
                "AND expense_date BETWEEN %s AND %s AND settled_at <= %s ORDER BY id",
                (employee_id, cutoff, as_of, as_of),
            ).fetchall()
        return {"as_of": as_of.isoformat(), "items": [r["payload"] for r in rows]}

    def save_decision(self, decision: dict[str, Any]) -> Any:
        from mcp_server.backend import BackendError
        from mcp_server.schemas import Decision

        value = Decision.model_validate(decision).model_dump(mode="json")
        report_id = value["report_id"]
        key = "QUEUE-" + hashlib.sha256(report_id.encode()).hexdigest()[:16]
        with connection() as db:
            db.execute(
                "INSERT INTO review_decisions(id,report_id,payload) VALUES (%s,%s,%s) "
                "ON CONFLICT(report_id) DO NOTHING",
                (key, report_id, Jsonb(value)),
            )
            row = db.execute(
                "SELECT payload FROM review_decisions WHERE report_id=%s", (report_id,)
            ).fetchone()
            if row["payload"] != value:
                raise BackendError("DECISION_CONFLICT")
        return {"queued": True, "id": key}
