"""Local, single-worker reviews with atomic result persistence."""

import asyncio
import json
import re
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent.loop import review
from app.config import load_endpoint
from app.intake import intake, redact
from integrations.mcp_client import connect
from integrations.model_client import ModelClient
from mcp_server.schemas import ExpenseReport

JOB_ID = re.compile(r"^[0-9a-f]{32}$")


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def run_review(report: ExpenseReport) -> dict[str, Any]:
    async def execute() -> dict[str, Any]:
        settings = load_endpoint("llm")
        with ModelClient(settings) as model:
            async with connect() as session:
                return await review(report, session, model, settings.model, 12, False)

    return asyncio.run(execute())


class BusyError(ValueError):
    """A review is already using this local worker."""


class JobStore:
    def __init__(
        self,
        root: Path,
        runner: Callable[[ExpenseReport], dict[str, Any]] = run_review,
    ) -> None:
        self.root = root
        self.runner = runner
        self.lock = threading.Lock()
        self.active: str | None = None
        root.mkdir(parents=True, exist_ok=True)
        # Startup recovery never silently repeats a possibly billable request.
        for path in root.glob("*/job.json"):
            job = json.loads(path.read_text(encoding="utf-8"))
            if job["status"] == "running":
                job.update(status="interrupted", error="Server stopped before saving completion.")
                write_json(path, job)

    def directory(self, job_id: str) -> Path:
        if not JOB_ID.fullmatch(job_id):
            raise FileNotFoundError
        path = self.root / job_id
        if not path.is_dir():
            raise FileNotFoundError
        return path

    def artifact(self, job_id: str, name: str) -> bytes:
        if name not in {"result.json", "trace.json"}:
            raise FileNotFoundError
        return (self.directory(job_id) / name).read_bytes()

    def close(self) -> None:
        pass

    def get(self, job_id: str) -> dict[str, Any]:
        value: dict[str, Any] = json.loads(
            (self.directory(job_id) / "job.json").read_text(encoding="utf-8")
        )
        return value

    def list(self) -> list[dict[str, Any]]:
        jobs = [self.get(p.parent.name) for p in self.root.glob("*/job.json")]
        return sorted(jobs, key=lambda j: j["created_at"], reverse=True)

    def submit(self, raw: Any) -> dict[str, Any]:
        report, counts = intake(raw)
        with self.lock:
            if self.active:
                raise BusyError("A review is already running. Wait for it to finish.")
            job_id = uuid4().hex
            directory = self.root / job_id
            directory.mkdir()
            job = {
                "id": job_id,
                "report_id": report.report_id,
                "status": "running",
                "created_at": datetime.now(UTC).isoformat(),
            }
            write_json(directory / "job.json", job)
            self.active = job_id
            threading.Thread(target=self._work, args=(job, report, counts), daemon=True).start()
            return dict(job)

    def _work(self, job: dict[str, Any], report: ExpenseReport, counts: dict[str, int]) -> None:
        directory = self.root / job["id"]
        job = dict(job)
        try:
            result = self.runner(report)
            trace = result.pop("trace")
            trace["redaction_counts"] = counts
            write_json(directory / "trace.json", redact(trace))
            write_json(directory / "result.json", redact(result))
            job.update(status=result["status"], result=redact(result))
        except Exception as error:
            # Never send endpoint URLs, credentials or raw provider exceptions to the browser.
            job.update(status="failed", error=type(error).__name__)
        finally:
            job["finished_at"] = datetime.now(UTC).isoformat()
            try:
                write_json(directory / "job.json", job)
            finally:
                with self.lock:
                    self.active = None
