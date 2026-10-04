"""Inspector-friendly script entry point (avoids CLI option forwarding ambiguity)."""
import asyncio

from mcp_server.server import main

if __name__ == '__main__':
    asyncio.run(main())
