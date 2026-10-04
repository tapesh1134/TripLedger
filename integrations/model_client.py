"""The provider-specific adapter: edit this file for a non-compatible API.

Chat contract: POST model/messages -> choices[0].message and usage.
Embeddings: configurable input field and response vector path.
No report data, keys, request/response bodies or URLs are logged.
"""

import json
import math
import random
import ssl
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.config import EndpointSettings


class ProviderError(RuntimeError):
    """Safe error message with no provider response body or secret-bearing URL."""


@dataclass(frozen=True)
class ModelResponse:
    message: dict[str, Any]
    usage: dict[str, Any]
    request_id: str


class ModelClient:
    def __init__(
        self,
        settings: EndpointSettings,
        transport: httpx.BaseTransport | None = None,
        usage_path: Path = Path("traces/usage.jsonl"),
    ) -> None:
        self.settings = settings
        self.usage_path = usage_path
        verify: bool | ssl.SSLContext = (
            ssl.create_default_context(cafile=settings.ca_bundle) if settings.ca_bundle else True
        )
        self.http = httpx.Client(
            timeout=settings.timeout, transport=transport, verify=verify, follow_redirects=False
        )

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> "ModelClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        auth = f"{self.settings.auth_scheme} {self.settings.api_key}".strip()
        for attempt in range(self.settings.retries + 1):
            try:
                response = self.http.post(
                    self.settings.url,
                    json=body,
                    headers={self.settings.auth_header: auth, "Content-Type": "application/json"},
                )
            except httpx.TimeoutException:
                if attempt == self.settings.retries:
                    raise ProviderError(
                        "API request timed out; check HTTP_TIMEOUT_SECONDS (maximum 120)"
                    ) from None
            except httpx.TransportError:
                if attempt == self.settings.retries:
                    raise ProviderError(
                        "API connection failed; check network, timeout and CA bundle"
                    ) from None
            else:
                if 200 <= response.status_code < 300:
                    try:
                        data: Any = response.json()
                    except ValueError:
                        raise ProviderError("API returned invalid JSON") from None
                    if not isinstance(data, dict):
                        raise ProviderError("API response must be a JSON object")
                    return data
                retryable = response.status_code == 429 or 500 <= response.status_code <= 599
                if not retryable or attempt == self.settings.retries:
                    hints = {
                        401: "check API key and authentication header",
                        403: "check model access and gateway authorization",
                        404: "check the exact endpoint URL and model name",
                        400: "check the provider request format and supported parameters",
                        429: "rate limit reached; try again later",
                    }
                    hint = hints.get(response.status_code, "check provider availability")
                    raise ProviderError(f"API HTTP {response.status_code}: {hint}")
            time.sleep(min(2**attempt, 8) + random.uniform(0, 0.2))
        raise ProviderError("API retry budget exhausted")

    def _usage(self, data: dict[str, Any], kind: str, started: float) -> tuple[str, dict[str, Any]]:
        raw = data.get("usage")
        usage = raw if isinstance(raw, dict) else {}

        def count(primary: str, alternate: str = "") -> int | None:
            value = usage.get(primary, usage.get(alternate))
            return value if type(value) is int and value >= 0 else None

        request_id = str(uuid4())
        record = {
            "request_id": request_id,
            "kind": kind,
            "created_at": datetime.now(UTC).isoformat(),
            "tokens_in": count("prompt_tokens", "input_tokens"),
            "tokens_out": count("completion_tokens", "output_tokens"),
            "tokens_total": count("total_tokens"),
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
        self.usage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.usage_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record) + "\n")
        return request_id, record

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> ModelResponse:
        started = time.perf_counter()
        body: dict[str, Any] = {
            **self.settings.extra_body,
            "model": self.settings.model,
            "messages": messages,
            "stream": False,
        }
        if self.settings.temperature is not None:
            body["temperature"] = self.settings.temperature
        if tools:
            body["tools"] = tools
        data = self._post(body)
        try:
            message = data["choices"][0]["message"]
            if not isinstance(message, dict):
                raise TypeError
            if not isinstance(message.get("content"), str) and not message.get("tool_calls"):
                raise TypeError
        except (KeyError, IndexError, TypeError):
            raise ProviderError("expected choices[0].message with content or tool_calls") from None
        request_id, usage = self._usage(data, "llm", started)
        return ModelResponse(message=message, usage=usage, request_id=request_id)

    def embed(self, text: str) -> dict[str, Any]:
        started = time.perf_counter()
        body: dict[str, Any] = {
            **self.settings.extra_body,
            "model": self.settings.model,
            self.settings.input_field: [text] if self.settings.input_as_list else text,
        }
        if self.settings.dimensions is not None:
            body["dimensions"] = self.settings.dimensions
        data = self._post(body)
        try:
            vector: Any = data
            for key in self.settings.vector_path.split("."):
                vector = vector[int(key)] if isinstance(vector, list) else vector[key]
            if not isinstance(vector, list) or not vector:
                raise ValueError
            if any(type(x) not in (int, float) or not math.isfinite(x) for x in vector):
                raise ValueError
            if self.settings.dimensions is not None and len(vector) != self.settings.dimensions:
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError, OverflowError):
            raise ProviderError(
                "invalid embedding vector; check vector path and dimensions"
            ) from None
        request_id, usage = self._usage(data, "embedding", started)
        return {
            "embedding": vector,
            "dimensions": len(vector),
            "usage": usage,
            "request_id": request_id,
        }
