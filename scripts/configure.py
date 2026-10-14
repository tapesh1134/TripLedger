"""Generate local secrets without overwriting existing configuration."""

import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    raise SystemExit(".env already exists; edit it directly. Nothing was overwritten.")
text = (root / ".env.example").read_text()
password = secrets.token_hex(16)
text = text.replace("DB_PASSWORD=CHANGE_ME", "DB_PASSWORD=" + password)
text = text.replace("tripledger:CHANGE_ME@", "tripledger:" + password + "@")
for key in ["SERVICE_KEY", "BOOTSTRAP_ADMIN_PASSWORD", "RABBIT_PASSWORD"]:
    text = text.replace(key + "=CHANGE_ME", key + "=" + secrets.token_hex(24))
target.write_text(text)
print(
    "Created .env with random local secrets. Configure LLM and embeddings there. Your administrator password is in BOOTSTRAP_ADMIN_PASSWORD."
)
