from contextlib import contextmanager
from urllib.parse import urlsplit, unquote
import pg8000.dbapi
from .config import env


@contextmanager
def connect():
    url = urlsplit(env("AI_DATABASE_URL"))
    if url.scheme not in ("postgresql", "postgres"):
        raise RuntimeError("Set AI_DATABASE_URL to a PostgreSQL URL")
    connection = pg8000.dbapi.connect(
        host=url.hostname or "127.0.0.1",
        port=url.port or 5432,
        database=url.path.lstrip("/"),
        user=unquote(url.username or ""),
        password=unquote(url.password or ""),
        timeout=15,
    )
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def query(connection, sql, args=()):
    cursor = connection.cursor()
    try:
        cursor.execute(sql, args)
        if cursor.description:
            keys = [c[0] for c in cursor.description]
            return [dict(zip(keys, row)) for row in cursor.fetchall()]
        return []
    finally:
        cursor.close()


def initialize():
    with connect() as c:
        query(c, "CREATE EXTENSION IF NOT EXISTS vector")
        query(
            c,
            """CREATE TABLE IF NOT EXISTS policy_chunks(
          policy_id uuid NOT NULL, chunk_id text NOT NULL, content text NOT NULL,
          model text NOT NULL, embedding vector NOT NULL, PRIMARY KEY(policy_id,chunk_id))""",
        )
        query(
            c,
            """CREATE TABLE IF NOT EXISTS reviews(job_id uuid PRIMARY KEY,
          report_id uuid NOT NULL, revision int NOT NULL, result jsonb NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now())""",
        )
        query(
            c,
            """CREATE TABLE IF NOT EXISTS fx_cache(day date NOT NULL, base text NOT NULL,
          quote text NOT NULL, rate numeric NOT NULL, PRIMARY KEY(day,base,quote))""",
        )


if __name__ == "__main__":
    initialize()
    print("AI database initialized (pgvector and review tables).")
