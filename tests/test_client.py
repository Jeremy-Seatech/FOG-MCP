import httpx
import pytest

from fog_mcp.client import FogClient, FogError, sanitize

from .conftest import TOKEN, envelope, settings


async def test_bearer_token_sent_raw(fog_api):
    route = fog_api.get("/host/1").respond(json={"id": 1})
    await FogClient(settings()).get("host/1")
    auth = route.calls.last.request.headers["Authorization"]
    assert auth == f"Bearer {TOKEN}"  # not base64 encoded
    assert "fog-api-token" not in route.calls.last.request.headers


async def test_base_path_is_kept(fog_api):
    route = fog_api.get("/system/info").respond(json={})
    await FogClient(settings()).get("/system/info")
    assert route.calls.last.request.url.path == "/fog/system/info"


async def test_page_always_sends_start_and_length(fog_api):
    route = fog_api.get("/image").respond(json=envelope([]))
    await FogClient(settings()).page("image", start=0, length=10, filter="name=win11")
    params = route.calls.last.request.url.params
    assert params["start"] == "0" and params["length"] == "10" and params["filter"] == "name=win11"


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (401, None, "401: authentication missing or invalid"),
        (403, None, "403: authenticated but not permitted"),
        (404, {"error": "Host not found"}, "404: no such object (Host not found)"),
        (400, {"error": "Unknown filter key: foo"}, "400: Bad Request (Unknown filter key: foo)"),
    ],
)
async def test_errors(fog_api, status, body, expected):
    fog_api.get("/host/9").respond(status, json=body)
    with pytest.raises(FogError, match=expected.replace("(", r"\(").replace(")", r"\)")) as info:
        await FogClient(settings()).get("host/9")
    assert info.value.status == status


async def test_network_error(fog_api):
    fog_api.get("/host/1").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(FogError, match="ConnectError"):
        await FogClient(settings()).get("host/1")


def test_sanitize_recursive():
    data = {"id": 1, "ADPass": "x", "token": "t", "inventory": {"sec_tok": "s", "cpu": "i7"}, "l": [{"pub_key": "k"}]}
    assert sanitize(data) == {"id": 1, "inventory": {"cpu": "i7"}, "l": [{}]}
