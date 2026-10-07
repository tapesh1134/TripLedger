"""Focused checks for versioned retrieval and secret-safe database errors."""

import pytest

from app.config import EndpointSettings
from storage.database import StorageError, connection
from storage.policies import chunks, corpus_hash, profile, vector_literal


def test_policy_version_tracks_edits():
    values = {"policy://one": "a" * 2600, "policy://two": "cap 20"}
    rows = chunks(values)
    assert len({r["id"] for r in rows}) == len(rows)
    assert all(len(r["content"]) <= 1400 for r in rows)
    assert corpus_hash(values) == corpus_hash(dict(reversed(list(values.items()))))
    assert corpus_hash(values) != corpus_hash({**values, "policy://two": "cap 30"})


def test_profile_tracks_model_not_key():
    def config(model="one", key="secret"):
        return EndpointSettings(url="https://example.com/embeddings", model=model, api_key=key)

    assert profile(config()) == profile(config(key="rotated"))
    assert profile(config()) != profile(config(model="two"))


@pytest.mark.parametrize("value", [[], [0.0, 0.0], [float("nan")], [float("inf")]])
def test_invalid_vector(value):
    with pytest.raises(ValueError):
        vector_literal(value)


def test_database_error_hides_secrets(monkeypatch):
    import psycopg

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:private-password@localhost/db")

    def fail(*args, **kwargs):
        raise psycopg.OperationalError("private-password")

    monkeypatch.setattr(psycopg, "connect", fail)
    with pytest.raises(StorageError) as error:
        with connection():
            pass
    assert "private-password" not in str(error.value)


def test_agent_returns_incomplete_when_retrieval_unavailable(monkeypatch):
    import asyncio
    import json
    from pathlib import Path
    from types import SimpleNamespace

    from mcp import types

    from agent.loop import review
    from app.intake import intake
    from storage.policies import resources

    monkeypatch.setenv("POLICY_SEARCH_ENABLED", "true")

    def unavailable(*args, **kwargs):
        raise ValueError("stale index")

    monkeypatch.setattr("storage.policies.search_policy", unavailable)

    class Session:
        async def list_tools(self):
            return SimpleNamespace(tools=[])

        async def read_resource(self, uri):
            return SimpleNamespace(
                contents=[types.TextResourceContents(uri=uri, text=resources()[str(uri)])]
            )

    class Model:
        def complete(self, *args, **kwargs):
            pytest.fail("Chat should not run after required retrieval fails")

    report = intake(json.loads(Path("evals/reports/EVAL-01.json").read_text()))[0]
    result = asyncio.run(review(report, Session(), Model(), "test"))
    assert result["status"] == "incomplete"
    assert result["decision"]["reason"] == "POLICY_RETRIEVAL_UNAVAILABLE"
    assert result["queued"] is False
