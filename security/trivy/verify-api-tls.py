"""Controlled TLS checks against the actual outbound pools; run inside the API image.

Usage: PYTHONPATH=apps/api python security/trivy/verify-api-tls.py
No credentials, external network, installed bundle edits or persistent keys are used.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import ssl
import subprocess
import sys
import tempfile
from pathlib import Path


def handshake(client_context: ssl.SSLContext, server_context: ssl.SSLContext, hostname: str) -> None:
    client_in, client_out = ssl.MemoryBIO(), ssl.MemoryBIO()
    server_in, server_out = ssl.MemoryBIO(), ssl.MemoryBIO()
    client = client_context.wrap_bio(client_in, client_out, server_hostname=hostname)
    server = server_context.wrap_bio(server_in, server_out, server_side=True)
    client_done = server_done = False
    for _ in range(20):
        if not client_done:
            try:
                client.do_handshake()
                client_done = True
            except ssl.SSLWantReadError:
                pass
        server_in.write(client_out.read())
        if not server_done:
            try:
                server.do_handshake()
                server_done = True
            except ssl.SSLWantReadError:
                pass
        client_in.write(server_out.read())
        if client_done and server_done:
            return
    raise AssertionError("TLS handshake did not finish")


def rejected(context: ssl.SSLContext, server: ssl.SSLContext, hostname: str, code: int) -> None:
    try:
        handshake(context, server, hostname)
    except ssl.SSLCertVerificationError as error:
        assert error.verify_code == code, (error.verify_code, error.verify_message)
    else:
        raise AssertionError("Invalid peer certificate was accepted")


async def main() -> None:
    # Isolated synthetic configuration, including before the settings singleton import.
    os.environ.update(
        APP_ENV="test",
        INSTANCE_TENANT_ID="anytoolai",
        INSTANCE_REGION="ru",
        APP_PUBLIC_BASE_URL="http://localhost:3000",
        DATABASE_URL="sqlite+pysqlite:///:memory:",
        POSTGRES_DB="anytoolai_test",
        POSTGRES_USER="anytoolai",
        POSTGRES_PASSWORD="simulated",
        POSTGRES_HOST="localhost",
        POSTGRES_PORT="5432",
        CORS_ALLOW_ORIGINS="http://localhost:3000",
        SKIP_LEGAL_SEED="true",
        BILLING_WORKER_ENABLED="false",
        OTEL_SDK_DISABLED="true",
        SENTRY_DSN="",
        SENTRY_RELEASE="",
        KERNEL_BASE_URL="https://localhost",
        KERNEL_SERVICE_TOKEN="simulated-kernel-token",
        LBX_BASE_URL="https://localhost",
        LBX_SERVER_USERNAME="simulated",
        LBX_SERVER_PASSWORD="simulated",
        LBX_WIDGET_SIGNING_SECRET="simulated",
        LBX_SELLER_ORGANIZATION_ID="21",
    )
    import certifi
    from app.core.settings import Settings
    from app.domains.catalog.contracts import SourceProvenance
    from app.integrations.kernel.client import PlatformKernelClient
    from app.integrations.lbx.client import LbxServerClient

    configuration = Settings(_env_file=None)
    kernel = PlatformKernelClient(configuration, provenance=SourceProvenance.SIMULATED)
    lbx = LbxServerClient(configuration)
    pools = {"kernel": kernel._http, "lbx-source": lbx._http, "lbx-account": lbx._account_http}
    bundle = Path(certifi.where())
    expected = ssl.create_default_context(cafile=str(bundle)).get_ca_certs(binary_form=True)
    try:
        with tempfile.TemporaryDirectory(prefix="portal-tls-") as directory:
            certificate, key = Path(directory) / "peer.pem", Path(directory) / "peer.key"
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-days",
                    "1",
                    "-subj",
                    "/CN=localhost",
                    "-addext",
                    "subjectAltName=DNS:localhost",
                    "-keyout",
                    str(key),
                    "-out",
                    str(certificate),
                ],
                check=True,
                capture_output=True,
            )
            server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server.load_cert_chain(certificate, key)
            for name, pool in pools.items():
                # Intentionally inspect the pinned HTTPX/httpcore pool: this is the
                # context actually used on connections, not an independently built client.
                context = pool._transport._pool._ssl_context
                assert context.verify_mode == ssl.CERT_REQUIRED
                assert context.check_hostname
                assert set(context.get_ca_certs(binary_form=True)) == set(expected)
                rejected(context, server, "localhost", 18)  # self-signed / untrusted
                # Add only to this disposable in-memory context; never edit certifi.
                context.load_verify_locations(cafile=str(certificate))
                handshake(context, server, "localhost")
                rejected(context, server, "wrong-host.test", 62)  # hostname mismatch
                print(
                    f"{name}: certifi bundle matched; untrusted rejected; trusted accepted; hostname mismatch rejected"
                )
    finally:
        for pool in pools.values():
            await pool.aclose()
    print(
        json.dumps(
            {
                "certifi": certifi.__version__,
                "bundle": str(bundle),
                "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
                "emsign_g3_present": "emSign ECC Root CA - G3" in bundle.read_text(),
            }
        )
    )
    if "--require-patched" in sys.argv:
        assert tuple(map(int, certifi.__version__.split("."))) >= (2026, 10, 19)
        assert "emSign ECC Root CA - G3" not in bundle.read_text()


if __name__ == "__main__":
    asyncio.run(main())
