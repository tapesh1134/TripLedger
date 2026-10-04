"""Launch the local Day 7 expense review dashboard."""

import argparse
import secrets
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.review_jobs import JobStore
from app.web import create_server


@contextmanager
def project_lock(root: Path) -> Iterator[None]:
    """One dashboard per project, including across different ports. OS releases on exit."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / "dashboard.lock").open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1..65535")
    root = Path(__file__).resolve().parents[1]
    token = secrets.token_urlsafe(32)
    try:
        with project_lock(root / "runtime"):
            store = JobStore(root / "runtime/dashboard")
            server = create_server(store, token, args.port)
            print(f"TripLedger: http://127.0.0.1:{args.port}/#token={token}", flush=True)
            print("One local review at a time. Starting a review calls your configured API.")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("Stopped. Unfinished reviews will be marked interrupted at next startup.")
            finally:
                server.server_close()
        return 0
    except OSError as error:
        print(
            f"Could not start dashboard ({type(error).__name__}). "
            "Close any dashboard using this project; check port and folder access."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
