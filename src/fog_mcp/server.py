"""FOG MCP server entry point (stdio)."""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from mcp.server.mcpserver import MCPServer

from fog_mcp import __version__
from fog_mcp.client import FogClient
from fog_mcp.config import ConfigError, Settings
from fog_mcp.tools_read import register_read_tools
from fog_mcp.tools_write import register_write_tools

log = logging.getLogger("fog_mcp")

INSTRUCTIONS = """\
Tools for a FOG Project imaging server (REST API 1.6).
Use search_hosts / list_groups / list_images to resolve names to numeric IDs first.
Write tools, when present, never act on the first call: they return a summary with
status "confirmation_required". Show it to the user and only call again with
confirm=true once the user has explicitly approved that exact summary.
"""


def build_server(settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> MCPServer:
    fog = FogClient(settings, transport=transport)

    @asynccontextmanager
    async def lifespan(_: MCPServer) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await fog.aclose()

    mcp = MCPServer(
        "fog",
        title="FOG Project",
        instructions=INSTRUCTIONS,
        version=__version__,
        lifespan=lifespan,
    )
    register_read_tools(mcp, fog)
    if settings.allow_write:
        register_write_tools(mcp, fog)
    return mcp


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"fog-mcp: configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    if not settings.verify_tls and settings.ca_bundle is None:
        log.warning("TLS verification is DISABLED (FOG_VERIFY_TLS=0). Prefer FOG_CA_BUNDLE.")
    log.info(
        "FOG %s, write tools %s", settings.url, "ENABLED" if settings.allow_write else "disabled (read-only)"
    )
    build_server(settings).run("stdio")


if __name__ == "__main__":
    main()
