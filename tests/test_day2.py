import json
import threading
from decimal import Decimal

import httpx
import pytest

from mcp_server.backend import Backend, BackendError, HttpAdapter
from mcp_server.fx import FxConverter
from mock_systems.seed_data import generate
from mock_systems.service import MockServer


@pytest.fixture
def services(tmp_path):
    data = generate()
    servers = [
        MockServer(role, data, 0, tmp_path / "queue.sqlite3", fail_every=10, travel_delay=0.001)
        for role in ["card", "travel", "hr", "ledger"]
    ]
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    yield servers
    for server in servers:
        server.shutdown()
        server.server_close()


def test_real_http_pagination_retry_and_queue(services, monkeypatch):
    monkeypatch.setattr("mcp_server.backend.time.sleep", lambda _: None)
    urls = {s.role: f"http://127.0.0.1:{s.server_port}" for s in services}
    backend = Backend(urls)
    try:
        assert backend.get_employee("EMP-2231")["grade"] == "Consultant"
        assert backend.get_trip("TRP-8890")["hotel_nights"] == 3
        first = backend.list_card_transactions("EMP-2231", "2026-04-07", "2026-04-14")
        assert len(first["items"]) == 20 and first["next_cursor"] == "20"
        assert not any(x["amount"] == "412.00" for x in first["items"])
        rows = backend.all_card_transactions("EMP-2231", "2026-04-07", "2026-04-14")
        assert len(rows) == 30
        assert any(x["amount"] == "412.00" for x in rows)
        for _ in range(12):
            backend.list_card_transactions("EMP-2231", "2026-04-07", "2026-04-14")
        assert backend.http.retry_count >= 1
        old = backend.list_settled_lines("EMP-2231")["items"]
        assert len(old) == 1 and old[0]["line_id"] != "OLD-EXPIRED"
        with open("examples/decision.json") as file:
            decision = json.load(file)
        first_save = backend.save_decision(decision)
        assert backend.save_decision(decision) == first_save
        assert len(backend.get("ledger", "/review-queue")["items"]) == 1
        decision["confidence"] = 0.5
        with pytest.raises(BackendError, match="409"):
            backend.save_decision(decision)
        with pytest.raises(BackendError, match="400"):
            backend.list_card_transactions("EMP-2231", "2026-04-07", "2026-04-14", "-1")
        with pytest.raises(BackendError, match="404"):
            backend.get_trip("missing")
        assert backend.get("card", "/transactions/TXN-00-021")["amount"] == "412.00"
        assert len(backend.get("travel", "/trips", {"employee_id": "EMP-2231"})["items"]) == 1
    finally:
        backend.close()


def test_fixture_counts_and_masking():
    data = generate()
    assert data == generate()
    assert len(data["employees"]) == 30
    assert len(data["trips"]) == 20
    assert len(data["transactions"]) == 600
    assert all(len(x["card_last4"]) == 4 for x in data["transactions"])
    assert all("card_number" not in x for x in data["transactions"])


@pytest.mark.parametrize("status,expected", [(429, 4), (503, 4), (403, 1), (404, 1)])
def test_retry_budget(status, expected, monkeypatch):
    monkeypatch.setattr("mcp_server.backend.time.sleep", lambda _: None)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(BackendError):
            HttpAdapter(client).request("GET", "https://example.test")
    assert len(calls) == expected


def test_timeout_retry(monkeypatch):
    monkeypatch.setattr("mcp_server.backend.time.sleep", lambda _: None)
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("synthetic timeout")
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert HttpAdapter(client).request("GET", "https://example.test")["ok"]
    assert len(calls) == 2


def test_fx_historical_decimal_cache(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path == "/v1/2026-04-09"
        assert request.url.params["base"] == "USD"
        assert request.url.params["symbols"] == "EUR"
        return httpx.Response(
            200, text='{"base":"USD","date":"2026-04-09","rates":{"EUR":0.92345}}'
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        converter = FxConverter(HttpAdapter(client), tmp_path / "fx.sqlite3")
        result = converter.convert("100", "USD", "EUR", "2026-04-09")
        assert result["amount"] == "92.35"
        assert result["rate"] == "0.92345"
        assert result["rate_date"] == "2026-04-09"
        assert not result["cached"] and "2026-04-09" in result["source"]
        # New converter instance must reuse the disk cache and use the new amount.
        second = FxConverter(HttpAdapter(client), tmp_path / "fx.sqlite3")
        assert second.convert("200", "USD", "EUR", "2026-04-09")["amount"] == "184.69"
        assert second.convert("200", "USD", "EUR", "2026-04-09")["cached"]
        assert len(calls) == 1
        assert Decimal(result["amount"]) == (Decimal("100") * Decimal(result["rate"])).quantize(
            Decimal(".01"), rounding="ROUND_HALF_UP"
        )


@pytest.mark.parametrize(
    "response",
    [
        {"base": "USD", "date": "2026-04-10", "rates": {"EUR": "0.9"}},
        {"base": "USD", "date": "2026-03-01", "rates": {"EUR": "0.9"}},
        {"base": "EUR", "date": "2026-04-09", "rates": {"EUR": "0.9"}},
        {"base": "USD", "date": "2026-04-09", "rates": {"EUR": "NaN"}},
        {"base": "USD", "date": "2026-04-09", "rates": {}},
    ],
)
def test_fx_rejects_bad_response(response, tmp_path):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response))
    ) as client:
        converter = FxConverter(HttpAdapter(client), tmp_path / "fx.sqlite3")
        with pytest.raises(BackendError, match="INVALID_HISTORICAL"):
            converter.convert("100", "USD", "EUR", "2026-04-09")


def test_fx_outage_never_invents_rate(tmp_path, monkeypatch):
    monkeypatch.setattr("mcp_server.backend.time.sleep", lambda _: None)
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as client:
        converter = FxConverter(HttpAdapter(client), tmp_path / "fx.sqlite3")
        with pytest.raises(BackendError) as error:
            converter.convert("100", "USD", "EUR", "2026-04-09")
        assert error.value.envelope()["error"]["retryable"]


def test_fx_identity_and_previous_working_date(tmp_path):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"base": "USD", "date": "2026-04-10", "rates": {"EUR": "0.9"}}
            )
        )
    ) as client:
        converter = FxConverter(HttpAdapter(client), tmp_path / "fx.sqlite3")
        identity = converter.convert("100", "EUR", "EUR", "2026-04-09")
        assert identity["amount"] == "100.00" and identity["rate"] == "1"
        result = converter.convert("100", "USD", "EUR", "2026-04-12")
        assert result["requested_date"] == "2026-04-12"
        assert result["rate_date"] == "2026-04-10"


def test_repeated_cursor_is_detected():
    page = {"items": [], "next_cursor": "20"}
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=page))
    ) as client:
        backend = Backend({"card": "https://example.test"}, HttpAdapter(client))
        with pytest.raises(BackendError, match="REPEATED"):
            backend.all_card_transactions("EMP-2231", "2026-04-07", "2026-04-14")
