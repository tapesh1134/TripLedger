"""Postgres is the source of truth for dashboard reports, jobs and artifacts."""

import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from app.intake import intake, redact
from app.review_jobs import JOB_ID, BusyError, run_review
from mcp_server.schemas import ExpenseReport
from storage.database import StorageError, connection, database_url

# Session advisory lock prevents a second dashboard from interrupting an active
# worker, even when launched from another copy of the project.
DASHBOARD_LOCK = 741852963


class PostgresJobStore:
    def __init__(
        self, root: Path, runner: Callable[[ExpenseReport], dict[str, Any]] = run_review
    ) -> None:
        self.root, self.runner = root, runner
        self.lock = threading.Lock()
        self.active: str | None = None
        self.guard: Any = None
        try:
            self.guard = psycopg.connect(database_url(), autocommit=True, connect_timeout=5)
            if not self.guard.execute(
                "SELECT pg_try_advisory_lock(%s)", (DASHBOARD_LOCK,)
            ).fetchone()[0]:
                raise StorageError("Another dashboard is already connected to this database")
            with connection() as db:
                db.execute(
                    "UPDATE review_jobs SET status='interrupted', finished_at=now(), "
                    "job=job || jsonb_build_object('status','interrupted','error',"
                    "'Server stopped before saving completion.','finished_at',now()) "
                    "WHERE status='running'"
                )
        except (psycopg.Error, StorageError):
            self.close()
            raise StorageError(
                "Could not start SQL job store; check setup or another dashboard"
            ) from None

    def close(self) -> None:
        if self.guard is not None:
            self.guard.close()

    def get(self, job_id: str) -> dict[str, Any]:
        if not JOB_ID.fullmatch(job_id):
            raise FileNotFoundError
        with connection() as db:
            row = db.execute("SELECT job FROM review_jobs WHERE id=%s", (job_id,)).fetchone()
        if not row:
            raise FileNotFoundError
        return row["job"]  # type: ignore[no-any-return]

    def list(self) -> list[dict[str, Any]]:
        with connection() as db:
            rows = db.execute("SELECT job FROM review_jobs ORDER BY created_at DESC").fetchall()
        return [row["job"] for row in rows]

    def artifact(self, job_id: str, name: str) -> bytes:
        if not JOB_ID.fullmatch(job_id) or name not in {"result.json", "trace.json"}:
            raise FileNotFoundError
        with connection() as db:
            row = db.execute(
                "SELECT result, trace FROM review_jobs WHERE id=%s", (job_id,)
            ).fetchone()
        value = row[name.removesuffix(".json")] if row else None
        if value is None:
            raise FileNotFoundError
        return json.dumps(value, indent=2).encode()

    def submit(self, raw: Any) -> dict[str, Any]:
        report, counts = intake(raw)
        with self.lock:
            if self.active:
                raise BusyError("A review is already running. Wait for it to finish.")
            try:
                # Detect loss of the cross-process lock connection before work.
                self.guard.execute("SELECT 1")
            except psycopg.Error:
                raise StorageError(
                    "Dashboard database session lost; restart the dashboard"
                ) from None
            job = {
                "id": uuid4().hex,
                "report_id": report.report_id,
                "status": "running",
                "created_at": datetime.now(UTC).isoformat(),
            }
            with connection() as db:
                db.execute(
                    "INSERT INTO review_jobs(id,report_id,status,created_at,report,job) "
                    "VALUES(%s,%s,%s,%s,%s,%s)",
                    (
                        job["id"],
                        job["report_id"],
                        job["status"],
                        job["created_at"],
                        Jsonb(redact(report.model_dump(mode="json"))),
                        Jsonb(job),
                    ),
                )
            self.active = job["id"]
            threading.Thread(
                target=self._work, args=(dict(job), report, counts), daemon=True
            ).start()
            return dict(job)

    def _work(self, job: dict[str, Any], report: ExpenseReport, counts: dict[str, int]) -> None:
        result, trace = None, None
        try:
            result = self.runner(report)
            trace = result.pop("trace")
            trace["redaction_counts"] = counts
            result, trace = redact(result), redact(trace)
            job.update(status=result["status"], result=result)
        except Exception as error:
            result, trace = None, None
            job.update(status="failed", error=type(error).__name__)
        job["finished_at"] = datetime.now(UTC).isoformat()
        try:
            with connection() as db:
                db.execute(
                    "UPDATE review_jobs SET status=%s,finished_at=%s,job=%s,result=%s,trace=%s "
                    "WHERE id=%s AND status='running'",
                    (
                        job["status"],
                        job["finished_at"],
                        Jsonb(job),
                        Jsonb(result),
                        Jsonb(trace),
                        job["id"],
                    ),
                )
        except StorageError:
            # Leave the durable running row for explicit interruption recovery.
            # Refuse another request until restart instead of losing work silently.
            return
        with self.lock:
            self.active = None
