import ssl

import pytest

from fog_mcp.config import DEFAULT_DESTRUCTIVE_TASK_TYPES, ConfigError, Settings

ENV = {"FOG_URL": "https://fog.lan/fog/", "FOG_API_TOKEN": "fog_abc"}


def test_defaults_are_read_only_and_verify_tls():
    s = Settings.from_env(ENV)
    assert s.url == "https://fog.lan/fog"
    assert s.allow_write is False
    assert s.ssl_verify() is True
    assert s.destructive_task_types == DEFAULT_DESTRUCTIVE_TASK_TYPES


@pytest.mark.parametrize("missing", ["FOG_URL", "FOG_API_TOKEN"])
def test_required(missing):
    env = {k: v for k, v in ENV.items() if k != missing}
    with pytest.raises(ConfigError, match=missing):
        Settings.from_env(env)


def test_write_flag():
    assert Settings.from_env({**ENV, "FOG_MCP_ALLOW_WRITE": "1"}).allow_write is True
    with pytest.raises(ConfigError):
        Settings.from_env({**ENV, "FOG_MCP_ALLOW_WRITE": "maybe"})


def test_ca_bundle_builds_ssl_context(tmp_path):
    import certifi

    ca = tmp_path / "ca.pem"
    ca.write_text(open(certifi.where()).read())
    s = Settings.from_env({**ENV, "FOG_CA_BUNDLE": str(ca), "FOG_VERIFY_TLS": "0"})
    ctx = s.ssl_verify()
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_missing_ca_bundle(tmp_path):
    with pytest.raises(ConfigError, match="FOG_CA_BUNDLE"):
        Settings.from_env({**ENV, "FOG_CA_BUNDLE": str(tmp_path / "nope.pem")})


def test_verify_can_be_disabled_explicitly():
    assert Settings.from_env({**ENV, "FOG_VERIFY_TLS": "0"}).ssl_verify() is False


def test_destructive_override():
    s = Settings.from_env({**ENV, "FOG_MCP_DESTRUCTIVE_TASK_TYPES": "1, 18"})
    assert s.destructive_task_types == {1, 18}
