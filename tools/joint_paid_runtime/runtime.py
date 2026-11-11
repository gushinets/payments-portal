"""Bounded local pair: two private Compose PostgreSQLs and real TCP app processes.

Run with Portal's .venv. No builds, pulls, installation or existing-volume cleanup.
The context owns only its unpredictable Compose projects and temporary directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import signal
import socket
import subprocess
import tempfile
from contextlib import ExitStack
from pathlib import Path
from time import monotonic, sleep
from types import TracebackType

import httpx
import psycopg
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.engine import URL, make_url

PORTAL = Path(__file__).resolve().parents[2]
KERNEL = Path(
    os.environ.get("ANY766_KERNEL_ROOT", PORTAL.parent / "anytoolai-platform")
)
TOOLS = Path(__file__).resolve().parent
PRODUCTS = (
    "proposal_ai",
    "client_update_writer",
    "brief_decoder",
    "acceptance_builder",
)
TIMEOUT = 90


class SubscriptionIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    provider_id: int


class JointIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    user_id: str
    token: str = Field(repr=False)
    foreign_token: str = Field(repr=False)
    subscriptions: dict[str, SubscriptionIdentity]


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class JointRuntime:
    def __init__(self, *, browser: bool = False) -> None:
        self.browser = browser
        self.stack = ExitStack()
        self.processes: dict[str, subprocess.Popen[bytes]] = {}
        self.ports = {
            name: free_port()
            for name in (
                "portal_api",
                "kernel_api",
                "lbx",
                "portal_web",
                "kernel_web",
                "kernel_peer",
                "summary",
            )
        }
        self.origins = {
            name: f"http://127.0.0.1:{port}" for name, port in self.ports.items()
        }

    def command(
        self,
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        name: str,
        timeout: int = TIMEOUT,
    ) -> None:
        log = self.run / f"{name}.log"
        with log.open("ab") as output:
            result = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
        if result.returncode:
            raise RuntimeError(f"Joint command {name} failed; see {log}")

    def start(
        self, name: str, command: list[str], cwd: Path, env: dict[str, str]
    ) -> None:
        output = self.stack.enter_context((self.run / f"{name}.log").open("ab"))
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.processes[name] = process
        self.stack.callback(self.stop, name)

    def stop(self, name: str) -> None:
        process = self.processes[name]
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(5)

    def wait(self, url: str, *, name: str) -> None:
        deadline = monotonic() + TIMEOUT
        with httpx.Client(trust_env=False, timeout=2) as client:
            while monotonic() < deadline:
                if name in self.processes and self.processes[name].poll() is not None:
                    raise RuntimeError(
                        f"Joint process {name} exited; see {self.run / (name + '.log')}"
                    )
                try:
                    if client.get(url).status_code < 500:
                        return
                except httpx.TransportError:
                    pass
                sleep(0.1)
        raise RuntimeError(f"Joint process {name} did not become ready")

    def compose(self, owner: str, *arguments: str) -> None:
        root = PORTAL if owner == "portal" else KERNEL
        compose = (
            "docker-compose.yml"
            if owner == "portal"
            else "infra/compose/docker-compose.yml"
        )
        self.command(
            [
                "docker",
                "compose",
                "--project-name",
                self.project + "-" + owner,
                "--env-file",
                str(self.run / (owner + ".env")),
                "-f",
                compose,
                *arguments,
            ],
            cwd=root,
            env=self.env,
            name=owner + "-compose",
        )

    def database(self, owner: str) -> str:
        port = free_port()
        password = secrets.token_urlsafe(32)
        prefix = "POSTGRES" if owner == "portal" else "ANYTOOLAI_POSTGRES"
        path = self.run / (owner + ".env")
        path.write_text(
            f"{prefix}_USER=joint\n{prefix}_PASSWORD={password}\n"
            f"{prefix}_DB=joint_{owner}_tests\n{prefix}_PORT={port}\n"
        )
        path.chmod(0o600)
        # Also clean a partially started, uniquely named project after startup failure.
        self.stack.callback(
            self.compose, owner, "down", "--volumes", "--remove-orphans"
        )
        self.compose(owner, "up", "-d", "--pull", "never", "--wait", "postgres")
        # A socket healthcheck can briefly see the image's initialization server.
        # Migrations need the final server to accept actual host TCP connections.
        deadline = monotonic() + TIMEOUT
        while True:
            try:
                with psycopg.connect(
                    host="127.0.0.1",
                    port=port,
                    user="joint",
                    password=password,
                    dbname=f"joint_{owner}_tests",
                    connect_timeout=2,
                ) as connection:
                    connection.execute("SELECT 1")
                break
            except psycopg.OperationalError:
                if monotonic() >= deadline:
                    raise
                sleep(0.1)
        return URL.create(
            "postgresql+psycopg",
            username="joint",
            password=password,
            host="127.0.0.1",
            port=port,
            database=f"joint_{owner}_tests",
        ).render_as_string(hide_password=False)

    def kernel_command(self, role: str) -> list[str]:
        return [
            str(KERNEL / ".quick-check-venv/bin/python"),
            str(TOOLS / "kernel.py"),
            role,
        ]

    def portal_command(self, role: str, *arguments: str) -> list[str]:
        return [
            str(PORTAL / ".venv/bin/python"),
            str(TOOLS / "portal.py"),
            role,
            *arguments,
        ]

    def __enter__(self) -> JointRuntime:
        # Keep logs on failure for diagnosis; clean only run-owned resources, never global Docker state.
        self.run = Path(tempfile.mkdtemp(prefix="any766-joint-"))
        self.run.chmod(0o700)
        self.project = self.run.name
        sources = {}
        for root in (PORTAL, KERNEL):
            revision = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True
            ).strip()
            diff = subprocess.check_output(["git", "diff", "HEAD"], cwd=root)
            sources[root.name] = {
                "revision": revision,
                "tracked_diff_sha256": hashlib.sha256(diff).hexdigest(),
            }
        (self.run / "sources.json").write_text(json.dumps(sources, indent=2))
        self.env = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "HOME", "LANG", "DOCKER_HOST", "XDG_RUNTIME_DIR"}
        }
        self.env.update(
            ANY766_RUN_DIR=str(self.run),
            LITELLM_LOCAL_MODEL_COST_MAP="True",
            OTEL_SDK_DISABLED="true",
            SENTRY_DSN="",
            SENTRY_RELEASE="",
            CI="true",  # Next must fail rather than install missing dependencies.
            WATCHPACK_POLLING="1000",  # Avoid consuming the shared host's watcher budget.
        )
        try:
            self.portal_url = self.database("portal")
            self.kernel_url = self.database("kernel")
            portal_database = make_url(self.portal_url)
            # Credentials are synthetic and unique by direction/consumer, never inherited.
            consumers = []
            for consumer, origin, products in (
                ("platform-kernel", self.origins["kernel_web"], PRODUCTS),
                ("synthetic-summary", self.origins["summary"], ("synthetic_summary",)),
            ):
                consumers.append(
                    dict(
                        consumer_id=consumer,
                        tenant_id="anytoolai",
                        region="ru",
                        consumer_policy_revision=1,
                        allowed_products=products,
                        permissions=[
                            "backend-session:exchange",
                            "backend-session:introspect",
                            "access-snapshot:read",
                            "allowance-exhaustion:write",
                        ],
                        callback_url=origin + "/portal-session/callback",
                        backend_base_url=(
                            self.origins["kernel_api"]
                            if consumer == "platform-kernel"
                            else origin
                        ),
                        technical_source_id=consumer,
                        backend_to_portal_current_secret="joint-"
                        + consumer
                        + "-backend-"
                        + "b" * 32,
                        portal_to_backend_current_secret="joint-"
                        + consumer
                        + "-portal-"
                        + "p" * 32,
                    )
                )
            # The browser callback and API may use different ports; BackendConsumer requires
            # one backend origin, so Kernel web proxies its internal routes to the real API.
            consumers[0]["callback_url"] = (
                self.origins["kernel_api"] + "/portal-session/callback"
            )
            if self.browser:
                consumers[0]["backend_base_url"] = self.origins["kernel_peer"]
                consumers[0]["callback_url"] = (
                    self.origins["kernel_peer"] + "/portal-session/callback"
                )
            self.consumers = consumers
            self.portal_env = {
                **self.env,
                "PYTHONPATH": str(PORTAL / "apps/api") + os.pathsep + str(PORTAL),
                "APP_ENV": "test",
                "INSTANCE_TENANT_ID": "anytoolai",
                "INSTANCE_REGION": "ru",
                "APP_PUBLIC_BASE_URL": self.origins["portal_web"],
                "DATABASE_URL": self.portal_url,
                "POSTGRES_DB": "joint_portal_tests",
                "POSTGRES_USER": "joint",
                "POSTGRES_PASSWORD": portal_database.password,
                "POSTGRES_HOST": "127.0.0.1",
                "POSTGRES_PORT": str(portal_database.port),
                "CORS_ALLOW_ORIGINS": self.origins["portal_web"],
                "KERNEL_MOCK_ENABLED": "false",
                "KERNEL_BASE_URL": consumers[0]["backend_base_url"],
                "KERNEL_SERVICE_TOKEN": consumers[0][
                    "portal_to_backend_current_secret"
                ],
                "BACKEND_CONSUMERS": json.dumps(consumers),
                "LBX_BASE_URL": self.origins["lbx"],
                "LBX_SERVER_USERNAME": "synthetic-user",
                "LBX_SERVER_PASSWORD": "synthetic-password",
                "LBX_WIDGET_SIGNING_SECRET": "joint-disposable-widget-secret",
                "LBX_SELLER_ORGANIZATION_ID": "21",
                "LBX_CURRENCY_ID": "1",
                "LBX_CURRENCY": "RUB",
                "BILLING_WORKER_ENABLED": "true",
                "ANY766_LBX_PORT": str(self.ports["lbx"]),
                "PAID_ACCESS_CLOCK_SKEW_SECONDS": "5",
            }
            self.portal_env.update(
                ANY766_SUMMARY_PORT=str(self.ports["summary"]),
                ANY766_PORTAL_ORIGIN=self.origins["portal_api"],
                ANY766_BROWSER=str(self.browser).lower(),
            )
            self.kernel_env = {
                **self.env,
                "ANYTOOLAI_DATABASE_URL": self.kernel_url,
                "ANYTOOLAI_ENABLED_PRODUCT_IDS": ",".join(PRODUCTS),
                "ANYTOOLAI_PORTAL_BASE_URL": self.origins["portal_api"],
                "ANYTOOLAI_PORTAL_SERVICE_TOKEN": consumers[0][
                    "portal_to_backend_current_secret"
                ],
                "ANYTOOLAI_PORTAL_ACCESS_SERVICE_TOKEN": consumers[0][
                    "backend_to_portal_current_secret"
                ],
                "ANYTOOLAI_PORTAL_ACCESS_INVALIDATION_ENABLED": "true",
                "ANYTOOLAI_PORTAL_USAGE_READ_ENABLED": "true",
                "ANYTOOLAI_PORTAL_EXHAUSTION_DELIVERY_ENABLED": "true",
                "ANYTOOLAI_APP_ENV": "test",
                "ANYTOOLAI_API_CORS_ORIGINS": self.origins["kernel_peer"],
                "ANY766_KERNEL_API_PORT": str(self.ports["kernel_api"]),
            }
            self.command(
                self.kernel_command("prepare"),
                cwd=KERNEL,
                env=self.kernel_env,
                name="profile",
            )
            self.command(
                self.kernel_command("migrate"),
                cwd=KERNEL,
                env=self.kernel_env,
                name="kernel-migrate",
            )
            self.command(
                [
                    str(PORTAL / ".venv/bin/python"),
                    "-m",
                    "alembic",
                    "-c",
                    "apps/api/alembic.ini",
                    "upgrade",
                    "head",
                ],
                cwd=PORTAL,
                env=self.portal_env,
                name="portal-migrate",
            )
            self.start("lbx", self.portal_command("lbx"), PORTAL, self.portal_env)
            self.wait(self.origins["lbx"] + "/openapi.json", name="lbx")
            self.start(
                "summary",
                [str(PORTAL / ".venv/bin/python"), str(TOOLS / "summary.py")],
                PORTAL,
                self.portal_env,
            )
            self.wait(self.origins["summary"] + "/openapi.json", name="summary")
            self.start(
                "kernel-api", self.kernel_command("api"), KERNEL, self.kernel_env
            )
            self.wait(self.origins["kernel_api"] + "/health", name="kernel-api")
            if self.browser:
                self.start_web()
            self.command(
                self.portal_command("seed"),
                cwd=PORTAL,
                env=self.portal_env,
                name="seed",
            )
            self.identity = JointIdentity.model_validate_json(
                (self.run / "identity.json").read_text()
            )
            self.start(
                "portal-api",
                [
                    str(PORTAL / ".venv/bin/python"),
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(self.ports["portal_api"]),
                    "--no-access-log",
                    "--log-level",
                    "warning",
                ],
                PORTAL,
                self.portal_env,
            )
            self.wait(
                self.origins["portal_api"] + "/api/auth/session", name="portal-api"
            )
            self.start(
                "kernel-worker", self.kernel_command("worker"), KERNEL, self.kernel_env
            )
            return self
        except BaseException:
            self.stack.close()
            raise

    def start_web(self) -> None:
        # pnpm may expose Node types only beside Next's peer dependencies.
        # Resolve that existing copy; do not install or change node_modules.
        node_types = subprocess.check_output(
            [
                "node",
                "-e",
                "const p=require('node:path');const next=require.resolve('next/package.json',"
                "{paths:[process.cwd()+'/apps/web-mirror']});const types=require.resolve('@types/node/package.json',"
                "{paths:[p.dirname(next)]});process.stdout.write(p.dirname(p.dirname(p.dirname(types))));",
            ],
            cwd=KERNEL,
            env=self.env,
            text=True,
            timeout=10,
        )
        portal_env = {
            **self.portal_env,
            "NEXT_PUBLIC_API_BASE_URL": self.origins["portal_api"],
            "NEXT_PUBLIC_KERNEL_WEB_BASE_URL": self.origins["kernel_peer"],
            "NEXT_TELEMETRY_DISABLED": "1",
        }
        kernel_env = {
            **self.env,
            "NODE_PATH": node_types,
            "PLATFORM_API_BASE_URL": self.origins["kernel_api"],
            "NEXT_PUBLIC_PORTAL_AUTHORIZE_URL": self.origins["portal_web"]
            + "/ru/backend/authorize",
            "NEXT_TELEMETRY_DISABLED": "1",
        }
        self.start(
            "kernel-web",
            [
                "node",
                str(KERNEL / "apps/web-mirror/node_modules/next/dist/bin/next"),
                "dev",
                "--hostname",
                "127.0.0.1",
                "--port",
                str(self.ports["kernel_web"]),
            ],
            KERNEL / "apps/web-mirror",
            kernel_env,
        )
        self.wait(
            self.origins["kernel_web"] + "/portal-session/launch", name="kernel-web"
        )
        peer_env = {
            **self.portal_env,
            "ANY766_KERNEL_API_ORIGIN": self.origins["kernel_api"],
            "ANY766_KERNEL_WEB_ORIGIN": self.origins["kernel_web"],
            "ANY766_PEER_PORT": str(self.ports["kernel_peer"]),
        }
        self.start(
            "kernel-peer",
            [str(PORTAL / ".venv/bin/python"), str(TOOLS / "peer.py")],
            PORTAL,
            peer_env,
        )
        self.wait(self.origins["kernel_peer"] + "/health", name="kernel-peer")
        self.start(
            "portal-web",
            [
                "node",
                str(PORTAL / "node_modules/next/dist/bin/next"),
                "dev",
                "--webpack",
                "--hostname",
                "127.0.0.1",
                "--port",
                str(self.ports["portal_web"]),
            ],
            PORTAL / "apps/web",
            portal_env,
        )
        self.wait(self.origins["portal_web"] + "/ru/account", name="portal-web")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stack.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    with JointRuntime(browser=args.browser) as runtime:
        print(
            f"Joint runtime ready; private configuration/logs: {runtime.run}",
            flush=True,
        )
        if args.browser:
            environment = {
                **os.environ,
                "PLAYWRIGHT_BASE_URL": runtime.origins["portal_web"],
                "PLAYWRIGHT_API_BASE_URL": runtime.origins["portal_api"],
                "ANY766_KERNEL_WEB_ORIGIN": runtime.origins["kernel_peer"],
                "ANY766_JOINT_IDENTITY": str(runtime.run / "identity.json"),
            }
            raise SystemExit(
                subprocess.call(
                    [
                        "npm",
                        "run",
                        "test:e2e:joint",
                    ],
                    cwd=PORTAL,
                    env=environment,
                )
            )


if __name__ == "__main__":
    main()
