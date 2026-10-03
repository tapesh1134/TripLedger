import json

import httpx
import pytest

from app.config import EndpointSettings
from integrations.model_client import ModelClient, ProviderError


def settings(**kwargs):
    return EndpointSettings(
        url="https://provider.example/custom/chat",
        model="demo",
        api_key="synthetic-test-key",
        **kwargs,
    )


def test_chat_request_and_safe_usage_log(tmp_path):
    def handler(request):
        assert str(request.url) == "https://provider.example/custom/chat"
        assert request.headers["Authorization"] == "Bearer synthetic-test-key"
        body = json.loads(request.content)
        assert body["model"] == "demo"
        assert "temperature" not in body
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ready"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
            },
        )

    usage_path = tmp_path / "usage.jsonl"
    with ModelClient(settings(), httpx.MockTransport(handler), usage_path) as client:
        response = client.complete([{"role": "user", "content": "synthetic hello"}])
    assert response.usage["tokens_total"] == 9
    logged = usage_path.read_text()
    assert "synthetic-test-key" not in logged
    assert "synthetic hello" not in logged


def test_retry_429_then_success(tmp_path, monkeypatch):
    monkeypatch.setattr("integrations.model_client.time.sleep", lambda _: None)
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    with ModelClient(settings(), httpx.MockTransport(handler), tmp_path / "usage") as client:
        result = client.complete([])
    assert len(calls) == 2
    assert result.usage["tokens_total"] is None  # Do not invent counts.


def test_403_not_retried_or_leaked(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(403, text="confidential gateway body")

    with ModelClient(settings(), httpx.MockTransport(handler), tmp_path / "usage") as client:
        with pytest.raises(ProviderError, match="403") as error:
            client.complete([])
    assert len(calls) == 1
    assert "confidential" not in str(error.value)


def test_custom_embedding_shape(tmp_path):
    def handler(request):
        assert request.headers["api-key"] == "synthetic-test-key"
        assert json.loads(request.content)["inputText"] == "test"
        return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})

    config = settings(
        auth_header="api-key",
        auth_scheme="",
        input_field="inputText",
        input_as_list=False,
        vector_path="embedding",
        dimensions=3,
    )
    with ModelClient(config, httpx.MockTransport(handler), tmp_path / "usage") as client:
        result = client.embed("test")
    assert result["dimensions"] == 3


def test_standard_embedding_shape(tmp_path):
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200, json={"data": [{"embedding": [0.1, 0.2]}], "usage": {"prompt_tokens": 1}}
        )
    )
    with ModelClient(settings(), transport, tmp_path / "usage") as client:
        result = client.embed("test")
    assert result["dimensions"] == 2


def test_malformed_chat_response(tmp_path):
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"wrong": True}))
    with ModelClient(settings(), transport, tmp_path / "usage") as client:
        with pytest.raises(ProviderError, match="choices"):
            client.complete([])


def test_retry_budget_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr("integrations.model_client.time.sleep", lambda _: None)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    with ModelClient(settings(), httpx.MockTransport(handler), tmp_path / "usage") as client:
        with pytest.raises(ProviderError, match="503"):
            client.complete([])
    assert len(calls) == 4  # Initial request plus three retries.
