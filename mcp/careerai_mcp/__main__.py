"""Entry point: `careerai-mcp` (stdio) or `python -m careerai_mcp --check`."""

import asyncio
import sys

from careerai_mcp.server import server


def main() -> int:
    if "--check" in sys.argv:
        tools = asyncio.run(server.list_tools())
        print("careerai-mcp tools:", ", ".join(tool.name for tool in tools))
        return 0
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
