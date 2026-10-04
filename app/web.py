"""Loopback-only dashboard; standard-library HTTP server, not a deployment server."""

import hmac
import json
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError

from app.review_jobs import BusyError, JobStore

ROOT = Path(__file__).resolve().parents[1]
MAX_BODY = 1024 * 1024
EXAMPLES = {
    "clean": "evals/reports/EVAL-01.json",
    "missing-receipt": "evals/reports/EVAL-24.json",
    "injection": "evals/reports/EVAL-21.json",
    "image": "examples/vision-report.json",
}


def make_handler(store: JobStore, token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass  # No request bodies, tokens or URLs in HTTP logs.

        def send(self, status: int, value: Any, mime: str = "application/json") -> None:
            body = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def authorized(self, api: bool = True) -> bool:
            expected = f"127.0.0.1:{self.server.server_port}"  # type: ignore[attr-defined]
            if self.headers.get("Host") != expected:
                self.send(403, {"error": "Use the printed 127.0.0.1 dashboard URL."})
                return False
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + expected:
                self.send(403, {"error": "Cross-origin request rejected."})
                return False
            if api and not hmac.compare_digest(self.headers.get("X-Session-Token", ""), token):
                self.send(403, {"error": "Open the complete URL printed by app.day7."})
                return False
            return True

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            assets = {
                "/": ("dashboard.html", "text/html; charset=utf-8"),
                "/dashboard.js": ("dashboard.js", "text/javascript; charset=utf-8"),
                "/dashboard.css": ("dashboard.css", "text/css; charset=utf-8"),
            }
            if not self.authorized(api=path not in assets):
                return
            try:
                if path in assets:
                    name, mime = assets[path]
                    self.send(200, (ROOT / "app/static" / name).read_bytes(), mime)
                elif path == "/api/jobs":
                    self.send(200, store.list())
                elif path.startswith("/api/examples/"):
                    key = path.removeprefix("/api/examples/")
                    if key not in EXAMPLES:
                        raise FileNotFoundError
                    self.send(200, (ROOT / EXAMPLES[key]).read_bytes())
                elif path.startswith("/api/jobs/"):
                    parts = path.removeprefix("/api/jobs/").split("/")
                    if len(parts) == 1:
                        self.send(200, store.get(parts[0]))
                    elif len(parts) == 2 and parts[1] in {"result.json", "trace.json"}:
                        self.send(200, (store.directory(parts[0]) / parts[1]).read_bytes())
                    else:
                        raise FileNotFoundError
                else:
                    raise FileNotFoundError
            except FileNotFoundError:
                self.send(404, {"error": "Not found or artifact not saved yet."})
            except (OSError, ValueError):
                self.send(500, {"error": "Could not read the saved artifact."})

        def do_POST(self) -> None:
            if not self.authorized():
                return
            if self.path != "/api/jobs":
                self.send(404, {"error": "Not found."})
                return
            if self.headers.get_content_type() != "application/json":
                self.send(415, {"error": "Send application/json."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY or self.headers.get("Transfer-Encoding"):
                    self.send(413, {"error": "Report must be between 1 byte and 1 MiB."})
                    return
                self.connection.settimeout(10)
                raw = json.loads(self.rfile.read(length), parse_float=Decimal)
                self.send(202, store.submit(raw))
            except BusyError as error:
                self.send(409, {"error": str(error)})
            except ValidationError as error:
                problems = [
                    {"field": ".".join(map(str, e["loc"])), "type": e["type"]}
                    for e in error.errors(include_input=False, include_context=False)
                ]
                self.send(422, {"error": "Invalid report.", "problems": problems})
            except (ValueError, UnicodeError):
                self.send(400, {"error": "Invalid JSON or content length."})
            except OSError:
                self.send(500, {"error": "Could not read request or save review."})

    return Handler


def create_server(store: JobStore, token: str, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(store, token))
