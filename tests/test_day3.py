import asyncio
import json
import shutil
import threading
from pathlib import Path

import pytest
from pydantic import AnyUrl

from app.day3 import smoke, tool
from integrations.mcp_client import connect
from mcp_server.dispatch import execute
from mcp_server.matching import match_transactions, normalize_merchant
from mock_systems.seed_data import generate
from mock_systems.service import MockServer

ROOT = Path(__file__).resolve().parents[1]


def example():
    return json.loads((ROOT / "examples/match-request.json").read_text())


def test_uber_normalization_and_pair():
    assert normalize_merchant("UBER *TRIP HELP.UBER.CO") == normalize_merchant("UBER BV AMSTERDAM")
    result = match_transactions(**example())
    assert result["pairs"][0]["score"] == 1.0
    assert result["unmatched_lines"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("currency", "USD"),
        ("posted_date", "2026-05-01"),
        ("merchant_raw", "Different coffee shop"),
        ("amount", "100.00"),
    ],
)
def test_unrelated_records_not_candidates(field, value):
    data = example()
    data["transactions"][0][field] = value
    result = match_transactions(**data)
    assert result["pairs"] == []
    assert result["unmatched_lines"] == ["L2"]
    assert result["unmatched_transactions"] == ["TXN-00-022"]


def test_tip_delta_and_ambiguity_preserved():
    data = example()
    data["transactions"][0]["amount"] = "40.00"
    data["transactions"].append({**data["transactions"][0], "txn_id": "TXN-OTHER"})
    result = match_transactions(**data)
    assert len(result["pairs"]) == 2
    assert result["pairs"][0]["amount_delta"] == "1.60"


@pytest.mark.parametrize(
    "name,args",
    [
        ("get_employee", {"employee_id": 123}),
        ("get_employee", {"employee_id": "EMP-2231", "extra": True}),
        (
            "list_card_transactions",
            {"employee_id": "EMP-2231", "from": "2026-04-10", "to": "2026-04-01"},
        ),
        ("list_settled_lines", {"employee_id": "EMP-2231", "months": 13}),
        (
            "compute_totals",
            {
                "lines": [{"line_id": "L1", "amount": "-1", "currency": "EUR"}],
                "caps": [],
                "base_currency": "EUR",
            },
        ),
        ("read_receipt", {}),
        ("save_decision", {}),
    ],
)
def test_safe_invalid_input_envelopes(name, args):
    result = execute(name, args)
    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_ARGUMENTS"
    assert "retryable" in result["error"] and "hint" in result["error"]


def test_receipt_fixture_and_path_confinement():
    good = execute("read_receipt", {"file_path": "receipts/L1.json"})
    assert good["ok"] and good["data"]["total"] == "412.00"
    assert (
        execute("read_receipt", {"file_path": "../.env"})["error"]["code"]
        == "RECEIPT_PATH_NOT_ALLOWED"
    )
    assert (
        execute("read_receipt", {"file_path": "L1.jpg"})["error"]["code"]
        == "IMAGE_EXTRACTION_DEFERRED"
    )
    assert execute("unknown", {})["error"]["code"] == "UNKNOWN_TOOL"


def test_duplicate_match_ids_are_rejected():
    data = example()
    data["lines"].append(data["lines"][0])
    assert execute("match_transactions", data)["error"]["code"] == "INVALID_ARGUMENTS"


def test_all_nine_tools_over_real_stdio(tmp_path):
    servers = [
        MockServer(role, generate(), 0, tmp_path / "queue.sqlite3", fail_every=10, travel_delay=0)
        for role in ["card", "travel", "hr", "ledger"]
    ]
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {f"{s.role.upper()}_BASE_URL": f"http://127.0.0.1:{s.server_port}" for s in servers}
    env["FX_CACHE_PATH"] = str(tmp_path / "fx.sqlite3")
    try:
        result = asyncio.run(smoke(env))
        assert result["tool_count"] == 9 and result["resource_count"] == 3
        assert result["all_transaction_count"] == 30
        assert result["hotel_totals_from_resource"]["disallowed"] == "52.00"
        assert result["queued"]["queued"]
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


def test_resource_edit_changes_result_without_restart(tmp_path):
    target = tmp_path / "resources"
    shutil.copytree(ROOT / "mcp_server/resources", target)

    async def run():
        async with connect({"POLICY_RESOURCE_DIR": str(target)}) as session:

            async def total():
                resource = await session.read_resource(AnyUrl("tripledger://policy/per-diem"))
                data = json.loads(resource.contents[0].text)
                return await tool(
                    session,
                    "compute_totals",
                    {
                        "lines": [{"line_id": "L1", "amount": "412", "currency": "EUR"}],
                        "caps": [
                            {
                                "line_id": "L1",
                                "rule_id": "R-03",
                                "kind": "cap_excess",
                                "limit": data["cities"]["Milan"]["Consultant"]["hotel_nightly"],
                                "quantity": 3,
                            }
                        ],
                        "base_currency": "EUR",
                    },
                )

            assert (await total())["data"]["disallowed"] == "52.00"
            path = target / "per-diem.json"
            data = json.loads(path.read_text())
            data["cities"]["Milan"]["Consultant"]["hotel_nightly"] = "140.00"
            data["version"] = "test-updated"
            path.write_text(json.dumps(data))
            assert (await total())["data"]["disallowed"] == "0.00"

    asyncio.run(run())
