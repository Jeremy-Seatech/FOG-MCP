"""Real TLS handshakes against a PKI shaped like an upgraded FOG server.

FOG 1.6 keeps the root CA created by the 1.5 installer (``openssl req -x509`` with the
distro openssl.cnf: basicConstraints critical CA:TRUE, SKI/AKI, but no keyUsage) and
signs the web certificate with a "FOG Web CA" intermediate under it.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import socket
import ssl
import threading
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from fog_mcp.config import Settings

ENV = {"FOG_URL": "https://127.0.0.1/fog", "FOG_API_TOKEN": "fog_abc"}


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _cert(subject, key, issuer, issuer_key, extensions) -> x509.Certificate:
    now = dt.datetime.now(dt.timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(subject))
        .issuer_name(_name(issuer))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), critical=False
        )
    )
    for ext, critical in extensions:
        builder = builder.add_extension(ext, critical=critical)
    return builder.sign(issuer_key, hashes.SHA256())


CA_KEY_USAGE = x509.KeyUsage(
    digital_signature=False, content_commitment=False, key_encipherment=False, data_encipherment=False,
    key_agreement=False, key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False,
)
LEAF_KEY_USAGE = x509.KeyUsage(
    digital_signature=True, content_commitment=False, key_encipherment=False, data_encipherment=False,
    key_agreement=False, key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False,
)


def _pem(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


@pytest.fixture
def fog_pki(tmp_path: Path):
    """Write root.pem (no keyUsage, like FOG 1.5) plus a server chain; return paths."""
    root_key, int_key, leaf_key = (ec.generate_private_key(ec.SECP256R1()) for _ in range(3))
    root = _cert(
        "FOG Server CA", root_key, "FOG Server CA", root_key,
        [(x509.BasicConstraints(ca=True, path_length=None), True)],
    )
    inter = _cert(
        "FOG Web CA", int_key, "FOG Server CA", root_key,
        [(x509.BasicConstraints(ca=True, path_length=0), True), (CA_KEY_USAGE, True)],
    )
    leaf = _cert(
        "127.0.0.1", leaf_key, "FOG Web CA", int_key,
        [
            (x509.BasicConstraints(ca=False, path_length=None), True),
            (LEAF_KEY_USAGE, True),
            (x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False),
            (x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False),
        ],
    )
    assert not any(isinstance(e.value, x509.KeyUsage) for e in root.extensions)

    (tmp_path / "root.pem").write_bytes(_pem(root))
    (tmp_path / "chain.pem").write_bytes(_pem(leaf) + _pem(inter))
    (tmp_path / "leaf.key").write_bytes(
        leaf_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    return tmp_path


def _handshake(server_dir: Path, client_ctx: ssl.SSLContext, hostname: str = "127.0.0.1") -> None:
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(server_dir / "chain.pem", server_dir / "leaf.key")
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]

    def serve() -> None:
        conn, _ = listener.accept()
        try:
            with server_ctx.wrap_socket(conn, server_side=True):
                pass
        except (ssl.SSLError, OSError):
            pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
            with client_ctx.wrap_socket(raw, server_hostname=hostname):
                pass
    finally:
        thread.join(timeout=5)
        listener.close()


def test_upgraded_fog_root_without_key_usage_is_accepted(fog_pki):
    ctx = Settings.from_env({**ENV, "FOG_CA_BUNDLE": str(fog_pki / "root.pem")}).ssl_verify()
    assert isinstance(ctx, ssl.SSLContext)
    assert not ctx.verify_flags & ssl.VERIFY_X509_STRICT
    _handshake(fog_pki, ctx)


def test_unrelated_ca_is_still_rejected(fog_pki, tmp_path_factory):
    other = tmp_path_factory.mktemp("other")
    other_key = ec.generate_private_key(ec.SECP256R1())
    other_root = _cert(
        "Other CA", other_key, "Other CA", other_key,
        [(x509.BasicConstraints(ca=True, path_length=None), True), (CA_KEY_USAGE, True)],
    )
    (other / "root.pem").write_bytes(_pem(other_root))
    ctx = Settings.from_env({**ENV, "FOG_CA_BUNDLE": str(other / "root.pem")}).ssl_verify()
    with pytest.raises(ssl.SSLCertVerificationError):
        _handshake(fog_pki, ctx)


def test_wrong_ip_is_still_rejected(fog_pki):
    ctx = Settings.from_env({**ENV, "FOG_CA_BUNDLE": str(fog_pki / "root.pem")}).ssl_verify()
    with pytest.raises(ssl.SSLCertVerificationError, match="IP address mismatch"):
        _handshake(fog_pki, ctx, hostname="10.9.88.101")


@pytest.mark.skipif(
    not ssl.create_default_context().verify_flags & ssl.VERIFY_X509_STRICT,
    reason="this Python does not enable VERIFY_X509_STRICT by default (< 3.13)",
)
def test_strict_default_would_reject_it(fog_pki):
    """Documents the failure the fix addresses."""
    ctx = ssl.create_default_context(cafile=str(fog_pki / "root.pem"))
    with pytest.raises(ssl.SSLCertVerificationError, match="key usage"):
        _handshake(fog_pki, ctx)
