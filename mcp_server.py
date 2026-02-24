# -*- coding: utf-8 -*-
"""
x-reader MCP Server — expose content reading as MCP tools.

Usage:
    python mcp_server.py                    # stdio transport (for Claude Code)
    python mcp_server.py --transport sse    # SSE transport (for web clients)

Claude Code config (~/.claude/claude_desktop_config.json):
    {
        "mcpServers": {
            "x-reader": {
                "command": "python",
                "args": ["/path/to/x-reader/mcp_server.py"]
            }
        }
    }
"""

import asyncio
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

from x_reader.reader import UniversalReader
from x_reader.schema import UnifiedInbox

mcp = FastMCP(
    "x-reader",
    instructions="Universal content reader — give it any URL, get structured content back.",
)

reader = UniversalReader(inbox=UnifiedInbox())


@mcp.tool()
async def read_url(url: str) -> str:
    """
    Read content from any URL and return structured result.

    Supports: YouTube, Bilibili, X/Twitter, WeChat, Xiaohongshu,
    Telegram, RSS, and any generic web page.

    Returns JSON with: title, content, url, source_type, platform metadata.
    """
    import json

    content = await reader.read(url)
    result = content.to_dict()
    # Keep it readable
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def read_batch(urls: list[str]) -> str:
    """
    Read multiple URLs concurrently. Returns JSON array of results.

    Failed URLs are logged but don't block other results.
    """
    import json

    contents = await reader.read_batch(urls)
    results = [c.to_dict() for c in contents]
    return json.dumps(results, ensure_ascii=False, indent=2)


@mcp.tool()
async def list_inbox() -> str:
    """
    List all items in the content inbox.

    Returns JSON array of previously fetched content.
    """
    import json

    items = [item.to_dict() for item in reader.inbox.items]
    return json.dumps(items, ensure_ascii=False, indent=2)


@mcp.tool()
async def detect_platform(url: str) -> str:
    """
    Detect which platform a URL belongs to.

    Returns the platform name: youtube, bilibili, twitter, wechat,
    xhs, telegram, rss, or generic.
    """
    return reader._detect_platform(url)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="x-reader MCP Server")
    parser.add_argument(
        "--transport", default="stdio", choices=["stdio", "sse"],
        help="Transport mode (default: stdio)",
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Host to bind SSE server (default: 127.0.0.1). "
        "WARNING: binding to 0.0.0.0 exposes the server to the network "
        "without authentication — use at your own risk.",
    )
    parser.add_argument("--port", type=int, default=8000, help="SSE port (default: 8000)")
    args = parser.parse_args()

    if args.transport == "sse":
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")
