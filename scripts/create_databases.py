"""Use the AI connection's server/user/password to create default databases.
The configured user needs CREATEDB; otherwise run infra/create-databases.sql as a DBA.
Existing databases are preserved. Edit URLs if choosing different database names.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai-service"))
from app.config import env
from urllib.parse import urlsplit, unquote
import pg8000.dbapi

u = urlsplit(env("AI_DATABASE_URL"))
conn = pg8000.dbapi.connect(
    host=u.hostname,
    port=u.port or 5432,
    user=unquote(u.username or ""),
    password=unquote(u.password or ""),
    database="postgres",
    timeout=15,
)
conn.autocommit = True
try:
    cursor = conn.cursor()
    for name in [
        "tripledger_identity",
        "tripledger_expense",
        "tripledger_policy",
        "tripledger_ai",
    ]:
        cursor.execute("SELECT 1 FROM pg_database WHERE datname=%s", (name,))
        if not cursor.fetchone():
            cursor.execute("CREATE DATABASE " + name)
        print(name + ": ready")
finally:
    conn.close()
