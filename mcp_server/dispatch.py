"""Public schema validation, errors and tool execution for the stdio server."""

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import jsonschema
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from mcp_server.backend import Backend, BackendError
from mcp_server.fx import fx_convert
from mcp_server.matching import match_transactions
from mcp_server.schemas import ComputeRequest, Decision
from mcp_server.tool_contracts import (
    CardArgs,
    EmployeeArgs,
    FxArgs,
    MatchArgs,
    Receipt,
    ReceiptArgs,
    SettledArgs,
    TripArgs,
)
from mcp_server.tools_compute import compute_totals
from storage.database import StorageError

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS: dict[str, tuple[type[BaseModel], str]] = {
    "get_employee": (EmployeeArgs, "Fetch synthetic HR grade, manager and cost centre."),
    "get_trip": (TripArgs, "Fetch booked city, dates, flights and hotel nights."),
    "list_card_transactions": (
        CardArgs,
        "Fetch one page (20 rows). Follow next_cursor until null.",
    ),
    "list_settled_lines": (
        SettledArgs,
        "Fetch prior settled claims for duplicate checking, up to 12 months.",
    ),
    "read_receipt": (
        ReceiptArgs,
        "Read JSON or PNG/JPEG receipt under receipts/. Images use opt-in custom API vision.",
    ),
    "fx_convert": (
        FxArgs,
        "Convert with a dated historical rate; returns source and rate_date. Never invent a rate.",
    ),
    "compute_totals": (
        ComputeRequest,
        "Exact decimal totals, supplied caps, excess versus whole-line disallowance.",
    ),
    "match_transactions": (
        MatchArgs,
        "Score candidate pairs using merchant, date and amount. Does not decide matches.",
    ),
    "save_decision": (
        Decision,
        "Store a schema-valid decision in the review queue only. Never pays money.",
    ),
}


def error(code: str, message: str, hint: str, retryable: bool = False) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {"code": code, "message": message, "retryable": retryable, "hint": hint},
    }


def read_receipt(file_path: str) -> dict[str, Any]:
    load_dotenv()
    root = Path(os.getenv("RECEIPT_ROOT", str(ROOT / "receipts"))).resolve()
    candidate = Path(file_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise BackendError("RECEIPT_PATH_NOT_ALLOWED")
    # Both L1.json and receipts/L1.json are convenient public forms.
    if candidate.parts and candidate.parts[0] == "receipts":
        candidate = Path(*candidate.parts[1:])
    path = (root / candidate).resolve()
    if not path.is_relative_to(root):
        raise BackendError("RECEIPT_PATH_NOT_ALLOWED")
    if path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        from integrations.receipt_vision import extract_receipt

        result = extract_receipt(path)
        if result["ok"]:
            return {**result["data"], "ref": candidate.as_posix()}
        return result
    if path.suffix.lower() != ".json":
        return error(
            "UNSUPPORTED_RECEIPT_FORMAT",
            "Use JSON, PNG or JPEG.",
            "PDF and other formats are not supported.",
        )
    if not path.is_file():
        raise BackendError("RECEIPT_NOT_FOUND")
    if path.stat().st_size > 100_000:
        raise BackendError("RECEIPT_TOO_LARGE")
    receipt = Receipt.model_validate_json(path.read_bytes())
    if receipt.tax > receipt.total:
        return error(
            "RECEIPT_EXTRACTION_INVALID",
            "Receipt tax exceeds total.",
            "Review the receipt manually.",
        )
    return {
        **receipt.model_dump(mode="json"),
        "source": "synthetic-json-fixture",
        "ref": candidate.as_posix(),
    }


def execute(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in CONTRACTS:
        return error("UNKNOWN_TOOL", "Tool name is not registered.", "Discover tools/list first.")
    model = CONTRACTS[name][0]
    try:
        # We validate explicitly so invalid arguments use the same safe error envelope.
        jsonschema.validate(arguments, model.model_json_schema(by_alias=True))
        request = model.model_validate(arguments)
        data = request.model_dump(mode="json", by_alias=True)
        if name == "read_receipt":
            result = read_receipt(data["file_path"])
            if result.get("ok") is False:
                return result
        elif name == "fx_convert":
            result = fx_convert(**data)
        elif name == "compute_totals":
            result = compute_totals(**data)
            result["calc_id"] = (
                "CALC-" + hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]
            )
        elif name == "match_transactions":
            result = match_transactions(**data)
        else:
            backend = Backend()
            try:
                if name == "get_employee":
                    result = backend.get_employee(data["employee_id"])
                elif name == "get_trip":
                    result = backend.get_trip(data["trip_id"])
                elif name == "list_card_transactions":
                    result = backend.list_card_transactions(
                        data["employee_id"], data["from"], data["to"], data["cursor"]
                    )
                elif name == "list_settled_lines":
                    result = backend.list_settled_lines(data["employee_id"], data["months"])
                else:
                    result = backend.save_decision(data)
            finally:
                backend.close()
        return {"ok": True, "data": result}
    except (ValidationError, jsonschema.ValidationError):
        return error(
            "INVALID_ARGUMENTS",
            "Arguments do not match the published schema.",
            "Check required fields, types, date ranges and constraints; values are not logged.",
        )
    except BackendError as exc:
        return exc.envelope()
    except StorageError:
        return error(
            "DATABASE_UNAVAILABLE",
            "PostgreSQL is unavailable.",
            "Check DATABASE_URL and run database setup.",
            True,
        )
    except (OSError, sqlite3.Error):
        return error(
            "LOCAL_STORAGE_ERROR",
            "Receipt, cache or storage is unavailable.",
            "Check configured paths and permissions.",
        )
    except ValueError:
        return error(
            "INVALID_ARGUMENTS",
            "The requested calculation or input is invalid.",
            "Check currency consistency, duplicate IDs, amounts and cap references.",
        )
    except Exception:
        # Do not allow the SDK to serialize a raw exception containing credentials or data.
        return error(
            "INTERNAL_ERROR",
            "Tool execution failed.",
            "Check local configuration; do not guess evidence.",
        )
