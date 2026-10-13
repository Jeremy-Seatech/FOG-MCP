"""Task type resolution and the target summaries shown before any write."""

from __future__ import annotations

import re
from typing import Any, Literal

from fog_mcp.client import FogClient, FogError
from fog_mcp.shapes import pick

Target = Literal["host", "group"]

# Second line of defence when an ID is missing from FOG_MCP_DESTRUCTIVE_TASK_TYPES:
# task type names come from the server's taskTypes table.
_DESTRUCTIVE_NAME = re.compile(r"deploy|wipe|multi-?cast|capture", re.IGNORECASE)

# Rows shown by name in a group summary; the count always covers the whole group.
GROUP_PREVIEW_HOSTS = 50
_MAX_GROUP_MEMBERS = 5000


async def resolve_task_type(fog: FogClient, task_type_id: int) -> dict[str, Any]:
    try:
        tt = await fog.get(f"tasktype/{task_type_id}")
    except FogError as exc:
        if exc.status == 404:
            raise FogError(404, f"unknown task type {task_type_id} (see GET /tasktype)") from exc
        raise
    return pick(tt, ("id", "name", "description", "access", "isAdvanced"))


def is_destructive(task_type: dict[str, Any], configured: frozenset[int]) -> bool:
    return task_type.get("id") in configured or bool(
        _DESTRUCTIVE_NAME.search(str(task_type.get("name", "")))
    )


def check_access(task_type: dict[str, Any], target: Target) -> None:
    """tasktype.access is both|host|group."""
    access = task_type.get("access") or "both"
    if access not in ("both", target):
        raise FogError(
            400, f"task type {task_type.get('name')!r} can only target a {access}, not a {target}"
        )


async def host_summary(fog: FogClient, host_id: int) -> dict[str, Any]:
    host = await fog.get(f"host/{host_id}")
    out = pick(host, ("id", "name", "mac", "ip", "imageID", "imagename", "task"))
    if not out.get("imageID"):
        out["imageID"] = None
    return out


async def group_hosts(fog: FogClient, group_id: int) -> tuple[int, list[dict[str, Any]]]:
    """Member count and the first members (name, mac, image) via groupassociation."""
    assoc = await fog.page(
        "groupassociation", start=0, length=_MAX_GROUP_MEMBERS, filter=f"groupID={group_id}"
    )
    host_ids = [row["hostID"] for row in assoc.get("data") or [] if row.get("hostID")]
    if not host_ids:
        return 0, []
    preview_ids = host_ids[:GROUP_PREVIEW_HOSTS]
    hosts = await fog.page(
        "host",
        start=0,
        length=len(preview_ids),
        filter="id=" + ",".join(str(i) for i in preview_ids),
    )
    rows = [pick(h, ("id", "name", "mac", "imageID", "imagename")) for h in hosts.get("data") or []]
    return len(host_ids), rows


async def group_summary(fog: FogClient, group_id: int) -> dict[str, Any]:
    group = await fog.get(f"group/{group_id}")
    out = pick(group, ("id", "name", "description"))
    count, hosts = await group_hosts(fog, group_id)
    out["host_count"] = count
    out["hosts"] = hosts
    if count > len(hosts):
        out["hosts_not_listed"] = count - len(hosts)
    without_image = [h.get("name") for h in hosts if not h.get("imageID")]
    if without_image:
        out["hosts_without_image"] = without_image
    return out


async def target_summary(fog: FogClient, target: Target, target_id: int) -> dict[str, Any]:
    if target == "host":
        return await host_summary(fog, target_id)
    return await group_summary(fog, target_id)
