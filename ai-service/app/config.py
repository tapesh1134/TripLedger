import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
# Root .env is loaded by the launcher. The service .env is an optional override source.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def env(name, default=""):
    return os.environ.get(name, default)


def service_key():
    key = env("SERVICE_KEY")
    if len(key) < 32:
        raise RuntimeError("SERVICE_KEY requires at least 32 characters")
    return key
