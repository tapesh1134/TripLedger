"""Environment-only credentials; independent chat and embedding endpoints."""

import json
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from dotenv import load_dotenv


@dataclass(frozen=True)
class EndpointSettings:
    url: str
    model: str
    api_key: str = field(repr=False)
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"
    timeout: float = 30
    retries: int = 3
    ca_bundle: str = ""
    temperature: float | None = None
    extra_body: dict[str, Any] = field(default_factory=dict)
    dimensions: int | None = None
    input_field: str = "input"
    input_as_list: bool = True
    vector_path: str = "data.0.embedding"

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise ValueError("configure a valid API URL")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("API URL must not contain credentials or a fragment")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("remote API endpoints require HTTPS")
        if not self.model or not self.api_key:
            raise ValueError("API model and API key are required")
        if not 0 <= self.retries <= 3 or not 0 < self.timeout <= 120:
            raise ValueError("use retries 0..3 and timeout 0..120 seconds")
        if self.temperature is not None and not 0 <= self.temperature <= 0.2:
            raise ValueError("temperature must be between 0 and 0.2, or blank")
        if self.dimensions is not None and self.dimensions < 1:
            raise ValueError("embedding dimensions must be positive")
        if self.extra_body.keys() & {
            "model",
            "messages",
            "tools",
            "stream",
            "temperature",
            "input",
            self.input_field,
            "dimensions",
        }:
            raise ValueError("extra body must not override core request fields")


def load_endpoint(kind: str) -> EndpointSettings:
    load_dotenv(override=False)
    prefix = "LLM" if kind == "llm" else "EMBEDDING"
    suffix = "chat/completions" if kind == "llm" else "embeddings"
    endpoint = os.getenv(f"{prefix}_ENDPOINT_URL", "").strip()
    base = os.getenv(f"{prefix}_BASE_URL", "").strip().rstrip("/")
    if not endpoint and not base:
        raise ValueError(f"set {prefix}_BASE_URL or {prefix}_ENDPOINT_URL in .env")
    extra = json.loads(os.getenv(f"{prefix}_EXTRA_BODY_JSON", "{}"))
    if not isinstance(extra, dict):
        raise ValueError(f"{prefix}_EXTRA_BODY_JSON must be a JSON object")
    temp = os.getenv("LLM_TEMPERATURE", "0.2").strip() if kind == "llm" else ""
    dimensions = os.getenv("EMBEDDING_DIMENSIONS", "").strip() if kind != "llm" else ""
    return EndpointSettings(
        url=endpoint or f"{base}/{suffix}",
        model=os.getenv(f"{prefix}_MODEL", "").strip(),
        api_key=os.getenv(f"{prefix}_API_KEY", "").strip(),
        auth_header=os.getenv(f"{prefix}_AUTH_HEADER", "Authorization"),
        auth_scheme=os.getenv(f"{prefix}_AUTH_SCHEME", "Bearer"),
        timeout=float(os.getenv("HTTP_TIMEOUT_SECONDS", "30")),
        retries=int(os.getenv("HTTP_MAX_RETRIES", "3")),
        ca_bundle=os.getenv("CA_BUNDLE", "").strip(),
        temperature=float(temp) if temp else None,
        extra_body=extra,
        dimensions=int(dimensions) if dimensions else None,
        input_field=os.getenv("EMBEDDING_INPUT_FIELD", "input"),
        input_as_list=os.getenv("EMBEDDING_INPUT_AS_LIST", "true").lower() == "true",
        vector_path=os.getenv("EMBEDDING_VECTOR_PATH", "data.0.embedding"),
    )
