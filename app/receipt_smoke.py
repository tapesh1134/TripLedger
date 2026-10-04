"""Exercise read_receipt through real MCP without running a whole report."""

import argparse
import asyncio
import json

from integrations.mcp_client import connect


async def run(file_path: str) -> int:
    async with connect() as session:
        result = await session.call_tool("read_receipt", {"file_path": file_path})
        data = result.structuredContent or {"ok": False, "error": "MCP returned no data"}
        print(json.dumps(data, indent=2))
        return 0 if data.get("ok") else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Read a JSON or PNG/JPEG receipt through MCP")
    parser.add_argument("file_path")
    return asyncio.run(run(parser.parse_args().file_path))


if __name__ == "__main__":
    raise SystemExit(main())
