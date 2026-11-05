import json

import httpx
import pytest

from .conftest import call, envelope

HOST = {"id": 7, "name": "pc01", "mac": "aa:bb:cc:dd:ee:ff", "imageID": 3, "imagename": "win10", "ADPass": "x"}
DEPLOY = {"id": 1, "name": "Deploy", "description": "Deploy action", "access": "both", "kernelArgs": "type=down"}
WAKE = {"id": 14, "name": "Wake-Up", "access": "both"}


def mock_host(fog_api, host=HOST):
    fog_api.get(f"/host/{host['id']}").respond(json=host)


def mock_group(fog_api):
    fog_api.get("/group/2").respond(json={"id": 2, "name": "salle-b"})
    fog_api.get("/groupassociation", params={"filter": "groupID=2"}).respond(
        json=envelope([{"id": 1, "hostID": 7, "groupID": 2}, {"id": 2, "hostID": 8, "groupID": 2}])
    )
    fog_api.get("/host", params={"filter": "id=7,8"}).respond(
        json=envelope([HOST, {"id": 8, "name": "pc02", "mac": "11:22", "imageID": None}])
    )


# --- assign_image ---------------------------------------------------------

async def test_assign_image_preview_does_not_write(fog_api, rw_server):
    mock_host(fog_api)
    fog_api.get("/image/4").respond(json={"id": 4, "name": "win11", "isEnabled": 1})
    put = fog_api.put("/host/7")
    err, out = await call(rw_server, "assign_image", {"host_id": 7, "image_id": 4})
    assert not err and not put.called
    assert out["status"] == "confirmation_required"
    assert out["summary"]["current_image"] == {"id": 3, "name": "win10"}
    assert out["summary"]["new_image"]["name"] == "win11"


async def test_assign_image_confirmed(fog_api, rw_server):
    mock_host(fog_api)
    fog_api.get("/image/4").respond(json={"id": 4, "name": "win11"})
    put = fog_api.put("/host/7").respond(json={**HOST, "imageID": 4, "imagename": "win11"})
    err, out = await call(rw_server, "assign_image", {"host_id": 7, "image_id": 4, "confirm": True})
    assert not err and out["status"] == "done"
    assert json.loads(put.calls.last.request.content) == {"imageID": 4}
    assert out["host"]["imageID"] == 4 and "ADPass" not in out["host"]


# --- create_task ----------------------------------------------------------

async def test_deploy_host_preview(fog_api, rw_server):
    mock_host(fog_api)
    fog_api.get("/tasktype/1").respond(json=DEPLOY)
    post = fog_api.post("/host/7/task")
    err, out = await call(rw_server, "create_task", {"target": "host", "target_id": 7, "task_type_id": 1})
    assert not err and not post.called
    assert out["status"] == "confirmation_required"
    s = out["summary"]
    assert s["host"]["name"] == "pc01" and s["host"]["imagename"] == "win10"
    assert s["task_type"]["name"] == "Deploy" and s["destructive"] is True
    assert any("destructive" in w for w in out["warnings"])


async def test_deploy_host_confirmed(fog_api, rw_server):
    fog_api.get("/host/7").mock(
        side_effect=[
            httpx.Response(200, json=HOST),
            httpx.Response(200, json={**HOST, "task": {"id": 51, "name": "Deploy Task"}}),
        ]
    )
    fog_api.get("/tasktype/1").respond(json=DEPLOY)
    # FOG 1.6 answers a queued task with a placeholder body, not the task.
    post = fog_api.post("/host/7/task").respond(json="")
    err, out = await call(
        rw_server, "create_task", {"target": "host", "target_id": 7, "task_type_id": 1, "shutdown": True, "confirm": True}
    )
    assert not err and out["status"] == "done"
    # wol defaults to on, like FOG itself when the field is left out.
    assert json.loads(post.calls.last.request.content) == {"taskTypeID": 1, "shutdown": True, "wol": True, "debug": False}
    assert out["queued_task"] == {"id": 51, "name": "Deploy Task"}


async def test_task_options_passed_through(fog_api, rw_server):
    mock_host(fog_api)
    fog_api.get("/tasktype/12").respond(json={"id": 12, "name": "All Snapins", "access": "both"})
    post = fog_api.post("/host/7/task").respond(json=[])
    await call(
        rw_server,
        "create_task",
        {
            "target": "host", "target_id": 7, "task_type_id": 12, "wol": False,
            "deploy_snapins": True, "snapin_abort_on_failure": True, "confirm": True,
        },
    )
    body = json.loads(post.calls.last.request.content)
    assert body["wol"] is False and body["deploySnapins"] is True and body["snapinAbortOnFailure"] is True


