"""Historical FX using Frankfurter v1; exact decimal computation and SQLite cache."""

import hashlib
import os
import re
import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from mcp_server.backend import BackendError, HttpAdapter
from mcp_server.tools_compute import money


class FxConverter:
    def __init__(
        self,
        adapter: HttpAdapter | None = None,
        cache: Path | None = None,
        base_url: str | None = None,
    ):
        load_dotenv()
        self.http = adapter or HttpAdapter()
        self.base_url = (
            base_url or os.getenv("FX_BASE_URL") or "https://api.frankfurter.dev/v1"
        ).rstrip("/")
        self.cache = cache or Path(os.getenv("FX_CACHE_PATH", "runtime/fx-cache.sqlite3"))
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.cache) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS rates (provider TEXT, base TEXT, quote TEXT, "
                "requested TEXT, rate TEXT, rate_date TEXT, source TEXT, fetched_at TEXT, "
                "PRIMARY KEY(provider, base, quote, requested))"
            )

    def close(self) -> None:
        self.http.close()

    def convert(self, amount: str, from_ccy: str, to_ccy: str, on_date: str) -> dict[str, Any]:
        try:
            value = Decimal(str(amount))
            requested = date.fromisoformat(on_date)
            if not value.is_finite() or not 0 <= value <= Decimal("999999999999.99"):
                raise ValueError
            if any(not re.fullmatch("[A-Z]{3}", c) for c in (from_ccy, to_ccy)):
                raise ValueError
            if requested >= datetime.now(UTC).date():
                raise ValueError
        except (ValueError, InvalidOperation):
            raise BackendError("INVALID_FX_INPUT_USE_PAST_DATE_AND_NONNEGATIVE_AMOUNT") from None
        cached = False
        if from_ccy == to_ccy:
            rate, rate_date, source = Decimal("1"), on_date, "identity:no-conversion"
        else:
            key = (self.base_url, from_ccy, to_ccy, on_date)
            with sqlite3.connect(self.cache) as db:
                row = db.execute(
                    "SELECT rate, rate_date, source FROM rates WHERE "
                    "provider=? AND base=? AND quote=? AND requested=?",
                    key,
                ).fetchone()
            if row:
                rate, rate_date, source = Decimal(row[0]), row[1], row[2]
                cached = True
            else:
                data = self.http.request(
                    "GET",
                    self.base_url + "/" + on_date,
                    params={"base": from_ccy, "symbols": to_ccy},
                )
                try:
                    rate = Decimal(str(data["rates"][to_ccy]))
                    rate_date = data["date"]
                    if data["base"] != from_ccy or not rate.is_finite() or rate <= 0:
                        raise ValueError
                    effective = date.fromisoformat(rate_date)
                    # Historical snapshots may use the preceding working day; never a future rate.
                    if effective > requested or (requested - effective).days > 7:
                        raise ValueError
                except (KeyError, TypeError, ValueError, InvalidOperation):
                    raise BackendError("INVALID_HISTORICAL_FX_RESPONSE") from None
                source = f"{self.base_url}/{on_date}?base={from_ccy}&symbols={to_ccy}"
                with sqlite3.connect(self.cache) as db:
                    db.execute(
                        "INSERT OR REPLACE INTO rates VALUES (?,?,?,?,?,?,?,?)",
                        (*key, str(rate), rate_date, source, datetime.now(UTC).isoformat()),
                    )
        try:
            if (
                not rate.is_finite()
                or rate <= 0
                or not 0 <= (requested - date.fromisoformat(rate_date)).days <= 7
            ):
                raise ValueError
            with localcontext() as ctx:
                ctx.prec = 50
                converted = money(value * rate)
        except (ValueError, InvalidOperation):
            raise BackendError("INVALID_FX_RATE") from None
        return {
            "amount": str(converted),
            "from_ccy": from_ccy,
            "to_ccy": to_ccy,
            "input_amount": str(value),
            "rate": str(rate),
            "requested_date": on_date,
            "rate_date": rate_date,
            "source": source,
            "cached": cached,
            "calc_id": "FX-"
            + hashlib.sha256(
                f"{value}|{from_ccy}|{to_ccy}|{on_date}|{rate}|{source}".encode()
            ).hexdigest()[:16],
        }


def fx_convert(amount: str, from_ccy: str, to_ccy: str, on_date: str) -> dict[str, Any]:
    converter = FxConverter()
    try:
        return converter.convert(amount, from_ccy, to_ccy, on_date)
    finally:
        converter.close()
