"""Four service roles on independent HTTP ports, using the standard library."""

import calendar
import hashlib
import json
import sqlite3
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from pydantic import ValidationError

from mcp_server.schemas import Decision


def failure(code: str, message: str, retryable: bool = False) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "hint": "Retry transient errors; otherwise check the input.",
        },
    }


class MockServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        role: str,
        data: dict[str, Any],
        port: int,
        queue_path: Path,
        fail_every: int = 10,
        travel_delay: float = 0.15,
    ):
        self.role, self.data = role, data
        self.fail_every, self.travel_delay = fail_every, travel_delay
        self.counter = 0
        self.lock = threading.Lock()
        self.queue_path = queue_path
        if role == "ledger":
            queue_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(queue_path) as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS decisions "
                    "(id TEXT PRIMARY KEY, report_id TEXT UNIQUE, payload TEXT NOT NULL)"
                )
        super().__init__(("127.0.0.1", port), Handler)


class Handler(BaseHTTPRequestHandler):
    server: MockServer

    def log_message(self, format: str, *args: Any) -> None:
        pass  # Do not log request bodies or query values.

    def send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if status == 503:
            self.send_header("Retry-After", "1")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # A timeout test may deliberately close its connection.

    def do_GET(self) -> None:
        try:
            self.get_route()
        except (ValueError, KeyError, TypeError):
            self.send_json(400, failure("INVALID_INPUT", "Invalid or missing query parameter."))
        except sqlite3.Error:
            self.send_json(503, failure("STORE_UNAVAILABLE", "Queue storage unavailable.", True))

    def get_route(self) -> None:
        parsed = urlsplit(self.path)
        path, query = parsed.path, parse_qs(parsed.query, keep_blank_values=True)

        def param(key: str, default: str | None = None) -> str:
            values = query.get(key)
            if values is None and default is not None:
                return default
            if values is None or len(values) != 1 or not values[0]:
                raise ValueError(key)
            return values[0]

        if path == "/health":
            self.send_json(200, {"ok": True, "service": self.server.role, "synthetic": True})
            return
        data, role = self.server.data, self.server.role
        if role == "card" and (path == "/transactions" or path.startswith("/transactions/")):
            with self.server.lock:
                self.server.counter += 1
                fail = (
                    self.server.fail_every > 0 and self.server.counter % self.server.fail_every == 0
                )
            if fail:
                self.send_json(
                    503, failure("SIMULATED_FAILURE", "Deliberate card-feed failure.", True)
                )
                return
            if path.startswith("/transactions/"):
                self.single(data["transactions"], "txn_id", path.rsplit("/", 1)[-1])
                return
            employee, start, end = (
                param("employee_id"),
                date.fromisoformat(param("from")),
                date.fromisoformat(param("to")),
            )
            if start > end:
                raise ValueError("date range")
            rows = sorted(
                [
                    x
                    for x in data["transactions"]
                    if x["employee_id"] == employee
                    and start <= date.fromisoformat(x["posted_date"]) <= end
                ],
                key=lambda x: x["txn_id"],
            )
            offset = int(param("cursor", "0"))
            if offset < 0 or offset % 20 or offset > len(rows):
                raise ValueError("cursor")
            self.send_json(
                200,
                {
                    "items": rows[offset : offset + 20],
                    "next_cursor": str(offset + 20) if offset + 20 < len(rows) else None,
                },
            )
        elif role == "travel" and (path == "/trips" or path.startswith("/trips/")):
            time.sleep(self.server.travel_delay)
            if path == "/trips":
                employee = param("employee_id")
                self.send_json(
                    200, {"items": [x for x in data["trips"] if x["employee_id"] == employee]}
                )
            else:
                self.single(data["trips"], "trip_id", path.rsplit("/", 1)[-1])
        elif role == "hr" and path.startswith("/employees/"):
            self.single(data["employees"], "employee_id", path.rsplit("/", 1)[-1])
        elif role == "ledger" and path == "/settled-lines":
            employee, months = param("employee_id"), int(param("months", "12"))
            if not 1 <= months <= 12:
                raise ValueError("months")
            # Fixed fixture clock ensures repeatable results. Optional as_of is explicit.
            as_of = date.fromisoformat(param("as_of", data["as_of"]))
            ordinal = as_of.year * 12 + as_of.month - 1 - months
            year, month = ordinal // 12, ordinal % 12 + 1
            cutoff = date(year, month, min(as_of.day, calendar.monthrange(year, month)[1]))
            self.send_json(
                200,
                {
                    "as_of": as_of.isoformat(),
                    "items": [
                        x
                        for x in data["settled_lines"]
                        if x["employee_id"] == employee
                        and cutoff <= date.fromisoformat(x["date"]) <= as_of
                        and date.fromisoformat(x["settled_at"]) <= as_of
                    ],
                },
            )
        elif role == "ledger" and path == "/review-queue":
            with sqlite3.connect(self.server.queue_path) as db:
                rows = db.execute("SELECT id, payload FROM decisions ORDER BY rowid").fetchall()
            self.send_json(
                200,
                {"items": [{"id": key, "decision": json.loads(payload)} for key, payload in rows]},
            )
        else:
            self.send_json(404, failure("NOT_FOUND", "Unknown endpoint."))

    def single(self, rows: list[dict[str, Any]], key: str, value: str) -> None:
        match = next((x for x in rows if x[key] == value), None)
        code = {
            "trip_id": "TRIP_NOT_FOUND",
            "employee_id": "EMPLOYEE_NOT_FOUND",
            "txn_id": "TRANSACTION_NOT_FOUND",
        }[key]
        self.send_json(200 if match else 404, match or failure(code, "Record not found."))

    def do_POST(self) -> None:
        if self.server.role != "ledger" or urlsplit(self.path).path != "/review-queue":
            self.send_json(404, failure("NOT_FOUND", "Only review-queue writes are supported."))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1_000_000:
                raise ValueError("body length")
            decision = Decision.model_validate_json(self.rfile.read(length))
            canonical = json.dumps(decision.model_dump(mode="json"), sort_keys=True)
            key = "QUEUE-" + hashlib.sha256(decision.report_id.encode()).hexdigest()[:16]
            with sqlite3.connect(self.server.queue_path, timeout=10) as db:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute(
                    "SELECT payload FROM decisions WHERE report_id=?", (decision.report_id,)
                ).fetchone()
                if existing and existing[0] != canonical:
                    self.send_json(
                        409, failure("DECISION_CONFLICT", "A different decision already exists.")
                    )
                    return
                db.execute(
                    "INSERT OR IGNORE INTO decisions VALUES (?, ?, ?)",
                    (key, decision.report_id, canonical),
                )
            self.send_json(200, {"queued": True, "id": key})
        except (ValueError, ValidationError):
            self.send_json(400, failure("INVALID_DECISION", "Body must match the decision schema."))
        except sqlite3.Error:
            self.send_json(503, failure("STORE_UNAVAILABLE", "Queue storage unavailable.", True))
