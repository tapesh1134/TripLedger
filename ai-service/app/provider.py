import json
import math
import ssl
import time
import httpx
from .config import env


class ProviderError(RuntimeError):
    pass


def client(timeout=120, *, trust_env=True):
    ca = env("CA_BUNDLE")
    verify = ssl.create_default_context(cafile=ca) if ca else True
    return httpx.Client(
        timeout=timeout, verify=verify, follow_redirects=False, trust_env=trust_env
    )


def call(prefix, body, suffix):
    endpoint = env(prefix + "_ENDPOINT_URL")
    if not endpoint:
        endpoint = env(prefix + "_BASE_URL").rstrip("/") + "/" + suffix
    if not endpoint.startswith(("https://", "http://127.0.0.1:", "http://localhost:")):
        raise ProviderError("Configure a valid provider endpoint")
    key = env(prefix + "_API_KEY")
    headers = {
        env(prefix + "_AUTH_HEADER", "Authorization"): (
            env(prefix + "_AUTH_SCHEME", "Bearer") + " " + key
        ).strip()
    }
    try:
        extra = json.loads(env(prefix + "_EXTRA_BODY_JSON", "{}"))
        if not isinstance(extra, dict):
            raise ValueError()
        body = {**extra, **body}
    except ValueError:
        raise ProviderError("Invalid provider extra JSON") from None
    for attempt in range(3):
        try:
            with client(int(env("HTTP_TIMEOUT_SECONDS", "120"))) as http:
                response = http.post(endpoint, headers=headers, json=body)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2**attempt)
                continue
            if not response.is_success:
                raise ProviderError(
                    f"{prefix} provider returned HTTP {response.status_code}; check endpoint, model access and credentials"
                )
            return response.json()
        except (httpx.HTTPError, ValueError):
            if attempt == 2:
                raise ProviderError(
                    f"{prefix} provider connection or JSON response failed"
                ) from None
            time.sleep(2**attempt)


def embedding(text):
    body = {
        "model": env("EMBEDDING_MODEL"),
        env("EMBEDDING_INPUT_FIELD", "input"): (
            [text] if env("EMBEDDING_INPUT_AS_LIST", "true").lower() == "true" else text
        ),
    }
    if env("EMBEDDING_DIMENSIONS"):
        body["dimensions"] = int(env("EMBEDDING_DIMENSIONS"))
    value = call("EMBEDDING", body, "embeddings")
    try:
        for key in env("EMBEDDING_VECTOR_PATH", "data.0.embedding").split("."):
            value = value[int(key)] if isinstance(value, list) else value[key]
        if not isinstance(value, list) or not value or len(value) > 16000:
            raise ValueError()
        vector = [float(x) for x in value]
        if not all(math.isfinite(x) for x in vector) or not any(vector):
            raise ValueError()
        return vector
    except (KeyError, IndexError, TypeError, ValueError):
        raise ProviderError("Embedding response path or vector is invalid") from None


def chat(messages, tools=None, vision=False):
    body = {
        "model": (
            env("VISION_MODEL") or env("LLM_MODEL") if vision else env("LLM_MODEL")
        ),
        "messages": messages,
    }
    if env("LLM_TEMPERATURE"):
        body["temperature"] = float(env("LLM_TEMPERATURE"))
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    response = call("LLM", body, "chat/completions")
    try:
        return response["choices"][0]["message"], response.get("usage", {})
    except (KeyError, TypeError, IndexError):
        raise ProviderError("Chat response must contain choices[0].message") from None


def parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)
