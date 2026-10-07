"""Opt-in integration checks; each test creates and removes only its own schema.

Set TEST_DATABASE_URL to a disposable database with pgvector installed.
"""

import json
import os
import time
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.database import initialize, seed
from mcp_server.backend import Backend, BackendError
from storage.database import StorageError, connection
from storage.jobs import PostgresJobStore
from storage.policies import index_policies, resources, search_policy

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def database(monkeypatch):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL for isolated PostgreSQL integration tests")
    schema = "test_" + uuid4().hex
    with psycopg.connect(url, autocommit=True) as db:
        db.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
        db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    monkeypatch.setenv("DATABASE_URL", make_conninfo(url, options=f"-csearch_path={schema},public"))
    monkeypatch.setenv("POLICY_SEARCH_ENABLED", "false")
    initialize()
    seed(ROOT / "mock_systems/seed/evaluation-data.json")
    try:
        yield
    finally:
        with psycopg.connect(url, autocommit=True) as db:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_evidence_and_pagination(database):
    backend = Backend()
    try:
        assert backend.get_employee("EVAL-EMP-24")["employee_id"] == "EVAL-EMP-24"
        page = backend.list_card_transactions("EVAL-EMP-24", "2026-04-01", "2026-04-30")
        assert len(page["items"]) == 20 and page["next_cursor"] == "20"
        second = backend.list_card_transactions("EVAL-EMP-24", "2026-04-01", "2026-04-30", "20")
        assert second["next_cursor"] is None
        assert any(x["txn_id"] == "TX-EVAL-24-20" for x in second["items"])
        assert backend.get_trip("EVAL-TRP-01")["employee_id"] == "EVAL-EMP-01"
        assert "items" in backend.list_settled_lines("EVAL-EMP-01")
        with pytest.raises(BackendError):
            backend.get_employee("missing")
    finally:
        backend.close()


def test_job_persistence(database, tmp_path):
    def runner(report):
        return {
            "status": "incomplete",
            "decision": {"reason": "EXAMPLE"},
            "queued": False,
            "trace": {"steps": []},
        }

    store = PostgresJobStore(tmp_path, runner)
    report = json.loads((ROOT / "evals/reports/EVAL-01.json").read_text())
    try:
        job = store.submit(report)
        deadline = time.monotonic() + 10
        while store.get(job["id"])["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert store.get(job["id"])["status"] == "incomplete"
        assert json.loads(store.artifact(job["id"], "trace.json"))["steps"] == []
        with connection() as db:
            row = db.execute("SELECT report FROM review_jobs WHERE id=%s", (job["id"],)).fetchone()
            assert row["report"]["report_id"] == "EVAL-01"
    finally:
        store.close()
    reopened = PostgresJobStore(tmp_path, runner)
    try:
        assert reopened.list()[0]["id"] == job["id"]
        assert json.loads(reopened.artifact(job["id"], "result.json"))["queued"] is False
    finally:
        reopened.close()


def test_dashboard_lock(database, tmp_path):
    store = PostgresJobStore(tmp_path)
    try:
        with pytest.raises(StorageError):
            PostgresJobStore(tmp_path / "other")
    finally:
        store.close()


def test_vector_search_stale_index(database, monkeypatch):
    monkeypatch.setenv("EMBEDDING_ENDPOINT_URL", "https://example.com/embeddings")
    monkeypatch.setenv("EMBEDDING_API_KEY", "test")
    monkeypatch.setenv("EMBEDDING_MODEL", "test-vector")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "3")

    def embed(self, text):
        return {
            "embedding": [1.0, float("receipt" in text.lower()), 0.25],
            "dimensions": 3,
            "usage": {"tokens_in": 2, "tokens_out": None},
        }

    monkeypatch.setattr("storage.policies.ModelClient.embed", embed)
    assert index_policies()["chunks"] > 0
    result = search_policy("receipt", resources(), 2)
    assert len(result["matches"]) == 2
    assert all(r["source_uri"] in resources() for r in result["matches"])
    changed = {**resources(), "tripledger://policy/expense-policy": "changed"}
    with pytest.raises(ValueError, match="stale"):
        search_policy("receipt", changed)
    monkeypatch.setenv("EMBEDDING_MODEL", "new-model")
    with pytest.raises(ValueError, match="stale"):
        search_policy("receipt", resources())


def test_queue_idempotency_conflict(database):
    value = json.loads((ROOT / "examples/decision.json").read_text())
    backend = Backend()
    try:
        first = backend.save_decision(value)
        assert backend.save_decision(value) == first
        value["confidence"] = 0.5
        with pytest.raises(BackendError, match="DECISION_CONFLICT"):
            backend.save_decision(value)
        with connection() as db:
            assert db.execute("SELECT count(*) AS n FROM review_decisions").fetchone()["n"] == 1
    finally:
        backend.close()


def test_agent_uses_sql_evidence_through_mcp(database, monkeypatch):
    import asyncio

    from test_agent import ScriptedModel, load_report

    from agent.loop import review
    from integrations.mcp_client import connect

    monkeypatch.setenv("EMBEDDING_ENDPOINT_URL", "https://example.com/embeddings")
    monkeypatch.setenv("EMBEDDING_API_KEY", "test")
    monkeypatch.setenv("EMBEDDING_MODEL", "test-vector")
    monkeypatch.setenv("EMBEDDING_DIMENSIONS", "3")
    monkeypatch.setenv("POLICY_SEARCH_ENABLED", "true")

    def embed(self, text):
        return {
            "embedding": [1.0, 0.5, 0.25],
            "dimensions": 3,
            "usage": {"tokens_in": 2, "tokens_out": None},
        }

    monkeypatch.setattr("storage.policies.ModelClient.embed", embed)
    index_policies()

    async def run():
        report = load_report(1)
        async with connect() as session:
            return await review(report, session, ScriptedModel(report), "scripted")

    result = asyncio.run(run())
    assert result["status"] == "complete"
    assert result["decision"]["decision"] == "auto_approve"
    assert result["decision"]["reimbursable_total"] == {"amount": "20.00", "currency": "EUR"}
    assert result["trace"]["policy_retrieval"]["matches"]


def test_recover_interrupted_job(database, tmp_path):
    with connection() as db:
        db.execute(
            "INSERT INTO review_jobs(id,report_id,status,created_at,report,job) "
            "VALUES ('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','old','running',now(),'{}',"
            '\'{"id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","status":"running"}\')'
        )
    store = PostgresJobStore(tmp_path)
    try:
        job = store.get("a" * 32)
        assert job["status"] == "interrupted"
        assert "finished_at" in job
    finally:
        store.close()
