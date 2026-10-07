"""Ordinary tests never use the developer's database or embedding credentials."""

import pytest


@pytest.fixture(autouse=True)
def isolated_storage_settings(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("POLICY_SEARCH_ENABLED", "false")
