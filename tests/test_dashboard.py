import json
import threading
import time
from pathlib import Path

import httpx
import pytest

from app.dashboard import project_lock
from app.review_jobs import BusyError, JobStore, write_json
from app.web import create_server

ROOT = Path(__file__).resolve().parents[1]


def report():
    return json.loads((ROOT / "evals/reports/EVAL-01.json").read_text())


def finish(store, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = store.get(job_id)
        if job["status"] != "running":
            return job
        time.sleep(0.01)
    pytest.fail("Worker did not finish")


def outcome(_):
    return {
        "status": "incomplete",
        "decision": {"reason": "STEP_BUDGET_EXHAUSTED"},
        "queued": False,
        "trace": {"steps": []},
    }


def test_worker_persists_incomplete_and_trace(tmp_path):
    store = JobStore(tmp_path, outcome)
    job = store.submit(report())
    saved = finish(store, job["id"])
    assert saved["status"] == "incomplete"
    assert saved["result"]["decision"]["reason"] == "STEP_BUDGET_EXHAUSTED"
    assert not saved["result"]["queued"]
    assert "redaction_counts" in json.loads((tmp_path / job["id"] / "trace.json").read_text())
    assert JobStore(tmp_path).get(job["id"]) == saved


def test_concurrent_submission_rejected(tmp_path):
    started, release = threading.Event(), threading.Event()

    def blocking(value):
        started.set()
        assert release.wait(5)
        return outcome(value)

    store = JobStore(tmp_path, blocking)
    job = store.submit(report())
    assert started.wait(2)
    try:
        with pytest.raises(BusyError):
            store.submit(report())
        assert len(store.list()) == 1
    finally:
        release.set()
    finish(store, job["id"])


def test_startup_marks_interrupted_without_rerun(tmp_path):
    directory = tmp_path / ("a" * 32)
    directory.mkdir()
    write_json(directory / "job.json", dict(id="a" * 32, status="running", created_at="now"))
    store = JobStore(tmp_path, lambda _: pytest.fail("Must not rerun"))
    assert store.list()[0]["status"] == "interrupted"


def test_exception_redacted_and_worker_released(tmp_path):
    def fails(_):
        raise RuntimeError("SECRET-KEY https://private-provider")

    store = JobStore(tmp_path, fails)
    saved = finish(store, store.submit(report())["id"])
    assert saved["status"] == "failed"
    assert saved["error"] == "RuntimeError"
    assert "SECRET" not in json.dumps(saved)


def test_project_lock_prevents_second_dashboard(tmp_path):
    with project_lock(tmp_path), pytest.raises(OSError), project_lock(tmp_path):
        pass
    with project_lock(tmp_path):
        pass


@pytest.fixture
def server(tmp_path):
    store = JobStore(tmp_path, outcome)
    http = create_server(store, "test-session", 0)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    with httpx.Client(
        base_url=f"http://127.0.0.1:{http.server_port}",
        headers={"X-Session-Token": "test-session"},
        trust_env=False,
    ) as client:
        yield client, store
    http.shutdown()
    http.server_close()
    thread.join()


def test_http_submit_poll_download(server):
    client, store = server
    response = client.post("/api/jobs", json=report())
    assert response.status_code == 202
    job_id = response.json()["id"]
    finish(store, job_id)
    assert client.get("/api/jobs").json()[0]["id"] == job_id
    assert client.get("/api/jobs/" + job_id).json()["status"] == "incomplete"
    assert client.get("/api/jobs/" + job_id + "/result.json").json()["status"] == "incomplete"
    assert client.get("/api/jobs/" + job_id + "/trace.json").status_code == 200
    assert client.get("/api/jobs/" + job_id + "/job.json").status_code == 404


@pytest.mark.parametrize(
    "headers",
    [
        {"X-Session-Token": ""},
        {"X-Session-Token": "wrong"},
        {"Origin": "https://evil.example"},
        {"Host": "evil.example"},
    ],
)
def test_local_access_controls(server, headers):
    client, store = server
    assert client.post("/api/jobs", json=report(), headers=headers).status_code == 403
    assert client.get("/api/jobs", headers=headers).status_code == 403
    assert store.list() == []


def test_invalid_reports_do_not_start_worker(server):
    client, store = server
    assert client.post("/api/jobs", json={}).status_code == 422
    assert (
        client.post(
            "/api/jobs", content="{", headers={"Content-Type": "application/json"}
        ).status_code
        == 400
    )
    assert client.post("/api/jobs", content="{}").status_code == 415
    assert (
        client.post(
            "/api/jobs",
            content=" " * (1024 * 1024 + 1),
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )
    assert store.list() == []


def test_static_assets_and_example_allowlist(server):
    client, _ = server
    assert client.get("/").status_code == 200
    assert "frame-ancestors" in client.get("/").headers["content-security-policy"]
    assert client.get("/dashboard.js").status_code == 200
    assert client.get("/api/examples/clean").json()["report_id"] == "EVAL-01"
    assert client.get("/api/examples/.env").status_code == 404
    assert client.get("/.env").status_code == 403 or client.get("/.env").status_code == 404
    assert client.get("/api/jobs/not-a-uuid/result.json").status_code == 404
