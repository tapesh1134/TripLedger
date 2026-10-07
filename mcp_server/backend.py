"""SQL evidence with an optional legacy HTTP backend; no model credentials."""

import json
import logging
import os
import random
import time
from decimal import Decimal
from typing import Any
from urllib.parse import quote

import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class BackendError(RuntimeError):
    def __init__(self, code: str, retryable: bool = False):
        self.code, self.retryable = code, retryable
        super().__init__(code)

    def envelope(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": str(self),
                "retryable": self.retryable,
                "hint": "Do not invent missing evidence or FX rates; escalate incomplete reviews.",
            },
        }


class HttpAdapter:
    def __init__(
        self,
        client: httpx.Client | None = None,
        retries: int = 3,
        backoff: float = 0.25,
        trust_env: bool = True,
    ):
        if not 0 <= retries <= 3 or backoff < 0:
            raise ValueError("invalid retry settings")
        self.client = client or httpx.Client(
            timeout=10, follow_redirects=False, trust_env=trust_env
        )
        self.owned = client is None
        self.retries, self.backoff = retries, backoff
        self.retry_count = 0

    def close(self) -> None:
        if self.owned:
            self.client.close()

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        for attempt in range(self.retries + 1):
            response = None
            try:
                response = self.client.request(method, url, **kwargs)
            except httpx.TransportError:
                error = BackendError("NETWORK_UNAVAILABLE", True)
            else:
                if 200 <= response.status_code < 300:
                    try:
                        return json.loads(response.text, parse_float=Decimal)
                    except ValueError:
                        raise BackendError("INVALID_UPSTREAM_JSON") from None
                retryable = response.status_code == 429 or 500 <= response.status_code < 600
                error = BackendError(f"UPSTREAM_HTTP_{response.status_code}", retryable)
                if not retryable:
                    raise error
            if attempt == self.retries:
                raise error
            self.retry_count += 1
            delay = self.backoff * (2**attempt) + random.uniform(0, self.backoff / 4)
            if response is not None:
                try:
                    delay = max(delay, min(10, float(response.headers.get("Retry-After", "0"))))
                except ValueError:
                    pass
            logger.info("upstream_retry attempt=%d code=%s", attempt + 1, error.code)
            time.sleep(delay)
        raise BackendError("RETRY_EXHAUSTED", True)


class Backend:
    def __init__(self, urls: dict[str, str] | None = None, adapter: HttpAdapter | None = None):
        load_dotenv()
        from storage.business import BusinessStore
        from storage.database import database_url

        self.store = (
            BusinessStore() if database_url() and urls is None and adapter is None else None
        )
        self.urls = urls or {
            role: os.getenv(f"{role.upper()}_BASE_URL", f"http://127.0.0.1:{port}")
            for role, port in [("card", 8011), ("travel", 8012), ("hr", 8013), ("ledger", 8014)]
        }
        self.http = adapter or HttpAdapter(trust_env=False)

    def close(self) -> None:
        self.http.close()

    def get(self, role: str, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.http.request("GET", self.urls[role].rstrip("/") + path, params=params)

    def get_employee(self, employee_id: str) -> Any:
        if self.store is not None:
            return self.store.get_employee(employee_id)
        return self.get("hr", "/employees/" + quote(employee_id, safe=""))

    def get_trip(self, trip_id: str) -> Any:
        if self.store is not None:
            return self.store.get_trip(trip_id)
        return self.get("travel", "/trips/" + quote(trip_id, safe=""))

    def list_card_transactions(
        self, employee_id: str, start: str, end: str, cursor: str | None = None
    ) -> dict[str, Any]:
        if self.store is not None:
            return self.store.list_card_transactions(employee_id, start, end, cursor)
        params = {"employee_id": employee_id, "from": start, "to": end}
        if cursor is not None:
            params["cursor"] = cursor
        page = self.get("card", "/transactions", params)
        if not isinstance(page, dict) or not isinstance(page.get("items"), list):
            raise BackendError("INVALID_CARD_PAGE")
        if "next_cursor" not in page or (
            page["next_cursor"] is not None and not isinstance(page["next_cursor"], str)
        ):
            raise BackendError("INVALID_CARD_CURSOR")
        return page

    def all_card_transactions(self, employee_id: str, start: str, end: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor = None
        seen: set[str] = set()
        for _ in range(100):
            page = self.list_card_transactions(employee_id, start, end, cursor)
            items.extend(page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                return items
            if cursor in seen:
                raise BackendError("REPEATED_PAGINATION_CURSOR")
            seen.add(cursor)
        raise BackendError("PAGINATION_BUDGET_EXHAUSTED")

    def list_settled_lines(self, employee_id: str, months: int = 12) -> Any:
        if self.store is not None:
            return self.store.list_settled_lines(employee_id, months)
        return self.get("ledger", "/settled-lines", {"employee_id": employee_id, "months": months})

    def save_decision(self, decision: dict[str, Any]) -> Any:
        if self.store is not None:
            return self.store.save_decision(decision)
        return self.http.request(
            "POST", self.urls["ledger"].rstrip("/") + "/review-queue", json=decision
        )
