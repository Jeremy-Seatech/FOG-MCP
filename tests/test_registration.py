from mcp import Client

from fog_mcp.server import build_server

from .conftest import settings

READ = {"system_info", "search_hosts", "get_host", "list_images", "list_groups", "current_tasks", "multicast_sessions"}
WRITE = {"assign_image", "create_task", "cancel_task"}


async def _names(server):
    async with Client(server) as client:
        return {t.name for t in (await client.list_tools()).tools}


async def test_read_only_by_default():
    assert await _names(build_server(settings())) == READ


async def test_write_tools_when_allowed():
    assert await _names(build_server(settings(allow_write=True))) == READ | WRITE


async def test_write_tools_default_to_no_confirm():
    async with Client(build_server(settings(allow_write=True))) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in WRITE:
        assert tools[name].input_schema["properties"]["confirm"]["default"] is False
        assert tools[name].annotations.destructive_hint is True
