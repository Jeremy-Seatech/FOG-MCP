from .conftest import call, envelope


async def test_system_info_checks_auth(fog_api, ro_server):
    fog_api.get("/system/info").respond(json={"version": "1.6.0-RC-10", "paging": {"maxRows": None}})
    fog_api.get("/task/count").respond(json={"total": 3})
    err, out = await call(ro_server, "system_info")
    assert not err
    assert out["server"]["version"] == "1.6.0-RC-10"
    assert out["auth"] == "ok"
    assert out["write_tools_enabled"] is False


async def test_system_info_reports_bad_token(fog_api, ro_server):
    fog_api.get("/system/info").respond(json={"version": "1.6.0-RC-10"})
    fog_api.get("/task/count").respond(401)
    err, out = await call(ro_server, "system_info")
    assert not err
    assert out["auth"].startswith("failed: FOG API 401")


async def test_search_hosts_encodes_and_trims(fog_api, ro_server):
    route = fog_api.get("/host/search/pc%2F01").respond(
        json=envelope(
            [{"id": 7, "name": "pc01", "mac": "aa:bb", "imageID": 3, "imagename": "win11", "ADPass": "secret", "kernelArgs": ""}],
            total=12,
            next_url="/fog/host/search/pc?start=1",
        )
    )
    err, out = await call(ro_server, "search_hosts", {"query": "pc/01", "limit": 1})
    assert not err
    assert route.calls.last.request.url.params["length"] == "1"
    assert out["total"] == 12 and out["next_start"] == 1
    assert out["items"] == [{"id": 7, "name": "pc01", "mac": "aa:bb", "imageID": 3, "imagename": "win11"}]


async def test_get_host_strips_secrets(fog_api, ro_server):
    fog_api.get("/host/7").respond(json={"id": 7, "name": "pc01", "ADPass": "x", "token": "y", "sec_tok": "z"})
    err, out = await call(ro_server, "get_host", {"host_id": 7})
    assert not err and out == {"id": 7, "name": "pc01"}


async def test_get_host_404_is_tool_error(fog_api, ro_server):
    fog_api.get("/host/99").respond(404, json={"error": "No such object"})
    err, out = await call(ro_server, "get_host", {"host_id": 99})
    assert err and "404" in out


async def test_list_images_filter(fog_api, ro_server):
    route = fog_api.get("/image").respond(json=envelope([{"id": 3, "name": "win11", "os": {"id": 9, "name": "Windows 11", "description": "long"}}]))
    err, out = await call(ro_server, "list_images", {"name_filter": "win11"})
    assert not err
    assert route.calls.last.request.url.params["filter"] == "name=win11"
    assert out["items"][0]["os"] == {"id": 9, "name": "Windows 11"}


async def test_list_groups_counts_hosts(fog_api, ro_server):
    fog_api.get("/group").respond(json=envelope([{"id": 2, "name": "salle-b", "hosts": [1, 2, 3]}]))
    err, out = await call(ro_server, "list_groups")
    assert not err and out["items"] == [{"id": 2, "name": "salle-b", "host_count": 3}]


async def test_current_tasks(fog_api, ro_server):
    fog_api.get("/task/current").respond(
        json=envelope([{"id": 50, "hostID": 7, "typeID": 1, "type": {"id": 1, "name": "Deploy", "kernelArgs": "x"}, "percent": 42}])
    )
    err, out = await call(ro_server, "current_tasks")
    assert not err and out["items"][0]["type"] == {"id": 1, "name": "Deploy"} and out["items"][0]["percent"] == 42


async def test_multicast_active_vs_all(fog_api, ro_server):
    active = fog_api.get("/multicastsession/current").respond(json=envelope([]))
    every = fog_api.get("/multicastsession").respond(json=envelope([{"id": 1, "name": "mc", "port": 9000}]))
    await call(ro_server, "multicast_sessions")
    err, out = await call(ro_server, "multicast_sessions", {"active_only": False})
    assert active.called and every.called
    assert out["items"] == [{"id": 1, "name": "mc", "port": 9000}]
