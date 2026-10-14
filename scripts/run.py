"""Run one component locally with the root .env loaded. Keep this terminal open."""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv

root = Path(__file__).resolve().parents[1]
load_dotenv(root / ".env")
p = argparse.ArgumentParser()
p.add_argument(
    "service",
    choices=[
        "identity",
        "expense",
        "policy",
        "gateway",
        "ai-api",
        "ai-worker",
        "frontend",
    ],
)
a = p.parse_args()
java = {
    "identity": "identity-service",
    "expense": "expense-service",
    "policy": "policy-service",
    "gateway": "api-gateway",
}
if a.service in java:
    module = java[a.service]
    jar = root / module / "target" / f"{module}-1.0.0.jar"
    if not jar.exists():
        raise SystemExit("Build Java services first: mvn clean verify")
    command = ["java", "-jar", str(jar)]
    cwd = root
elif a.service == "ai-api":
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        os.getenv("BIND_ADDRESS", "127.0.0.1"),
        "--port",
        "8090",
    ]
    cwd = root / "ai-service"
elif a.service == "ai-worker":
    command = [sys.executable, "-m", "app.worker"]
    cwd = root / "ai-service"
else:
    command = ["npm.cmd" if os.name == "nt" else "npm", "run", "dev"]
    cwd = root / "frontend"
try:
    raise SystemExit(subprocess.call(command, cwd=cwd))
except KeyboardInterrupt:
    pass
