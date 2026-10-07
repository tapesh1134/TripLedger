"""Start all four mock servers: python -m mock_systems.run."""

import argparse
import json
import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

from mock_systems.seed_data import DEFAULT_PATH
from mock_systems.service import MockServer


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Run four synthetic HTTP services on localhost")
    parser.add_argument("--seed", type=Path, default=DEFAULT_PATH.with_name("evaluation-data.json"))
    parser.add_argument("--queue", type=Path, default=Path("runtime/review-queue.sqlite3"))
    args = parser.parse_args()
    data = json.loads(args.seed.read_text(encoding="utf-8"))
    servers = []
    try:
        for role, default in [("card", 8011), ("travel", 8012), ("hr", 8013), ("ledger", 8014)]:
            server = MockServer(
                role,
                data,
                int(os.getenv(f"MOCK_{role.upper()}_PORT", str(default))),
                args.queue,
                int(os.getenv("MOCK_CARD_FAIL_EVERY", "10")),
                float(os.getenv("MOCK_TRAVEL_DELAY_SECONDS", "0.15")),
            )
            servers.append(server)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            print(f"{role}: http://127.0.0.1:{server.server_port}", flush=True)
        print("Synthetic services ready. Ctrl+C stops all four.", flush=True)
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping mocks.")
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
