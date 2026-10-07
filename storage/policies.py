"""Versioned policy embeddings; retrieval supplements the complete policy rules."""

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

from app.config import EndpointSettings, load_endpoint
from integrations.model_client import ModelClient
from storage.database import connection

RESOURCE_FILES = {
    "tripledger://policy/expense-policy": "expense-policy.md",
    "tripledger://policy/per-diem": "per-diem.json",
    "tripledger://reference/mcc-codes": "mcc-codes.json",
}


def resources() -> dict[str, str]:
    root = Path(
        os.getenv(
            "POLICY_RESOURCE_DIR", str(Path(__file__).resolve().parents[1] / "mcp_server/resources")
        )
    )
    return {uri: (root / name).read_text(encoding="utf-8") for uri, name in RESOURCE_FILES.items()}


def corpus_hash(values: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def profile(settings: EndpointSettings) -> str:
    # Hash endpoint identity without storing a potentially secret-bearing URL.
    value = [
        settings.url,
        settings.model,
        settings.dimensions,
        settings.input_field,
        settings.input_as_list,
        settings.vector_path,
        settings.extra_body,
    ]
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def chunks(values: dict[str, str]) -> list[dict[str, str]]:
    result = []
    for uri, content in sorted(values.items()):
        # Small bounded text chunks; full resources remain authoritative.
        for start in range(0, len(content), 1200):
            result.append(
                {
                    "id": hashlib.sha256(f"{uri}:{start}".encode()).hexdigest(),
                    "source_uri": uri,
                    "content": content[start : start + 1400],
                }
            )
    return result


def vector_literal(vector: list[float]) -> str:
    if not vector or any(not math.isfinite(x) for x in vector) or not any(vector):
        raise ValueError("Embedding must be finite and nonzero")
    return json.dumps(vector)


def index_policies() -> dict[str, Any]:
    values = resources()
    digest = corpus_hash(values)
    settings = load_endpoint("embedding")
    identity = profile(settings)
    rows = chunks(values)
    vectors = []
    with ModelClient(settings) as model:
        for row in rows:
            vector = model.embed(row["content"])["embedding"]
            vectors.append(vector_literal(vector))
    dimensions = {len(json.loads(v)) for v in vectors}
    if len(dimensions) != 1:
        raise ValueError("Embedding provider returned inconsistent dimensions")
    dimension = dimensions.pop()
    # Atomically replace the corpus only after every embedding is valid.
    with connection() as db:
        db.execute("SELECT pg_advisory_xact_lock(741852964)")
        db.execute("DELETE FROM policy_chunks")
        for row, vector in zip(rows, vectors, strict=True):
            db.execute(
                "INSERT INTO policy_chunks(id,source_uri,content,corpus_hash,embedding_profile,"
                "dimensions,embedding) VALUES(%s,%s,%s,%s,%s,%s,%s::vector)",
                (row["id"], row["source_uri"], row["content"], digest, identity, dimension, vector),
            )
    return {"chunks": len(rows), "dimensions": dimension, "corpus_hash": digest}


def search_policy(query: str, values: dict[str, str], limit: int = 4) -> dict[str, Any]:
    settings = load_endpoint("embedding")
    digest, identity = corpus_hash(values), profile(settings)
    with connection() as db:
        ready = db.execute(
            "SELECT count(*) AS count FROM policy_chunks "
            "WHERE corpus_hash=%s AND embedding_profile=%s",
            (digest, identity),
        ).fetchone()
    if ready["count"] != len(chunks(values)):
        raise ValueError("Policy index missing or stale; run python -m app.database index-policies")
    with ModelClient(settings) as model:
        embedded = model.embed(query)
    vector = vector_literal(embedded["embedding"])
    with connection() as db:
        rows = db.execute(
            "SELECT id,source_uri,content,embedding <=> %s::vector AS distance "
            "FROM policy_chunks WHERE corpus_hash=%s AND embedding_profile=%s AND dimensions=%s "
            "ORDER BY embedding <=> %s::vector,id LIMIT %s",
            (vector, digest, identity, embedded["dimensions"], vector, min(max(limit, 1), 8)),
        ).fetchall()
    if not rows:
        raise ValueError("Policy index dimension or version changed; re-index policies")
    return {
        "matches": rows,
        "usage": embedded["usage"],
        "corpus_hash": digest,
        "embedding_profile": identity,
    }
