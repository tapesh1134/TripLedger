import json
from .config import env
from .database import connect, query
from .provider import embedding


def index_policy(policy):
    text = (
        policy["content"]
        + "\nEnforced structured rules:\n"
        + json.dumps(policy["rules"])
    )
    chunks = [text[i : i + 1500] for i in range(0, len(text), 1300)]
    vectors = [embedding(chunk) for chunk in chunks]
    if len({len(v) for v in vectors}) != 1:
        raise ValueError("Embedding dimensions changed during indexing")
    with connect() as c:
        query(c, "SELECT pg_advisory_xact_lock(hashtext(%s))", (str(policy["id"]),))
        query(c, "DELETE FROM policy_chunks WHERE policy_id=%s", (str(policy["id"]),))
        for number, (chunk, vector) in enumerate(zip(chunks, vectors)):
            query(
                c,
                "INSERT INTO policy_chunks VALUES (%s,%s,%s,%s,%s::vector)",
                (
                    str(policy["id"]),
                    f"POLICY-{number+1}",
                    chunk,
                    env("EMBEDDING_MODEL"),
                    json.dumps(vector),
                ),
            )
    return {"chunks": len(chunks), "dimensions": len(vectors[0])}


def search(policy_id, text):
    vector = embedding(text)
    with connect() as c:
        rows = query(
            c,
            """SELECT chunk_id,content,1-(embedding <=> %s::vector) AS score
            FROM policy_chunks WHERE policy_id=%s AND model=%s AND vector_dims(embedding)=%s
            ORDER BY embedding <=> %s::vector LIMIT 5""",
            (
                json.dumps(vector),
                str(policy_id),
                env("EMBEDDING_MODEL"),
                len(vector),
                json.dumps(vector),
            ),
        )
    if not rows:
        raise ValueError(
            "Policy index is missing or embedding configuration changed; republish the policy"
        )
    return rows
