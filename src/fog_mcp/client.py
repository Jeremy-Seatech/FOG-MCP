"""Thin async client for the FOG 1.6 REST API (see swagger.json)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from fog_mcp import __version__
from fog_mcp.config import Settings

# Credential-like fields never returned to the model, at any nesting depth.
SENSITIVE_KEYS = frozenset(
    {
        "ADPass",
        "ADPassLegacy",
        "ADUser",
        "productKey",
        "pub_key",
        "sec_tok",
        "prev_sec_tok",
        "token",
        "tokenlock",
        "sbenrollcert",
        "password",
        "pass",
    }
)

_STATUS_HINTS = {
    401: "authentication missing or invalid (check FOG_API_TOKEN)",
    403: "authenticated but not permitted",
    404: "no such object",
    409: "the resource is not in a cancellable state",
}


class FogError(ToolError):
    """An error reply from the FOG API, surfaced to the MCP client as a tool error."""

    def __init__(self, status: int | None, message: str) -> None:
        self.status = status
        prefix = f"FOG API {status}" if status is not None else "FOG API"
        super().__init__(f"{prefix}: {message}")


def sanitize(value: Any) -> Any:
    """Drop credential fields recursively."""
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items() if k not in SENSITIVE_KEYS}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    return value


def segment(value: str | int) -> str:
    """Encode one path segment (search terms may contain / or spaces)."""
    return quote(str(value), safe="")


class FogClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    @property
    def _http(self) -> httpx.AsyncClient:
        # Created lazily and re-created after aclose(): the server lifespan closes it
        # at the end of each MCP session.
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.settings.url + "/",
                headers={
                    # Bearer tokens are sent raw: only fog-api-token / fog-user-token are base64.
                    "Authorization": f"Bearer {self.settings.token}",
                    "Accept": "application/json",
                    "User-Agent": f"fog-mcp/{__version__}",
                },
                verify=self.settings.ssl_verify(),
                timeout=self.settings.timeout,
                transport=self._transport,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        try:
            resp = await self._http.request(method, path.lstrip("/"), params=params, json=json)
        except httpx.HTTPError as exc:
            raise FogError(None, f"{type(exc).__name__}: {exc}") from exc

        if resp.is_error:
            raise FogError(resp.status_code, self._error_message(resp))
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError as exc:
            raise FogError(resp.status_code, "response is not JSON") from exc

    @staticmethod
    def _error_message(resp: httpx.Response) -> str:
        detail = ""
        try:
            body = resp.json()
            if isinstance(body, dict):
                detail = str(body.get("error") or body.get("msg") or "")
        except ValueError:
            detail = resp.text.strip()[:200]
        hint = _STATUS_HINTS.get(resp.status_code, resp.reason_phrase)
        return f"{hint} ({detail})" if detail else hint

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self.request("GET", path, params=params)

    async def page(
        self,
        path: str,
        *,
        start: int = 0,
        length: int = 100,
        filter: str | None = None,
    ) -> dict[str, Any]:
        """One page of a list envelope. start/length are always sent so the server never caps at MAX_ROWS."""
        params: dict[str, Any] = {"start": max(0, start), "length": max(1, length)}
        if filter:
            params["filter"] = filter
        body = await self.get(path, params)
        if not isinstance(body, dict):
            raise FogError(None, f"unexpected list response from {path}")
        return body
