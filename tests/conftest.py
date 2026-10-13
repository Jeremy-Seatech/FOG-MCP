from __future__ import annotations

import json
from typing import Any

import pytest
import respx
from mcp import Client

from fog_mcp.config import Settings
from fog_mcp.server import build_server

BASE = "https://fog.test/fog"
TOKEN = "fog_0123456789abcdef"


def envelope(rows: list[dict[str, Any]], total: int | None = None, next_url: str | None = None) -> dict[str, Any]:
    return {
        "recordsTotal": total if total is not None else len(rows),
        "recordsFiltered": total if total is not None else len(rows),
        "recordsReturned": len(rows),
        "data": rows,
        "nextUrl": next_url,
    }


def settings(**overrides: Any) -> Settings:
    return Settings(url=BASE, token=TOKEN, **overrides)


@pytest.fixture
def fog_api():
    with respx.mock(base_url=BASE, assert_all_called=False, assert_all_mocked=True) as router:
        yield router


async def call(server, name: str, args: dict[str, Any] | None = None) -> tuple[bool, Any]:
    """Call a tool in-process; returns (is_error, parsed JSON or raw text)."""
    async with Client(server) as client:
        result = await client.call_tool(name, args or {})
    text = result.content[0].text
    try:
        return result.is_error, json.loads(text)
    except ValueError:
        return result.is_error, text


@pytest.fixture
def ro_server(fog_api):
    return build_server(settings())


@pytest.fixture
def rw_server(fog_api):
    return build_server(settings(allow_write=True))