async def test_task_type_permission_denied(fog_api, rw_server):
    mock_host(fog_api)
    fog_api.get("/tasktype/1").respond(json=DEPLOY)
    fog_api.post("/host/7/task").respond(403, json={"error": "Forbidden"})
    err, out = await call(rw_server, "create_task", {"target": "host", "target_id": 7, "task_type_id": 1, "confirm": True})
    assert err and "tasktype.1" in out


async def test_wakeup_still_needs_confirm(fog_api, rw_server):
    mock_host(fog_api)
    fog_api.get("/tasktype/14").respond(json=WAKE)
    post = fog_api.post("/host/7/task")
    err, out = await call(rw_server, "create_task", {"target": "host", "target_id": 7, "task_type_id": 14})
    assert not err and not post.called
    assert out["status"] == "confirmation_required" and out["summary"]["destructive"] is False


async def test_destructive_detected_by_name(fog_api, rw_server):
    mock_host(fog_api)
    fog_api.get("/tasktype/42").respond(json={"id": 42, "name": "Secure Wipe", "access": "both"})
    err, out = await call(rw_server, "create_task", {"target": "host", "target_id": 7, "task_type_id": 42})
    assert out["summary"]["destructive"] is True


async def test_group_deploy_lists_hosts(fog_api, rw_server):
    mock_group(fog_api)
    fog_api.get("/tasktype/1").respond(json=DEPLOY)
    post = fog_api.post("/group/2/task").respond(json=envelope([]))
    err, out = await call(rw_server, "create_task", {"target": "group", "target_id": 2, "task_type_id": 1})
    assert not err and not post.called
    g = out["summary"]["group"]
    assert g["host_count"] == 2 and [h["name"] for h in g["hosts"]] == ["pc01", "pc02"]
    assert g["hosts_without_image"] == ["pc02"]

    err, out = await call(rw_server, "create_task", {"target": "group", "target_id": 2, "task_type_id": 1, "confirm": True})
    assert out["status"] == "done" and post.call_count == 1
    assert "current_tasks" in out["next_step"]


async def test_unknown_task_type(fog_api, rw_server):
    fog_api.get("/tasktype/999").respond(404)
    post = fog_api.post("/host/7/task")
    err, out = await call(rw_server, "create_task", {"target": "host", "target_id": 7, "task_type_id": 999, "confirm": True})
    assert err and "unknown task type 999" in out and not post.called


async def test_task_type_access_mismatch(fog_api, rw_server):
    fog_api.get("/tasktype/1").respond(json={**DEPLOY, "access": "host"})
    post = fog_api.post("/group/2/task")
    err, out = await call(rw_server, "create_task", {"target": "group", "target_id": 2, "task_type_id": 1, "confirm": True})
    assert err and "can only target a host" in out and not post.called


# --- cancel_task ----------------------------------------------------------

async def test_cancel_requires_exactly_one_id(rw_server):
    err, out = await call(rw_server, "cancel_task", {"task_id": 1, "host_id": 2})
    assert err and "exactly one" in out


async def test_cancel_preview_then_confirm(fog_api, rw_server):
    fog_api.get("/task/50").respond(json={"id": 50, "hostID": 7, "typeID": 1, "state": {"id": 2, "name": "In-Progress"}})
    delete = fog_api.delete("/task/50/cancel").respond(json="")
    err, out = await call(rw_server, "cancel_task", {"task_id": 50})
    assert out["status"] == "confirmation_required" and not delete.called
    err, out = await call(rw_server, "cancel_task", {"task_id": 50, "confirm": True})
    assert not err and out["status"] == "done" and delete.called


async def test_cancel_unknown_task_is_404(fog_api, rw_server):
    fog_api.get("/task/999").respond(404, json={"error": "No such object"})
    delete = fog_api.delete("/task/999/cancel")
    err, out = await call(rw_server, "cancel_task", {"task_id": 999, "confirm": True})
    assert err and "404" in out and not delete.called


@pytest.mark.parametrize(("kind", "path"), [("host_id", "/host/7/cancel")])
async def test_cancel_409_not_cancellable(fog_api, rw_server, kind, path):
    mock_host(fog_api)
    fog_api.delete(path).respond(409, json={"error": "Task already Complete"})
    err, out = await call(rw_server, "cancel_task", {kind: 7, "confirm": True})
    assert not err and out["status"] == "not_cancellable" and "Complete" in out["message"]
