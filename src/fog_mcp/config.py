"""Configuration read from environment variables."""

from __future__ import annotations

import os
import ssl
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

# Defaults from FOG's stock taskTypes table: the API spec does not enumerate them.
# 1 deploy, 2 capture, 8 multicast, 15 deploy-debug, 16 capture-debug,
# 17 deploy without snapins, 18/19/20 fast/normal/full wipe.
DEFAULT_DESTRUCTIVE_TASK_TYPES = frozenset({1, 2, 8, 15, 16, 17, 18, 19, 20})

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class ConfigError(ValueError):
    """Invalid or missing configuration."""


def _flag(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise ConfigError(f"{name} must be 0/1 (got {raw!r})")


def _int_set(env: Mapping[str, str], name: str, default: frozenset[int]) -> frozenset[int]:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        return frozenset(int(part) for part in raw.split(",") if part.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} must be a comma separated list of integers") from exc


@dataclass(frozen=True)
class Settings:
    url: str
    token: str
    ca_bundle: Path | None = None
    verify_tls: bool = True
    allow_write: bool = False
    destructive_task_types: frozenset[int] = field(default=DEFAULT_DESTRUCTIVE_TASK_TYPES)
    timeout: float = 30.0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env

        url = env.get("FOG_URL", "").strip().rstrip("/")
        if not url:
            raise ConfigError("FOG_URL is required (e.g. https://fog.example.lan/fog)")
        if not url.startswith(("http://", "https://")):
            raise ConfigError("FOG_URL must start with http:// or https://")

        token = env.get("FOG_API_TOKEN", "").strip()
        if not token:
            raise ConfigError("FOG_API_TOKEN is required (fog_... token from the user's API tab)")

        ca_bundle = None
        if raw_ca := env.get("FOG_CA_BUNDLE", "").strip():
            ca_bundle = Path(raw_ca).expanduser()
            if not ca_bundle.is_file():
                raise ConfigError(f"FOG_CA_BUNDLE not found: {ca_bundle}")

        try:
            timeout = float(env.get("FOG_TIMEOUT", "30") or 30)
        except ValueError as exc:
            raise ConfigError("FOG_TIMEOUT must be a number of seconds") from exc

        return cls(
            url=url,
            token=token,
            ca_bundle=ca_bundle,
            verify_tls=_flag(env, "FOG_VERIFY_TLS", True),
            allow_write=_flag(env, "FOG_MCP_ALLOW_WRITE", False),
            destructive_task_types=_int_set(
                env, "FOG_MCP_DESTRUCTIVE_TASK_TYPES", DEFAULT_DESTRUCTIVE_TASK_TYPES
            ),
            timeout=timeout,
        )

    def ssl_verify(self) -> ssl.SSLContext | bool:
        """Value for httpx's ``verify``: a CA bundle wins over FOG_VERIFY_TLS=0."""
        if self.ca_bundle is not None:
            return ssl.create_default_context(cafile=str(self.ca_bundle))
        return self.verify_tls
