"""Read-only tools: always registered."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from fog_mcp.client import FogClient, FogError, sanitize, segment
from fog_mcp.shapes import (
    HOST_FIELDS,
    IMAGE_FIELDS,
    MULTICAST_FIELDS,
    TASK_FIELDS,
    group_summary,
    page_summary,
)

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)

Limit = Annotated[int, Field(ge=1, le=500, description="Page size (1-500)")]
Start = Annotated[int, Field(ge=0, description="Row offset; use next_start from a previous page")]


def register_read_tools(mcp: MCPServer, fog: FogClient) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def system_info() -> dict[str, Any]:
        """FOG server version and paging bounds, plus a check that the API token is accepted.

        GET /system/info (unauthenticated) then GET /task/count to validate the token.
        """
        info = await fog.get("system/info")
        out: dict[str, Any] = {"server": info, "url": fog.settings.url}
        try:
            await fog.get("task/count")
            out["auth"] = "ok"
        except FogError as exc:
            out["auth"] = f"failed: {exc}"
        out["write_tools_enabled"] = fog.settings.allow_write
        return out

    @mcp.tool(annotations=READ_ONLY)
    async def search_hosts(
        query: Annotated[str, Field(min_length=1, description="Term matched against host names")],
        limit: Limit = 50,
        start: Start = 0,
    ) -> dict[str, Any]:
        """Search hosts by name. GET /host/search/{item}."""
        body = await fog.page(f"host/search/{segment(query)}", start=start, length=limit)
        return page_summary(body, HOST_FIELDS, start)

    @mcp.tool(annotations=READ_ONLY)
    async def get_host(host_id: Annotated[int, Field(ge=1)]) -> dict[str, Any]:
        """Full details of one host (credentials removed). GET /host/{id}."""
        return sanitize(await fog.get(f"host/{host_id}"))

    @mcp.tool(annotations=READ_ONLY)
    async def list_images(
        limit: Limit = 100,
        start: Start = 0,
        name_filter: Annotated[
            str | None, Field(description="Exact image name; comma separated to match any")
        ] = None,
    ) -> dict[str, Any]:
        """List images. GET /image (?filter=name=...)."""
        flt = f"name={name_filter}" if name_filter else None
        body = await fog.page("image", start=start, length=limit, filter=flt)
        return page_summary(body, IMAGE_FIELDS, start)

    @mcp.tool(annotations=READ_ONLY)
    async def list_groups(limit: Limit = 100, start: Start = 0) -> dict[str, Any]:
        """List host groups. GET /group."""
        body = await fog.page("group", start=start, length=limit)
        out = page_summary(body, (), start)
        out["items"] = [group_summary(row) for row in body.get("data") or []]
        return out

    @mcp.tool(annotations=READ_ONLY)
    async def current_tasks(limit: Limit = 100, start: Start = 0) -> dict[str, Any]:
        """Queued and in-progress tasks. GET /task/current."""
        body = await fog.page("task/current", start=start, length=limit)
        return page_summary(body, TASK_FIELDS, start)

    @mcp.tool(annotations=READ_ONLY)
    async def multicast_sessions(
        active_only: bool = True, limit: Limit = 50, start: Start = 0
    ) -> dict[str, Any]:
        """Multicast sessions. GET /multicastsession/current, or GET /multicastsession for all."""
        path = "multicastsession/current" if active_only else "multicastsession"
        body = await fog.page(path, start=start, length=limit)
        return page_summary(body, MULTICAST_FIELDS, start)
