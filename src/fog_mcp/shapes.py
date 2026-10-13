"""Compact projections of FOG objects, so tool output stays readable for the model."""

from __future__ import annotations

from typing import Any

from fog_mcp.client import sanitize

HOST_FIELDS = (
    "id", "name", "description", "mac", "ip", "imageID", "imagename",
    "pingstatus", "lastcheckin", "deployed", "pending", "task",
)
IMAGE_FIELDS = (
    "id", "name", "description", "path", "size", "osID", "os", "imagetype",
    "imageTypeID", "isEnabled", "protected", "deployed",
)
GROUP_FIELDS = ("id", "name", "description", "hosts")
TASK_FIELDS = (
    "id", "name", "hostID", "host", "typeID", "type", "stateID", "state",
    "imageID", "image", "percent", "pct", "timeElapsed", "timeRemaining",
    "checkInTime", "scheduledStartTime", "isForced", "shutdown", "wol",
)
MULTICAST_FIELDS = (
    "id", "name", "image", "imagename", "clients", "sessclients", "percent",
    "stateID", "state", "starttime", "completetime", "interface", "port", "isDD",
)


def _flatten(value: Any) -> Any:
    """Collapse an inlined related object to its id/name."""
    if isinstance(value, dict) and ("name" in value or "id" in value):
        return {k: value[k] for k in ("id", "name") if k in value}
    return value


def pick(obj: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(obj, dict):
        return {}
    obj = sanitize(obj)
    return {k: _flatten(obj[k]) for k in fields if k in obj and obj[k] not in (None, "")}


def group_summary(group: dict[str, Any]) -> dict[str, Any]:
    out = pick(group, GROUP_FIELDS)
    hosts = out.pop("hosts", None)
    if isinstance(hosts, list):
        out["host_count"] = len(hosts)
    return out


def page_summary(body: dict[str, Any], fields: tuple[str, ...], start: int) -> dict[str, Any]:
    rows = body.get("data") or []
    items = [pick(row, fields) for row in rows]
    total = body.get("recordsFiltered", body.get("recordsTotal"))
    out: dict[str, Any] = {"total": total, "start": start, "returned": len(items), "items": items}
    if body.get("nextUrl"):
        out["next_start"] = start + len(items)
    if body.get("truncated"):
        out["truncated"] = True
    return out
