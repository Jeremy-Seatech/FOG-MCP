"""Write tools: registered only when FOG_MCP_ALLOW_WRITE=1.

Every write is two-step. Without confirm=true the tool only reads, and returns a
summary of what would happen. The call has to be repeated with confirm=true to act.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from fog_mcp.client import FogClient, FogError, sanitize
from fog_mcp.shapes import TASK_FIELDS, pick
from fog_mcp.tasks import (
    Target,
    check_access,
    group_summary,
    host_summary,
    is_destructive,
    resolve_task_type,
    target_summary,
)

Id = Annotated[int, Field(ge=1)]
Confirm = Annotated[
    bool,
    Field(description="false (default): return a summary and change nothing. true: perform the action."),
]


def _needs_confirmation(action: str, summary: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"status": "confirmation_required", "action": action, "summary": summary}
    if warnings:
        out["warnings"] = warnings
    out["next_step"] = (
        "Nothing was changed. Show this summary to the user and, only once they approve it, "
        "call the same tool again with the same arguments and confirm=true."
    )
    return out


def register_write_tools(mcp: MCPServer, fog: FogClient) -> None:
    destructive_types = fog.settings.destructive_task_types

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True, idempotent_hint=True, open_world_hint=True))
    async def assign_image(host_id: Id, image_id: Id, confirm: Confirm = False) -> dict[str, Any]:
        """Set the image a host will receive on its next deploy. PUT /host/{id} {"imageID": ...}.

        Requires confirm=true; without it, returns the host, its current image and the new image.
        """
        host = await host_summary(fog, host_id)
        image = pick(await fog.get(f"image/{image_id}"), ("id", "name", "path", "os", "isEnabled"))
        summary = {
            "host": {k: host.get(k) for k in ("id", "name", "mac")},
            "current_image": {"id": host.get("imageID"), "name": host.get("imagename")},
            "new_image": image,
        }
        warnings = []
        if str(image.get("isEnabled", "1")) in ("0", "False", "false"):
            warnings.append(f"image {image.get('name')!r} is disabled")
        if host.get("imageID") == image_id:
            warnings.append("the host already has this image")

        if not confirm:
            return _needs_confirmation("assign_image", summary, warnings)

        updated = await fog.request("PUT", f"host/{host_id}", json={"imageID": image_id})
        return {
            "status": "done",
            "action": "assign_image",
            "summary": summary,
            "host": pick(updated, ("id", "name", "imageID", "imagename")) or sanitize(updated),
        }

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True, open_world_hint=True))
    async def create_task(
        target: Annotated[Target, Field(description="'host' or 'group'")],
        target_id: Id,
        task_type_id: Annotated[
            int,
            Field(ge=1, description="FOG task type ID, e.g. 1 deploy, 2 capture, 14 wake-up (see GET /tasktype)"),
        ],
        confirm: Confirm = False,
        shutdown: Annotated[bool, Field(description="Power off when the task finishes")] = False,
        wol: Annotated[bool, Field(description="Send wake-on-LAN when queuing")] = False,
        debug: bool = False,
        deploy_snapins: Annotated[
            bool | int | None, Field(description="Deploy all snapins (true) or one snapin ID")
        ] = None,
        task_name: str | None = None,
    ) -> dict[str, Any]:
        """Queue a task on a host or group. POST /host/{id}/task or POST /group/{id}/task.

        Requires confirm=true; without it, returns the target (hosts, current images) and task type.
        """
        task_type = await resolve_task_type(fog, task_type_id)
        check_access(task_type, target)
        destructive = is_destructive(task_type, destructive_types)
        tgt = await target_summary(fog, target, target_id)

        options = {"shutdown": shutdown, "wol": wol, "debug": debug}
        if deploy_snapins is not None:
            options["deploySnapins"] = deploy_snapins
        summary = {
            "target": target,
            target: tgt,
            "task_type": task_type,
            "destructive": destructive,
            "options": options,
        }
        warnings = []
        if destructive:
            warnings.append(
                f"{task_type.get('name')!r} is destructive: disks on the target machine(s) "
                "or the stored image may be overwritten"
            )
        if target == "host" and destructive and not tgt.get("imageID"):
            warnings.append("the host has no image assigned")
        if tgt.get("hosts_without_image") and destructive:
            warnings.append(f"hosts without an image: {', '.join(map(str, tgt['hosts_without_image']))}")
        if target == "group" and tgt.get("host_count") == 0:
            warnings.append("the group has no hosts")

        if not confirm:
            return _needs_confirmation("create_task", summary, warnings)

        body: dict[str, Any] = {"taskTypeID": task_type_id, **options}
        if task_name:
            body["taskName"] = task_name
        result = await fog.request("POST", f"{target}/{target_id}/task", json=body)
        return {"status": "done", "action": "create_task", "summary": summary, "result": sanitize(result)}

    @mcp.tool(annotations=ToolAnnotations(destructive_hint=True, idempotent_hint=True, open_world_hint=True))
    async def cancel_task(
        task_id: Annotated[int | None, Field(ge=1, description="Cancel this task (DELETE /task/{id}/cancel)")] = None,
        host_id: Annotated[int | None, Field(ge=1, description="Cancel the host's task (DELETE /host/{id}/cancel)")] = None,
        group_id: Annotated[int | None, Field(ge=1, description="Cancel the group's tasks (DELETE /group/{id}/cancel)")] = None,
        confirm: Confirm = False,
    ) -> dict[str, Any]:
        """Cancel a queued or in-progress task. Give exactly one of task_id, host_id, group_id.

        Requires confirm=true; without it, returns what would be cancelled.
        """
        given = {k: v for k, v in (("task", task_id), ("host", host_id), ("group", group_id)) if v is not None}
        if len(given) != 1:
            raise FogError(None, "give exactly one of task_id, host_id or group_id")
        kind, obj_id = next(iter(given.items()))

        if kind == "task":
            summary: dict[str, Any] = {"task": pick(await fog.get(f"task/{obj_id}"), TASK_FIELDS)}
        elif kind == "host":
            summary = {"host": await host_summary(fog, obj_id)}
        else:
            summary = {"group": await group_summary(fog, obj_id)}

        if not confirm:
            return _needs_confirmation("cancel_task", summary, [])

        try:
            result = await fog.request("DELETE", f"{kind}/{obj_id}/cancel")
        except FogError as exc:
            if exc.status == 409:
                return {"status": "not_cancellable", "action": "cancel_task", "summary": summary, "message": str(exc)}
            raise
        return {"status": "done", "action": "cancel_task", "summary": summary, "result": sanitize(result)}
