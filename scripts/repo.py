#!/usr/bin/env python3
"""Cross-platform repository and agent harness for Payment Portal."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tomllib
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Iterable


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
API_LOCK = API_DIR / "uv.lock"
REPOSITORY_VENV = ROOT / ".venv"
HARNESS_DIR = ROOT / ".harness"
RUNTIME_JSON = HARNESS_DIR / "runtime.json"
RUNTIME_ENV = HARNESS_DIR / "runtime.env"
LEGAL_DIR = ROOT / "docs" / "legal" / "ru" / "2026-07-11"
LEGAL_MANIFEST = LEGAL_DIR / "manifest.json"
GENERATED_DB = ROOT / "docs" / "generated" / "db-schema.md"
GENERATED_OPENAPI = ROOT / "docs" / "generated" / "openapi.json"
GENERATED_TOKENS = ROOT / "apps" / "web" / "src" / "app" / "tokens.generated.css"
GENERATED_LEGAL_PY = ROOT / "apps" / "api" / "app" / "generated" / "legal_manifest.py"
GENERATED_LEGAL_JSON = ROOT / "apps" / "web" / "src" / "generated" / "legal-manifest.json"
REGISTRATION_ACCEPTANCE_TEXT_SOURCE = (
    ROOT / "apps" / "api" / "app" / "domains" / "legal" / "acceptance_text.py"
)
GENERATED_REGISTRATION_ACCEPTANCE_TS = (
    ROOT / "apps" / "web" / "src" / "generated" / "registration-acceptance.ts"
)
API_TEST_PATH = "apps/api/tests"
LEGAL_DOCS_ROOT = ROOT / "docs" / "legal" / "ru"
LOCAL_INSTANCE_TENANT_ID = "anytoolai"
LOCAL_INSTANCE_REGION = "ru"

CANONICAL_PERSISTED_ENUM_NAMES = frozenset(
    {
        "AcceptanceKind",
        "BillingStateObservationKind",
        "ExternalBillingCustomerBindingState",
        "ExternalCreateOperationKind",
        "ExternalSubscriptionCommercialAccessStatus",
        "ExternalSubscriptionFinancialAccessStatus",
        "ExternalSubscriptionLifecycleStatus",
        "LegalEntityStatus",
        "LegalEntityType",
        "MagicLinkPurpose",
        "PurchaseIntentState",
        "RegionStatus",
        "UserStatus",
    }
)
REMOVED_BILLING_ENUM_FACADE_NAMES = CANONICAL_PERSISTED_ENUM_NAMES | {
    "BillingPeriod",
    "BundleProductStatus",
    "BundleStatus",
    "CheckoutSessionStatus",
    "EntitlementSource",
    "EntitlementStatus",
    "OrderItemType",
    "OrderStatus",
    "PaymentStatus",
    "PaymentWebhookEventStatus",
    "PlanLimitOveragePolicy",
    "PlanLimitResetPolicy",
    "PlanPriceComponentType",
    "PlanStatus",
    "ProductStatus",
    "RefundStatus",
    "SubscriptionEventType",
    "SubscriptionRenewalMode",
    "SubscriptionScopeType",
    "SubscriptionStatus",
    "WebhookEventStatus",
}
REMOVED_LEGACY_PERSISTED_ENUM_NAMES = (
    REMOVED_BILLING_ENUM_FACADE_NAMES - CANONICAL_PERSISTED_ENUM_NAMES
)


class HarnessError(RuntimeError):
    pass


@dataclass(frozen=True)
class PythonImport:
    line: int
    targets: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeConfig:
    worktree_id: str
    compose_project: str
    web_port: int
    api_port: int
    postgres_port: int
    grafana_port: int
    loki_port: int
    prometheus_port: int
    tempo_port: int
    otlp_grpc_port: int
    otlp_http_port: int
    database_name: str


@dataclass(frozen=True)
class TrivyGateSummary:
    report: str
    critical_vulnerabilities: int
    fixable_high_vulnerabilities: int
    high_or_critical_misconfigurations: int
    high_or_critical_secrets: int

    @property
    def blocking_findings(self) -> int:
        return (
            self.critical_vulnerabilities
            + self.fixable_high_vulnerabilities
            + self.high_or_critical_misconfigurations
            + self.high_or_critical_secrets
        )


def run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    check: bool = True,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    display = subprocess.list2cmdline(command)
    print(f"+ {display}")
    return subprocess.run(
        command,
        cwd=cwd,
        check=check,
        text=True,
        capture_output=capture,
        env=env,
    )


def tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise HarnessError(f"Required executable is missing: {name}")
    return path


def python_312_executable() -> str:
    if sys.version_info[:2] != (3, 12):
        raise HarnessError(
            "Python 3.12 is required for repository-managed API operations; "
            f"found {sys.version.split()[0]}"
        )
    return str(Path(sys.executable).resolve())


def uv_environment(
    *,
    environ: dict[str, str] | None = None,
    project_environment: Path | None = None,
    python: str | None = None,
) -> dict[str, str]:
    """Build the environment for every repository-managed uv subprocess."""
    environment = dict(os.environ if environ is None else environ)
    environment.pop("VIRTUAL_ENV", None)
    environment["UV_PROJECT_ENVIRONMENT"] = str(
        (project_environment or (ROOT / ".venv")).resolve()
    )
    environment["UV_PYTHON"] = python or python_312_executable()
    environment["UV_PYTHON_DOWNLOADS"] = "never"
    return environment


def runtime_config(port_offset: int = 0, *, root: Path = ROOT) -> RuntimeConfig:
    canonical = str(root.resolve()).replace("\\", "/").lower()
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    slot = (int(digest[:8], 16) % 700) + port_offset
    if not 0 <= slot <= 999:
        raise HarnessError("Port offset places the worktree outside the supported range")
    worktree_id = digest[:8]
    return RuntimeConfig(
        worktree_id=worktree_id,
        compose_project=f"payments-{worktree_id}",
        web_port=30000 + slot,
        api_port=31000 + slot,
        postgres_port=32000 + slot,
        grafana_port=33000 + slot,
        loki_port=34000 + slot,
        prometheus_port=35000 + slot,
        tempo_port=36000 + slot,
        otlp_grpc_port=37000 + slot,
        otlp_http_port=38000 + slot,
        database_name=f"payments_{worktree_id}",
    )


def canonical_check_environment(
    *, root: Path = ROOT, environ: dict[str, str] | None = None
) -> dict[str, str]:
    environment = dict(os.environ if environ is None else environ)
    temp_dir = (root / ".harness" / "tmp").resolve()
    temp_dir.mkdir(parents=True, exist_ok=True)
    for variable in ("TEMP", "TMP", "TMPDIR"):
        environment[variable] = str(temp_dir)
    environment["OTEL_EXPORTER_OTLP_ENDPOINT"] = ""
    environment["INSTANCE_TENANT_ID"] = LOCAL_INSTANCE_TENANT_ID
    environment["INSTANCE_REGION"] = LOCAL_INSTANCE_REGION
    return environment


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def runtime_caddy_port(config: RuntimeConfig) -> int:
    return config.otlp_http_port + 1000


def read_dotenv(path: Path = ROOT / ".env") -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def is_loopback_hostname(hostname: str) -> bool:
    normalized_hostname = hostname.strip().lower()
    if normalized_hostname == "localhost" or normalized_hostname.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized_hostname).is_loopback
    except ValueError:
        return False


def validate_production_caddy_domain(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        raise HarnessError("CADDY_DOMAIN is required")
    if "://" in candidate:
        raise HarnessError("CADDY_DOMAIN must not include a URL scheme")

    parsed = urllib.parse.urlparse(f"//{candidate}")
    if (
        not parsed.hostname
        or parsed.path
        or parsed.params
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or parsed.port is not None
    ):
        raise HarnessError("CADDY_DOMAIN must be a bare public hostname")
    if is_loopback_hostname(parsed.hostname):
        raise HarnessError("CADDY_DOMAIN must not use a loopback host in production")
    return candidate


def validate_production_deployment_environment(*, environ: dict[str, str] | None = None) -> None:
    environment = os.environ if environ is None else environ
    validate_production_caddy_domain(environment.get("CADDY_DOMAIN", ""))


def protect_private_directory(
    path: Path,
    *,
    os_name: str | None = None,
    environ: dict[str, str] | None = None,
    runner: Callable[[list[str]], object] = run,
    icacls_path: str | None = None,
) -> None:
    if (os.name if os_name is None else os_name) != "nt":
        path.chmod(0o700)
        return

    protect_windows_path_acl(
        path,
        permission="(OI)(CI)F",
        failure_message="Failed to protect harness directory ACLs on Windows",
        environ=environ,
        runner=runner,
        icacls_path=icacls_path,
    )


def windows_current_user(*, environ: dict[str, str] | None = None) -> str:
    environment = os.environ if environ is None else environ
    username = environment.get("USERNAME") or environment.get("USER")
    if not username:
        raise HarnessError("Cannot protect runtime.env on Windows: current user is unknown")
    domain = environment.get("USERDOMAIN")
    computer = environment.get("COMPUTERNAME")
    if domain and domain != computer:
        return f"{domain}\\{username}"
    return username


def protect_windows_path_acl(
    path: Path,
    *,
    permission: str,
    failure_message: str,
    environ: dict[str, str] | None = None,
    runner: Callable[[list[str]], object] = run,
    icacls_path: str | None = None,
) -> None:
    principal = windows_current_user(environ=environ)
    command = [
        icacls_path or tool("icacls"),
        str(path),
        "/inheritance:r",
        "/grant:r",
        f"{principal}:{permission}",
    ]
    try:
        runner(command)
    except (HarnessError, OSError, subprocess.CalledProcessError) as exc:
        raise HarnessError(failure_message) from exc


def protect_runtime_env_file(
    path: Path,
    *,
    os_name: str | None = None,
    environ: dict[str, str] | None = None,
    runner: Callable[[list[str]], object] = run,
    icacls_path: str | None = None,
) -> None:
    if (os.name if os_name is None else os_name) != "nt":
        path.chmod(0o600)
        return

    protect_windows_path_acl(
        path,
        permission="RW",
        failure_message="Failed to protect runtime.env ACLs on Windows",
        environ=environ,
        runner=runner,
        icacls_path=icacls_path,
    )


def write_protected_runtime_env_file(path: Path, contents: str) -> None:
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary_path.write_text("", encoding="utf-8")
        protect_runtime_env_file(temporary_path)
        temporary_path.write_text(contents, encoding="utf-8")
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def write_runtime(config: RuntimeConfig) -> None:
    HARNESS_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    protect_private_directory(HARNESS_DIR)
    RUNTIME_JSON.write_text(json.dumps(asdict(config), indent=2) + "\n", encoding="utf-8")
    caddy_origin = f"http://localhost:{runtime_caddy_port(config)}"
    local_env = read_dotenv()
    app_public_base_url = local_env.get("APP_PUBLIC_BASE_URL", caddy_origin)
    cors_allow_origins = caddy_origin
    if app_public_base_url != caddy_origin:
        cors_allow_origins = f"{caddy_origin},{app_public_base_url}"
    values = {
        "COMPOSE_PROJECT_NAME": config.compose_project,
        "APP_ENV": "development",
        "INSTANCE_TENANT_ID": LOCAL_INSTANCE_TENANT_ID,
        "INSTANCE_REGION": LOCAL_INSTANCE_REGION,
        "POSTGRES_DB": config.database_name,
        "POSTGRES_USER": "anytoolai",
        "POSTGRES_PASSWORD": "anytoolai-local-only",
        "POSTGRES_HOST": "postgres",
        "POSTGRES_PORT": str(config.postgres_port),
        "DATABASE_URL": (
            f"postgresql+psycopg://anytoolai:anytoolai-local-only@postgres:5432/"
            f"{config.database_name}"
        ),
        "WEB_PORT": str(config.web_port),
        "API_PORT": str(config.api_port),
        "CADDY_PORT": str(runtime_caddy_port(config)),
        "NEXT_PUBLIC_API_BASE_URL": caddy_origin,
        "CORS_ALLOW_ORIGINS": cors_allow_origins,
        "APP_PUBLIC_BASE_URL": app_public_base_url,
        "SMTP_HOST": local_env.get("SMTP_HOST", ""),
        "SMTP_PORT": local_env.get("SMTP_PORT", "587"),
        "SMTP_USERNAME": local_env.get("SMTP_USERNAME", ""),
        "SMTP_PASSWORD": local_env.get("SMTP_PASSWORD", ""),
        "SMTP_FROM_EMAIL": local_env.get("SMTP_FROM_EMAIL", "support@any-tool-ai.ru"),
        "SMTP_USE_TLS": local_env.get("SMTP_USE_TLS", "true"),
        "GRAFANA_PORT": str(config.grafana_port),
        "LOKI_PORT": str(config.loki_port),
        "PROMETHEUS_PORT": str(config.prometheus_port),
        "TEMPO_PORT": str(config.tempo_port),
        "OTLP_GRPC_PORT": str(config.otlp_grpc_port),
        "OTLP_HTTP_PORT": str(config.otlp_http_port),
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://observability:4318",
        "OTEL_SERVICE_NAME": "payment-portal-api",
    }
    write_protected_runtime_env_file(
        RUNTIME_ENV,
        "".join(f"{key}={value}\n" for key, value in values.items()),
    )


def compose_command(config: RuntimeConfig) -> list[str]:
    return [
        tool("docker"),
        "compose",
        "--project-name",
        config.compose_project,
        "--env-file",
        str(RUNTIME_ENV),
        "-f",
        str(ROOT / "docker-compose.yml"),
        "-f",
        str(ROOT / "docker-compose.agent.yml"),
    ]


def cmd_doctor(_: argparse.Namespace) -> None:
    failures: list[str] = []
    commands = (
        ["git", "--version"],
        ["python", "--version"],
        ["uv", "--version"],
        ["node", "--version"],
        ["npm", "--version"],
        ["docker", "--version"],
    )
    for command in commands:
        try:
            executable = tool(command[0])
            result = run([executable, *command[1:]], capture=True)
            output = (result.stdout or result.stderr).strip()
            print(output)
            if command[0] == "python" and sys.version_info[:2] != (3, 12):
                failures.append(
                    "Python 3.12 is required for the repository; "
                    f"found {sys.version.split()[0]}"
                )
            if command[0] == "uv":
                required_version = tomllib.loads(
                    (ROOT / "apps/api/pyproject.toml").read_text(encoding="utf-8")
                )["tool"]["uv"]["required-version"]
                installed_match = re.search(r"\buv\s+(\d+\.\d+\.\d+)", output)
                if not installed_match or required_version != f"=={installed_match.group(1)}":
                    failures.append(
                        f"Installed uv does not satisfy apps/api/pyproject.toml "
                        f"required-version {required_version!r}"
                    )
        except (HarnessError, subprocess.CalledProcessError) as exc:
            failures.append(str(exc))
    try:
        run([tool("docker"), "compose", "version"], capture=True)
    except (HarnessError, subprocess.CalledProcessError) as exc:
        failures.append(str(exc))
    required = [
        ROOT / ".env.example",
        ROOT / "package-lock.json",
        ROOT / "apps/api/pyproject.toml",
        API_LOCK,
    ]
    for path in required:
        if not path.exists():
            failures.append(f"Missing required file: {path.relative_to(ROOT)}")
    conflicting_venv = API_DIR / ".venv"
    if conflicting_venv.exists():
        failures.append(
            "Conflicting API environment found at apps/api/.venv; "
            "repository tooling uses .venv and will not delete either environment"
        )
    if REPOSITORY_VENV.exists():
        print(f"Canonical API environment: {REPOSITORY_VENV.relative_to(ROOT)}")
    else:
        print("Canonical API environment: .venv (will be created by repo:setup)")
    config = runtime_config()
    busy = [port for port in runtime_ports(config) if not port_is_free(port)]
    if busy:
        failures.append(
            f"Preferred ports are busy: {busy}. Use repo.py up --port-offset <n>."
        )
    if failures:
        raise HarnessError("Environment diagnostic failed:\n- " + "\n- ".join(failures))
    print(json.dumps(asdict(config), indent=2))
    print("Environment diagnostic passed.")


def runtime_ports(config: RuntimeConfig) -> Iterable[int]:
    return (
        config.web_port,
        config.api_port,
        runtime_caddy_port(config),
        config.postgres_port,
        config.grafana_port,
        config.loki_port,
        config.prometheus_port,
        config.tempo_port,
        config.otlp_grpc_port,
        config.otlp_http_port,
    )


def cmd_setup(_: argparse.Namespace) -> None:
    python_312_executable()
    tool("uv")
    tool("npm")
    sync_api()
    run([tool("npm"), "ci"])
    run([tool("npm"), "run", "playwright:install"])
    config = runtime_config()
    write_runtime(config)
    print(f"Setup complete for worktree {config.worktree_id}.")


def api_uv_command(action: str, *arguments: str) -> list[str]:
    return [tool("uv"), action, "--directory", str(API_DIR), *arguments]


def sync_api() -> None:
    run(
        api_uv_command("sync", "--locked", "--dev"),
        env=uv_environment(),
    )


def cmd_sync_api(_: argparse.Namespace) -> None:
    sync_api()


def cmd_lock_api(_: argparse.Namespace) -> None:
    run(api_uv_command("lock"), env=uv_environment())


def cmd_check_api_lock(_: argparse.Namespace) -> None:
    run(api_uv_command("lock", "--check"), env=uv_environment())


def cmd_up(args: argparse.Namespace) -> None:
    config = runtime_config(args.port_offset)
    busy = [port for port in runtime_ports(config) if not port_is_free(port)]
    if busy and not args.reuse:
        raise HarnessError(
            f"Ports are busy: {busy}. If this worktree already runs, pass --reuse; "
            "otherwise choose --port-offset."
        )
    write_runtime(config)
    run([*compose_command(config), "up", "-d", "--build"])
    print(json.dumps(asdict(config), indent=2))


def load_runtime() -> RuntimeConfig:
    if not RUNTIME_JSON.exists():
        config = runtime_config()
        write_runtime(config)
        return config
    return RuntimeConfig(**json.loads(RUNTIME_JSON.read_text(encoding="utf-8")))


def cmd_down(_: argparse.Namespace) -> None:
    config = load_runtime()
    run([*compose_command(config), "down"])


def cmd_test_db(args: argparse.Namespace) -> None:
    config = load_runtime()
    write_runtime(config)
    if args.action == "up":
        run([*compose_command(config), "up", "-d", "--no-deps", "--wait", "postgres"])
        return
    run([*compose_command(config), "stop", "postgres"])


def cmd_reset(args: argparse.Namespace) -> None:
    config = load_runtime()
    expected = f"payments-{config.worktree_id}"
    if config.compose_project != expected or not config.database_name.startswith("payments_"):
        raise HarnessError("Refusing reset: runtime state is not harness-scoped")
    if args.confirm != config.worktree_id:
        raise HarnessError(f"Refusing reset: pass --confirm {config.worktree_id}")
    run([*compose_command(config), "down", "--volumes", "--remove-orphans"])
    print("Current worktree runtime state was removed.")


def normalize_legal_markdown(raw: str) -> str:
    source = raw.replace("\r\n", "\n")
    if source.startswith("---"):
        closing = source.find("\n---", 3)
        if closing >= 0:
            source = source[closing + 4 :]
    return source.strip()


def computed_legal_manifest() -> dict:
    manifest = json.loads(LEGAL_MANIFEST.read_text(encoding="utf-8"))
    for document in manifest["documents"]:
        source = (LEGAL_DIR / document["file"]).read_text(encoding="utf-8")
        normalized = normalize_legal_markdown(source)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        document["contentHash"] = f"sha256:{digest}"
    return manifest


def render_legal_python(manifest: dict) -> str:
    return (
        '"""Generated by scripts/repo.py legal generate. Do not edit."""\n\n'
        f"LEGAL_MANIFEST = {repr(manifest)}\n"
    )


def render_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def write_or_check(path: Path, content: str, *, check: bool) -> bool:
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    if existing == content:
        return False
    if check:
        print(f"Generated artifact is stale: {path.relative_to(ROOT)}")
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    print(f"Updated {path.relative_to(ROOT)}")
    return True


def generate_legal(*, check: bool) -> bool:
    manifest = computed_legal_manifest()
    stale = write_or_check(LEGAL_MANIFEST, render_json(manifest), check=check)
    stale |= write_or_check(GENERATED_LEGAL_JSON, render_json(manifest), check=check)
    stale |= write_or_check(GENERATED_LEGAL_PY, render_legal_python(manifest), check=check)
    return stale


def import_api() -> tuple[object, object]:
    api_root = str(ROOT / "apps" / "api")
    if api_root not in sys.path:
        sys.path.insert(0, api_root)
    os.environ.setdefault("APP_ENV", "test")
    os.environ["INSTANCE_TENANT_ID"] = LOCAL_INSTANCE_TENANT_ID
    os.environ["INSTANCE_REGION"] = LOCAL_INSTANCE_REGION
    os.environ.setdefault("APP_PUBLIC_BASE_URL", "http://localhost:3000")
    os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    os.environ.setdefault("POSTGRES_DB", "anytoolai")
    os.environ.setdefault("POSTGRES_USER", "anytoolai")
    os.environ.setdefault("POSTGRES_PASSWORD", "anytoolai")
    os.environ.setdefault("POSTGRES_HOST", "postgres")
    os.environ.setdefault("POSTGRES_PORT", "5432")
    os.environ.setdefault("CORS_ALLOW_ORIGINS", "http://localhost:3000")
    os.environ.setdefault("SKIP_LEGAL_SEED", "true")
    from app.core.database import Base  # type: ignore
    from app.main import app as fastapi_app  # type: ignore
    importlib.import_module("app.models")

    return Base, fastapi_app


def render_db_schema() -> str:
    Base, _ = import_api()
    lines = [
        "# Generated Database Schema",
        "",
        "Generated from SQLAlchemy metadata. Do not edit directly.",
        "",
    ]
    for table in sorted(Base.metadata.tables.values(), key=lambda item: item.name):
        lines.extend([f"## `{table.name}`", "", "| Column | Type | Nullable | Key |", "|---|---|---:|---|"])
        for column in table.columns:
            key = "PK" if column.primary_key else "FK" if column.foreign_keys else ""
            lines.append(f"| `{column.name}` | `{column.type}` | {'yes' if column.nullable else 'no'} | {key} |")
        if table.constraints or table.indexes:
            lines.extend(["", "Indexes and constraints:", ""])
            for constraint in sorted((item for item in table.constraints if getattr(item, "name", None)), key=lambda item: item.name):
                lines.append(f"- `{constraint.name}`")
            for index in sorted(table.indexes, key=lambda item: item.name):
                lines.append(f"- `{index.name}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_openapi() -> str:
    _, app = import_api()
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_tokens() -> str:
    values = json.loads((ROOT / "docs/design-system/bundle3/tokens.json").read_text(encoding="utf-8"))
    colors = values["colors"]
    gradients = values["gradients"]
    layout = values["layout"]
    return "\n".join(
        [
            "/* Generated from docs/design-system/bundle3/tokens.json. Do not edit. */",
            ":root {",
            f"  --bg: {colors['background'].lower()};",
            f"  --bg2: {colors['backgroundSecondary'].lower()};",
            f"  --bg3: {colors['backgroundTertiary'].lower()};",
            f"  --surf1: {colors['surfaceCard']};",
            f"  --surf2: {colors['surfaceHover']};",
            f"  --surf3: {colors['surfaceActive']};",
            f"  --border: {colors['border']};",
            f"  --border2: {colors['borderStrong']};",
            f"  --txt: {colors['text'].lower()};",
            f"  --txt2: {colors['textSecondary']};",
            f"  --txt3: {colors['textDisabled']};",
            f"  --acc: {colors['accent'].lower()};",
            f"  --acc2: {colors['accentDeep'].lower()};",
            f"  --acc-glow: {colors['accentGlow']};",
            f"  --teal: {colors['teal'].lower()};",
            f"  --teal-glow: {colors['tealGlow']};",
            f"  --green: {colors['success'].lower()};",
            f"  --green-bg: {colors['successBackground']};",
            f"  --green-bdr: {colors['successBorder']};",
            f"  --red: {colors['error'].lower()};",
            f"  --red-bg: {colors['errorBackground']};",
            f"  --amber: {colors['warning'].lower()};",
            f"  --acc-grad: {gradients['accent']};",
            f"  --headline-grad: {gradients['headline']};",
            f"  --max: {layout['maxWidth']};",
            "}",
            "",
        ]
    )


def registration_acceptance_texts() -> dict[str, str]:
    required_names = {
        "REGISTRATION_PERSONAL_CONSENT_TEXT",
        "REGISTRATION_OFFER_CONSENT_TEXT",
    }
    tree = ast.parse(
        REGISTRATION_ACCEPTANCE_TEXT_SOURCE.read_text(encoding="utf-8"),
        filename=str(REGISTRATION_ACCEPTANCE_TEXT_SOURCE),
    )
    values: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in required_names:
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, TypeError) as error:
            raise HarnessError(
                f"Registration acceptance text must be a string literal: {target.id}"
            ) from error
        if not isinstance(value, str):
            raise HarnessError(
                f"Registration acceptance text must be a string literal: {target.id}"
            )
        values[target.id] = value

    missing = sorted(required_names - values.keys())
    if missing:
        raise HarnessError(
            "Missing canonical registration acceptance text: " + ", ".join(missing)
        )
    return values


def render_registration_acceptance_typescript() -> str:
    values = registration_acceptance_texts()
    lines = [
        "// Generated from apps/api/app/domains/legal/acceptance_text.py. Do not edit.",
        "",
    ]
    for name in (
        "REGISTRATION_PERSONAL_CONSENT_TEXT",
        "REGISTRATION_OFFER_CONSENT_TEXT",
    ):
        lines.append(
            f"export const {name} = {json.dumps(values[name], ensure_ascii=False)} as const;"
        )
    lines.append("")
    return "\n".join(lines)


def generate_all(*, check: bool) -> bool:
    stale = generate_legal(check=check)
    stale |= write_or_check(GENERATED_DB, render_db_schema(), check=check)
    stale |= write_or_check(GENERATED_OPENAPI, render_openapi(), check=check)
    stale |= write_or_check(GENERATED_TOKENS, render_tokens(), check=check)
    stale |= write_or_check(
        GENERATED_REGISTRATION_ACCEPTANCE_TS,
        render_registration_acceptance_typescript(),
        check=check,
    )
    return stale


def cmd_generate(args: argparse.Namespace) -> None:
    stale = generate_all(check=args.check)
    if args.check and stale:
        raise HarnessError("Generated artifacts are stale; run npm run generate")


def cmd_legal(args: argparse.Namespace) -> None:
    stale = generate_legal(check=args.action == "check")
    if args.action == "check" and stale:
        raise HarnessError("Legal generated artifacts are stale")


MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
CURRENT_LEGAL_VERSION = re.compile(
    r"Current RU legal source version:\s*`([^`]+)`"
)
MIGRATION_LEGAL_VERSION = re.compile(r'"version":\s*"([^"]+)"')
GENERATED_PY_LEGAL_VERSION = re.compile(r"'version':\s*'([^']+)'")
CANONICAL_METADATA_TABLE_ENTRY = re.compile(
    r"^\|\s*`(?P<table>[^`|]+)`\s*\|\s*[^|\n]+\|\s*[^|\n]+\|\s*$",
    re.MULTILINE,
)
TOP_LEVEL_STATUS = re.compile(r"^Status:[^\r\n]*$", re.IGNORECASE | re.MULTILINE)
LEVEL_2_HEADING = re.compile(r"^##(?:[ \t]+|$)", re.MULTILINE)
INITIAL_MIGRATION = (
    ROOT
    / "apps"
    / "api"
    / "alembic"
    / "versions"
    / "20260924_0001_clean_first_install.py"
)
EXTERNAL_BILLING_ADR = (
    ROOT
    / "docs"
    / "architecture"
    / "decisions"
    / "0005-external-billing-boundary.md"
)
EXTERNAL_BILLING_DESIGN = (
    ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-09-15-external-billing-boundary-design.md"
)
PORTAL_KERNEL_ACCESS_DESIGN = (
    ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-09-15-portal-kernel-access-contract-design.md"
)
EXTERNAL_BILLING_AUTHORITY_CHAIN = (
    EXTERNAL_BILLING_ADR,
    EXTERNAL_BILLING_DESIGN,
    PORTAL_KERNEL_ACCESS_DESIGN,
)
CORE_AUTHORITY_LINKS = {
    ROOT / "AGENTS.md": (
        ROOT / "README.md",
        ROOT / "ARCHITECTURE.md",
        ROOT / "docs" / "PRODUCT.md",
        ROOT / "docs" / "architecture" / "contours.md",
        ROOT / "docs" / "architecture" / "region-resolver-contract.md",
        ROOT / "docs" / "architecture" / "payment-providers.md",
        ROOT / "docs" / "architecture" / "payment-portal-data-model.md",
        *EXTERNAL_BILLING_AUTHORITY_CHAIN,
        ROOT / "docs" / "product" / "ru-mvp.md",
        ROOT / "docs" / "DESIGN.md",
        ROOT / "docs" / "SECURITY.md",
        ROOT / "docs" / "RELIABILITY.md",
        ROOT / "docs" / "engineering" / "AGENT_WORKFLOW.md",
        ROOT / "docs" / "engineering" / "CODING_CONVENTIONS.md",
        ROOT / "docs" / "exec-plans",
    ),
    ROOT / "docs" / "README.md": (
        ROOT / "ARCHITECTURE.md",
        ROOT / "docs" / "PRODUCT.md",
        ROOT / "docs" / "product" / "ru-mvp.md",
        ROOT / "docs" / "DESIGN.md",
        ROOT / "docs" / "architecture" / "contours.md",
        ROOT / "docs" / "architecture" / "region-resolver-contract.md",
        ROOT / "docs" / "architecture" / "payment-providers.md",
        ROOT / "docs" / "architecture" / "payment-portal-data-model.md",
        *EXTERNAL_BILLING_AUTHORITY_CHAIN,
        ROOT / "docs" / "engineering" / "AGENT_WORKFLOW.md",
        ROOT / "docs" / "engineering" / "CODING_CONVENTIONS.md",
        ROOT / "docs" / "RELIABILITY.md",
        ROOT / "docs" / "SECURITY.md",
        ROOT / "docs" / "legal" / "README.md",
        ROOT / "docs" / "exec-plans" / "README.md",
    ),
    ROOT / "README.md": EXTERNAL_BILLING_AUTHORITY_CHAIN,
    ROOT / "apps" / "api" / "AGENTS.md": EXTERNAL_BILLING_AUTHORITY_CHAIN,
    ROOT / "ARCHITECTURE.md": EXTERNAL_BILLING_AUTHORITY_CHAIN,
    ROOT / "docs" / "PRODUCT.md": EXTERNAL_BILLING_AUTHORITY_CHAIN,
    ROOT / "docs" / "RELIABILITY.md": EXTERNAL_BILLING_AUTHORITY_CHAIN,
    ROOT / "docs" / "architecture" / "contours.md": (
        *EXTERNAL_BILLING_AUTHORITY_CHAIN,
    ),
    ROOT / "docs" / "architecture" / "payment-providers.md": (
        EXTERNAL_BILLING_ADR,
        EXTERNAL_BILLING_DESIGN,
    ),
    ROOT / "docs" / "architecture" / "decisions" / "0001-multi-contour-billing.md": (
        EXTERNAL_BILLING_ADR,
    ),
    ROOT
    / "docs"
    / "architecture"
    / "decisions"
    / "0002-plan-based-checkout-identity.md": (
        EXTERNAL_BILLING_ADR,
    ),
    ROOT
    / "docs"
    / "architecture"
    / "decisions"
    / "0004-billing-authority-and-consistency.md": (
        EXTERNAL_BILLING_ADR,
    ),
    ROOT / "docs" / "architecture" / "decisions" / "README.md": (
        EXTERNAL_BILLING_ADR,
    ),
    ROOT / "docs" / "architecture" / "billing-authority.md": (
        *EXTERNAL_BILLING_AUTHORITY_CHAIN,
    ),
    ROOT / "docs" / "architecture" / "payment-portal-data-model.md": (
        EXTERNAL_BILLING_ADR,
        EXTERNAL_BILLING_DESIGN,
    ),
    ROOT / "docs" / "architecture" / "platform-kernel-contract.md": (
        EXTERNAL_BILLING_ADR,
        PORTAL_KERNEL_ACCESS_DESIGN,
    ),
    ROOT / "docs" / "engineering" / "CODING_CONVENTIONS.md": (
        *EXTERNAL_BILLING_AUTHORITY_CHAIN,
    ),
}

SUPERSEDED_BILLING_PLANS = (
    "ANY-165-payment-provider-boundary.md",
    "ANY-166-cloudpayments-browser-checkout-adapter.md",
    "ANY-167-cloudpayments-notification-adapter.md",
    "ANY-78-subscriptions-entitlements.md",
)


def engineering_markdown_files() -> Iterable[Path]:
    yield ROOT / "README.md"
    yield ROOT / "AGENTS.md"
    yield ROOT / "ARCHITECTURE.md"
    for path in (ROOT / "docs").rglob("*.md"):
        if LEGAL_DOCS_ROOT in path.parents:
            continue
        yield path
    for subtree in (ROOT / "apps" / "api", ROOT / "apps" / "web"):
        yield from subtree.rglob("AGENTS.md")


def resolved_markdown_links(source: Path, content: str, *, root: Path) -> set[Path]:
    resolved: set[Path] = set()
    for target in MARKDOWN_LINK.findall(content):
        clean = target.split("#", 1)[0].strip()
        if not clean or clean.startswith(("http://", "https://", "mailto:")):
            continue
        candidate = (source.parent / urllib.parse.unquote(clean)).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            continue
        resolved.add(candidate)
    return resolved


def check_required_markdown_link_content(
    source: Path,
    content: str,
    required: Iterable[Path],
    *,
    root: Path,
) -> list[str]:
    linked = resolved_markdown_links(source, content, root=root)
    return [
        (
            f"Missing core authority link in {source.relative_to(root)}: "
            f"{target.relative_to(root)}"
        )
        for target in required
        if target.resolve() not in linked
    ]


def check_required_markdown_links(
    source: Path, required: Iterable[Path], *, root: Path = ROOT
) -> list[str]:
    if not source.exists():
        return []
    return check_required_markdown_link_content(
        source,
        source.read_text(encoding="utf-8"),
        required,
        root=root,
    )


def markdown_header_region(content: str) -> str:
    heading = LEVEL_2_HEADING.search(content)
    return content if heading is None else content[: heading.start()]


def normalized_top_level_statuses(content: str) -> list[str]:
    return [
        " ".join(match.group(0).lower().split())
        for match in TOP_LEVEL_STATUS.finditer(markdown_header_region(content))
    ]


def check_external_billing_documentation_precedence(
    *, root: Path = ROOT
) -> list[str]:
    required_statuses = {
        Path("docs/architecture/decisions/0005-external-billing-boundary.md"): (
            "status: accepted"
        ),
        Path(
            "docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md"
        ): "status: accepted implementation baseline",
        Path(
            "docs/superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md"
        ): "status: accepted implementation baseline",
        Path("docs/architecture/decisions/0002-plan-based-checkout-identity.md"): (
            "status: superseded for new billing development"
        ),
        Path(
            "docs/architecture/decisions/0004-billing-authority-and-consistency.md"
        ): "status: superseded for new billing development",
        Path("docs/architecture/billing-authority.md"): (
            "status: historical/superseded reference only; not current-state "
            "or target authority"
        ),
        Path("docs/architecture/payment-providers.md"): (
            "status: historical boundary reference; direct-provider runtime removed"
        ),
        Path("docs/architecture/payment-portal-data-model.md"): (
            "status: authoritative current-state schema reference"
        ),
        Path("docs/architecture/platform-kernel-contract.md"): (
            "status: superseded planned contract; retained historical context only"
        ),
        Path("docs/RELIABILITY.md"): (
            "status: authoritative operational requirements; target "
            "external-billing semantics delegated"
        ),
        Path("docs/architecture/contours.md"): (
            "status: authoritative target architecture; implemented product remains `ru`"
        ),
        Path("docs/PRODUCT.md"): "status: authoritative",
    }

    required_header_markers = {
        Path("docs/architecture/billing-authority.md"): (
            "historical/superseded only — not current state or target authority",
            "does not describe the current repository or runtime",
        ),
        Path("docs/architecture/payment-providers.md"): (
            "removed direct-provider reference — not target architecture",
        ),
        Path("docs/architecture/payment-portal-data-model.md"): (
            "current as-built schema reference",
        ),
        Path("docs/architecture/platform-kernel-contract.md"): (
            "superseded contract notice",
        ),
    }

    required_document_markers = {
        Path("AGENTS.md"): (
            "for all new billing work, follow this target authority chain in order:",
        ),
        Path("docs/RELIABILITY.md"): (
            "target external-billing authority",
        ),
        Path("docs/architecture/contours.md"): (
            "target billing ownership authority:",
        ),
        Path("docs/PRODUCT.md"): (
            "target billing ownership and authoritative facts follow, in precedence order,",
        ),
    }

    stale_executable_authority_markers = {
        Path("docs/RELIABILITY.md"): (
            "any-497 external billing command flows and reconciliation remain future work",
        ),
        Path("docs/architecture/contours.md"): ("billing ownership: [adr 0004]",),
        Path("docs/PRODUCT.md"): (
            "private regional entitlement/access api for platform kernel is planned "
            "under any-79",
        ),
    }

    documents: dict[Path, str] = {}
    errors: list[str] = []
    required_documents = dict.fromkeys(
        (*required_statuses, *required_header_markers, *required_document_markers)
    )
    for relative in required_documents:
        path = root / relative
        rendered_path = path.relative_to(root).as_posix()
        if not path.exists():
            errors.append(
                f"Missing external-billing authority document: {rendered_path}"
            )
            continue
        documents[relative] = path.read_text(encoding="utf-8")

    for relative, expected_status in required_statuses.items():
        content = documents.get(relative)
        if content is None:
            continue
        statuses = normalized_top_level_statuses(content)
        if statuses != [expected_status]:
            rendered_statuses = (
                ", ".join(repr(status) for status in statuses) or "none"
            )
            errors.append(
                "Incorrect external-billing documentation classification in "
                f"{(root / relative).relative_to(root).as_posix()}: expected exactly "
                f"one active status {expected_status!r}, found {rendered_statuses}"
            )

    for relative, markers in required_header_markers.items():
        content = documents.get(relative)
        if content is None:
            continue
        normalized = " ".join(markdown_header_region(content).lower().split())
        for marker in markers:
            if marker not in normalized:
                errors.append(
                    "Incorrect external-billing documentation classification in "
                    f"{(root / relative).relative_to(root).as_posix()}: expected header "
                    f"marker {marker!r}"
                )

    for relative, markers in required_document_markers.items():
        content = documents.get(relative)
        if content is None:
            continue
        normalized = " ".join(content.lower().split())
        for marker in markers:
            if marker not in normalized:
                errors.append(
                    "Incorrect external-billing documentation classification in "
                    f"{(root / relative).relative_to(root).as_posix()}: expected "
                    f"document marker {marker!r}"
                )

    for relative, markers in stale_executable_authority_markers.items():
        path = root / relative
        if not path.exists():
            continue
        normalized = " ".join(path.read_text(encoding="utf-8").lower().split())
        for marker in markers:
            if marker in normalized:
                errors.append(
                    "Stale executable billing authority in "
                    f"{path.relative_to(root).as_posix()}: marker {marker!r}"
                )

    active = root / "docs/exec-plans/active"
    superseded = root / "docs/exec-plans/superseded"
    for filename in SUPERSEDED_BILLING_PLANS:
        active_plan = active / filename
        retained_plan = superseded / filename
        if active_plan.exists():
            errors.append(
                "Superseded billing execution plan must not remain active: "
                f"{active_plan.relative_to(root).as_posix()}"
            )
        if not retained_plan.exists():
            errors.append(
                "Missing retained superseded billing execution plan: "
                f"{retained_plan.relative_to(root).as_posix()}"
            )
    return errors


def check_expected_legal_versions(
    expected: str,
    sources: Iterable[tuple[str, Iterable[str], int]],
) -> list[str]:
    errors: list[str] = []
    for label, versions, expected_count in sources:
        found = list(versions)
        if len(found) != expected_count or set(found) != {expected}:
            rendered = ", ".join(found) if found else "none"
            errors.append(
                f"Current legal version mismatch in {label}: expected "
                f"{expected_count} occurrence(s) of {expected}, found {rendered}"
            )
    return errors


def check_documented_metadata_tables(table_names: Iterable[str], documented: str) -> list[str]:
    documented_tables = {
        match.group("table") for match in CANONICAL_METADATA_TABLE_ENTRY.finditer(documented)
    }
    return [
        f"Implemented table missing from canonical data model: {table}"
        for table in sorted(table_names)
        if table not in documented_tables
    ]


def check_knowledge_hierarchy() -> list[str]:
    errors: list[str] = []
    for source, required in CORE_AUTHORITY_LINKS.items():
        errors.extend(check_required_markdown_links(source, required))

    expected = LEGAL_DIR.name
    source_manifest = json.loads(LEGAL_MANIFEST.read_text(encoding="utf-8"))
    web_manifest_path = ROOT / "apps" / "web" / "src" / "generated" / "legal-manifest.json"
    web_manifest = json.loads(web_manifest_path.read_text(encoding="utf-8"))
    api_manifest_path = ROOT / "apps" / "api" / "app" / "generated" / "legal_manifest.py"
    version_sources = [
        (
            "docs/README.md",
            CURRENT_LEGAL_VERSION.findall(
                (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
            ),
            1,
        ),
        (
            "docs/legal/README.md",
            CURRENT_LEGAL_VERSION.findall(
                (ROOT / "docs" / "legal" / "README.md").read_text(encoding="utf-8")
            ),
            1,
        ),
        (
            str(LEGAL_MANIFEST.relative_to(ROOT)),
            [document["version"] for document in source_manifest["documents"]],
            6,
        ),
        (
            str(web_manifest_path.relative_to(ROOT)),
            [document["version"] for document in web_manifest["documents"]],
            6,
        ),
        (
            str(api_manifest_path.relative_to(ROOT)),
            GENERATED_PY_LEGAL_VERSION.findall(
                api_manifest_path.read_text(encoding="utf-8")
            ),
            6,
        ),
        (
            str(INITIAL_MIGRATION.relative_to(ROOT)),
            MIGRATION_LEGAL_VERSION.findall(
                INITIAL_MIGRATION.read_text(encoding="utf-8")
            ),
            6,
        ),
    ]
    errors.extend(check_expected_legal_versions(expected, version_sources))
    return errors


def check_docs() -> list[str]:
    errors: list[str] = []
    required = [
        ROOT / "AGENTS.md",
        ROOT / "ARCHITECTURE.md",
        ROOT / "docs/README.md",
        ROOT / "docs/architecture/payment-portal-data-model.md",
        ROOT / "docs/architecture/contours.md",
        ROOT / "docs/architecture/region-resolver-contract.md",
        ROOT / "docs/architecture/payment-providers.md",
        ROOT / "docs/product/ru-mvp.md",
    ]
    for path in required:
        if not path.exists():
            errors.append(f"Missing authoritative document: {path.relative_to(ROOT)}")
    errors.extend(check_knowledge_hierarchy())
    errors.extend(check_external_billing_documentation_precedence())
    for path in engineering_markdown_files():
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        if CYRILLIC.search(content):
            errors.append(f"Engineering Markdown must be English: {path.relative_to(ROOT)}")
        for target in MARKDOWN_LINK.findall(content):
            clean = target.split("#", 1)[0].strip()
            if not clean or clean.startswith(("http://", "https://", "mailto:")):
                continue
            candidate = (path.parent / urllib.parse.unquote(clean)).resolve()
            try:
                candidate.relative_to(ROOT.resolve())
            except ValueError:
                errors.append(f"Link leaves repository in {path.relative_to(ROOT)}: {target}")
                continue
            if not candidate.exists():
                errors.append(f"Broken link in {path.relative_to(ROOT)}: {target}")
    Base, _ = import_api()
    documented = (ROOT / "docs/architecture/payment-portal-data-model.md").read_text(encoding="utf-8")
    errors.extend(check_documented_metadata_tables(Base.metadata.tables, documented))
    if (ROOT / "docs/project").exists() and any((ROOT / "docs/project").iterdir()):
        errors.append("Superseded docs/project directory still contains files")
    return errors


def cmd_docs(_: argparse.Namespace) -> None:
    errors = check_docs()
    if errors:
        raise HarnessError("Documentation checks failed:\n- " + "\n- ".join(errors))
    print("Documentation checks passed.")


def python_module_for_path(path: Path, app_root: Path) -> tuple[str, bool]:
    parts = list(path.relative_to(app_root.parent).with_suffix("").parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    return ".".join(parts), is_package


def resolve_python_imports(path: Path, app_root: Path) -> list[PythonImport]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    current_module, is_package = python_module_for_path(path, app_root)
    current_package = current_module if is_package else current_module.rpartition(".")[0]
    imports: list[PythonImport] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(
                PythonImport(line=node.lineno, targets=(alias.name,))
                for alias in node.names
            )
            continue
        if not isinstance(node, ast.ImportFrom):
            continue

        if node.level:
            package_parts = current_package.split(".") if current_package else []
            keep = max(0, len(package_parts) - node.level + 1)
            base_parts = package_parts[:keep]
            if node.module:
                base_parts.extend(node.module.split("."))
            base = ".".join(base_parts)
        else:
            base = node.module or ""

        targets = [base] if base else []
        targets.extend(
            f"{base}.{alias.name}" if base else alias.name
            for alias in node.names
            if alias.name != "*"
        )
        imports.append(PythonImport(line=node.lineno, targets=tuple(targets)))

    return imports


def module_matches(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def router_module(module: str) -> bool:
    return module.endswith(".router") or ".router." in module


_REMOVED_API_COMPATIBILITY_PATHS = {
    Path("apps/api/app/auth.py"): (
        "app.auth",
        "the owning identity modules and app.http.dependencies",
    ),
    Path("apps/api/app/database.py"): ("app.database", "app.core.database"),
    Path("apps/api/app/legal.py"): ("app.legal", "app.domains.legal.router"),
    Path("apps/api/app/legal_consents.py"): (
        "app.legal_consents",
        "app.domains.legal.service",
    ),
    Path("apps/api/app/settings.py"): ("app.settings", "app.core.settings"),
    Path("apps/api/app/domains/identity/session.py"): (
        "app.domains.identity.session",
        "app.core.settings or app.domains.identity.services.auth",
    ),
    Path("apps/api/app/domains/identity/models.py"): (
        "app.domains.identity.models",
        "app.models",
    ),
    Path("apps/api/app/domains/legal/models.py"): (
        "app.domains.legal.models",
        "app.models",
    ),
    Path("apps/api/app/domains/identity/services/account.py"): (
        "app.domains.identity.services.account",
        "the authenticated app.models.User",
    ),
    Path("apps/api/app/health.py"): ("app.health", "app.http.health"),
    Path("apps/api/app/http_dependencies.py"): (
        "app.http_dependencies",
        "app.http.dependencies",
    ),
    Path("apps/api/app/http_errors.py"): ("app.http_errors", "app.http.errors"),
}


def check_removed_api_compatibility(root: Path = ROOT) -> list[str]:
    """Reject removed post-reset compatibility modules and their imports."""
    errors: list[str] = []
    removed_modules = {
        module: replacement
        for module, replacement in _REMOVED_API_COMPATIBILITY_PATHS.values()
    }

    for relative, (module, replacement) in _REMOVED_API_COMPATIBILITY_PATHS.items():
        if (root / relative).exists():
            errors.append(
                f"{relative.as_posix()} is a removed compatibility path; "
                f"import from {replacement} instead of {module}"
            )

    for source_root in (root / "apps/api", root / "scripts"):
        if not source_root.exists():
            continue
        for path in sorted(source_root.rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                targets: set[str] = set()
                if isinstance(node, ast.Import):
                    targets.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    module = node.module or ""
                    if module:
                        targets.add(module)
                        targets.update(
                            f"{module}.{alias.name}"
                            for alias in node.names
                            if alias.name != "*"
                        )
                else:
                    continue

                imported_removed_modules = {
                    removed_module
                    for target in targets
                    for removed_module in removed_modules
                    if module_matches(target, removed_module)
                }
                for removed_module in sorted(imported_removed_modules):
                    errors.append(
                        f"{relative}:{node.lineno} imports removed compatibility module "
                        f"{removed_module}; import from "
                        f"{removed_modules[removed_module]} instead"
                    )

    return errors


_REMOVED_LEGACY_MODEL_NAMES = frozenset(
    {
        "Bundle",
        "BundleProduct",
        "CheckoutSession",
        "Entitlement",
        "EntrypointSession",
        "Order",
        "OrderItem",
        "Payment",
        "PaymentProviderAccount",
        "PaymentWebhookEvent",
        "Plan",
        "PlanLimit",
        "PlanPriceComponent",
        "Product",
        "ProductAccessState",
        "Refund",
        "Subscription",
        "SubscriptionEvent",
        "Trial",
    }
)
_REMOVED_LEGACY_TABLE_NAMES = frozenset(
    {
        "bundle_products",
        "bundles",
        "checkout_sessions",
        "entitlements",
        "entrypoint_sessions",
        "order_items",
        "orders",
        "payment_provider_accounts",
        "payment_webhook_events",
        "payments",
        "plan_limits",
        "plan_price_components",
        "plans",
        "product_access_states",
        "products",
        "refunds",
        "subscription_events",
        "subscriptions",
        "trials",
    }
)
_REMOVED_DIRECT_PROVIDER_MODULES = (
    "app.cloudpayments",
    "app.integrations.cloudpayments",
    "app.payment_providers",
)
_REMOVED_DIRECT_PROVIDER_NAMES = frozenset(
    {"PaymentProviderAdapter", "PaymentProviderRegistry"}
)
_IDENTITY_RECOVERY_PATHS = frozenset(
    {
        ("domains", "identity", "password_reset.py"),
        ("domains", "identity", "passwords.py"),
        ("domains", "identity", "session.py"),
        ("domains", "identity", "services", "auth.py"),
        ("domains", "identity", "services", "password_reset.py"),
        ("infrastructure", "persistence", "identity.py"),
        ("infrastructure", "persistence", "password_reset.py"),
        ("infrastructure", "queries", "identity.py"),
    }
)
_IDENTITY_RECOVERY_FORBIDDEN_MODEL_NAMES = frozenset(
    {"EntrypointSession", "Product", "Plan", "Subscription", "Entitlement"}
)
_IDENTITY_RECOVERY_FORBIDDEN_NAMES = _IDENTITY_RECOVERY_FORBIDDEN_MODEL_NAMES | {
    "PaymentProviderAdapter",
    "PaymentProviderRegistry",
}
_IDENTITY_RECOVERY_FORBIDDEN_MODULES = (
    "app.domains.billing",
    "app.domains.identity.services.account",
    "app.domains.identity.services.checkout",
    "app.infrastructure.queries.orders",
    "app.infrastructure.queries.payments",
    "app.infrastructure.queries.plans",
    "app.infrastructure.queries.products",
    "app.infrastructure.queries.subscriptions",
    "app.integrations",
    "app.payment_providers",
)


def _is_identity_legal_surface(path_parts: tuple[str, ...]) -> bool:
    return (
        path_parts in _IDENTITY_RECOVERY_PATHS
        or path_parts[:2] == ("domains", "legal")
        or path_parts
        in {
            ("infrastructure", "queries", "legal.py"),
            ("models", "identity.py"),
            ("models", "legal.py"),
        }
    )


def _identity_boundary_names(tree: ast.AST) -> list[tuple[int, str]]:
    names: set[tuple[int, str]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add((node.lineno, node.id))
        elif isinstance(node, ast.Attribute):
            names.add((node.lineno, node.attr))
        elif isinstance(node, ast.alias):
            names.add((node.lineno, node.asname or node.name.rsplit(".", 1)[-1]))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add((node.lineno, node.name))
        elif isinstance(node, ast.arg):
            names.add((node.lineno, node.arg))
        elif isinstance(node, ast.keyword) and node.arg is not None:
            names.add((node.lineno, node.arg))
    return sorted(names)


def _canonical_model_references(
    tree: ast.AST,
    forbidden_names: frozenset[str],
) -> list[tuple[int, str, str]]:
    """Find direct references to selected canonical persisted model symbols."""
    module_aliases: dict[str, str] = {}
    references: set[tuple[int, str, str]] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if module_matches(alias.name, "app.models"):
                    bound_name = alias.asname or alias.name.split(".", 1)[0]
                    module_aliases[bound_name] = (
                        alias.name if alias.asname else bound_name
                    )
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        for alias in node.names:
            target = f"{module}.{alias.name}" if module else alias.name
            if (
                module_matches(module, "app.models")
                and alias.name in forbidden_names
            ):
                references.add((node.lineno, alias.name, module))
            elif module_matches(target, "app.models") and alias.name[:1].islower():
                module_aliases[alias.asname or alias.name] = target

    for node in ast.walk(tree):
        if (
            not isinstance(node, ast.Attribute)
            or node.attr not in forbidden_names
        ):
            continue
        dotted = _dotted_python_name(node)
        if dotted is None:
            continue
        prefix, _, symbol = dotted.rpartition(".")
        for alias, module in module_aliases.items():
            if prefix == alias or prefix.startswith(f"{alias}."):
                suffix = prefix[len(alias) :].lstrip(".")
                canonical_module = f"{module}.{suffix}" if suffix else module
                if module_matches(canonical_module, "app.models"):
                    references.add((node.lineno, symbol, canonical_module))
                break

    return sorted(references)


def _owns_fastapi_api_router(tree: ast.AST) -> bool:
    factories: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and module_matches(
            node.module or "", "fastapi"
        ):
            for alias in node.names:
                if alias.name == "APIRouter":
                    factories.add(alias.asname or alias.name)
                elif node.module == "fastapi" and alias.name == "routing":
                    factories.add(f"{alias.asname or alias.name}.APIRouter")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "fastapi":
                    factories.add(f"{alias.asname or 'fastapi'}.APIRouter")
                elif alias.name == "fastapi.routing":
                    factories.add(f"{alias.asname or 'fastapi.routing'}.APIRouter")

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and _dotted_python_name(node.value) in factories
        ):
            factories.add(node.targets[0].id)

    return any(
        isinstance(node, ast.Call) and _dotted_python_name(node.func) in factories
        for node in ast.walk(tree)
    )


def _dotted_python_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_python_name(node.value)
        if prefix is not None:
            return f"{prefix}.{node.attr}"
    return None


def _sqlalchemy_session_symbols(tree: ast.AST) -> tuple[set[str], set[str]]:
    direct_names: set[str] = set()
    module_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "sqlalchemy.orm":
                direct_names.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "Session"
                )
            elif node.module == "sqlalchemy":
                module_names.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "orm"
                )
            continue
        if not isinstance(node, ast.Import):
            continue
        for alias in node.names:
            if alias.name == "sqlalchemy.orm":
                module_names.add(alias.asname or "sqlalchemy.orm")
            elif alias.name == "sqlalchemy":
                module_names.add(
                    f"{alias.asname}.orm" if alias.asname else "sqlalchemy.orm"
                )

    return direct_names, module_names


def _references_sqlalchemy_session(
    node: ast.expr,
    direct_names: set[str],
    module_names: set[str],
) -> bool:
    for candidate in ast.walk(node):
        dotted = _dotted_python_name(candidate)
        if dotted in direct_names or any(
            dotted == f"{module}.Session" for module in module_names
        ):
            return True
        if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
            if candidate.value in direct_names or any(
                candidate.value == f"{module}.Session" for module in module_names
            ):
                return True
    return False


class _PersistenceTransactionOwnershipVisitor(ast.NodeVisitor):
    forbidden_methods = frozenset({"begin", "commit", "rollback"})

    def __init__(self, direct_names: set[str], module_names: set[str]) -> None:
        self.direct_names = direct_names
        self.module_names = module_names
        self.session_scopes: list[set[str]] = [set()]
        self.violations: list[tuple[int, str]] = []

    def _is_session_reference(self, node: ast.expr) -> bool:
        dotted = _dotted_python_name(node)
        return dotted in self.direct_names or any(
            dotted == f"{module}.Session" for module in self.module_names
        )

    def _is_session_receiver(self, node: ast.expr) -> bool:
        return (isinstance(node, ast.Name) and node.id in self.session_scopes[-1]) or (
            self._is_session_reference(node)
        )

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        arguments = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        shadowed_names = {argument.arg for argument in arguments}
        session_names = self.session_scopes[-1] - shadowed_names
        session_names.update(
            argument.arg
            for argument in arguments
            if argument.annotation is not None
            and _references_sqlalchemy_session(
                argument.annotation,
                self.direct_names,
                self.module_names,
            )
        )
        self.session_scopes.append(session_names)
        for statement in node.body:
            self.visit(statement)
        self.session_scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            if _references_sqlalchemy_session(
                node.annotation,
                self.direct_names,
                self.module_names,
            ):
                self.session_scopes[-1].add(node.target.id)
            else:
                self.session_scopes[-1].discard(node.target.id)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        value_is_session = self._is_session_receiver(node.value) or (
            isinstance(node.value, ast.Call)
            and self._is_session_reference(node.value.func)
        )
        for target in node.targets:
            if isinstance(target, ast.Name):
                if value_is_session:
                    self.session_scopes[-1].add(target.id)
                else:
                    self.session_scopes[-1].discard(target.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in self.forbidden_methods
            and self._is_session_receiver(node.func.value)
        ):
            self.violations.append((node.lineno, node.func.attr))
        self.generic_visit(node)


class _PresentationPersistenceOrchestrationVisitor(
    _PersistenceTransactionOwnershipVisitor
):
    forbidden_methods = frozenset(
        {
            "add",
            "add_all",
            "begin",
            "begin_nested",
            "commit",
            "delete",
            "execute",
            "flush",
            "get",
            "merge",
            "query",
            "refresh",
            "rollback",
            "scalar",
            "scalars",
        }
    )


class _ApplicationQueryCompositionVisitor(_PersistenceTransactionOwnershipVisitor):
    forbidden_methods = frozenset({"execute", "get", "query", "scalar", "scalars"})


def _is_refactored_application_persistence_surface(
    path_parts: tuple[str, ...],
) -> bool:
    """Identify active inward surfaces with established focused persistence helpers."""
    return (
        path_parts[:3] == ("domains", "identity", "services")
        or path_parts == ("domains", "legal", "service.py")
        or path_parts
        in {
            ("domains", "billing", "service", "account.py"),
            ("domains", "billing", "service", "catalog.py"),
        }
    )


def check_persistence_transaction_ownership(root: Path = ROOT) -> list[str]:
    app_root = root / "apps/api/app"
    focused_roots = (
        app_root / "infrastructure/queries",
        app_root / "infrastructure/persistence",
    )
    errors: list[str] = []

    for focused_root in focused_roots:
        if not focused_root.exists():
            continue
        for path in sorted(focused_root.rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError:
                continue
            direct_names, module_names = _sqlalchemy_session_symbols(tree)
            if not direct_names and not module_names:
                continue
            visitor = _PersistenceTransactionOwnershipVisitor(
                direct_names, module_names
            )
            visitor.visit(tree)
            errors.extend(
                f"{relative}:{line} calls SQLAlchemy Session.{method}(); focused persistence "
                "helpers must not own or finalize the outer business transaction "
                "(see ARCHITECTURE.md)"
                for line, method in visitor.violations
            )

    return errors


def check_removed_billing_architecture(root: Path = ROOT) -> list[str]:
    """Reject executable legacy billing and direct-provider architecture."""
    app_root = root / "apps/api/app"
    errors: list[str] = []
    for relative in (
        Path("scripts/cloudpayments_sandbox_verify.py"),
        Path("apps/api/app/commands/expire_subscriptions.py"),
    ):
        if (root / relative).exists():
            errors.append(
                f"{relative.as_posix()} recreates a removed provider/lifecycle command"
            )

    web_root = root / "apps/web/src"
    if web_root.exists():
        for path in sorted(web_root.rglob("*")):
            if path.suffix not in {".js", ".jsx", ".ts", ".tsx"}:
                continue
            source = path.read_text(encoding="utf-8")
            if "cloudpayments" in source.lower():
                errors.append(
                    f"{path.relative_to(root).as_posix()} references removed CloudPayments "
                    "runtime; do not restore provider-specific executable architecture "
                    "(see ADR 0005)"
                )

    if not app_root.exists():
        return errors

    for path in sorted(app_root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        path_parts = path.relative_to(app_root).parts
        source = path.read_text(encoding="utf-8")

        if (
            path_parts[0] == "payment_providers"
            or path_parts[:2] == ("integrations", "cloudpayments")
            or path_parts == ("cloudpayments.py",)
        ):
            errors.append(
                f"{relative} recreates removed direct-provider/CloudPayments runtime; "
                "External Billing is a separate boundary (see ADR 0005)"
            )
        elif "cloudpayments" in source.lower():
            errors.append(
                f"{relative} references removed CloudPayments runtime; "
                "do not restore provider-specific executable architecture (see ADR 0005)"
            )

        try:
            tree = ast.parse(source, filename=str(path))
            imports = resolve_python_imports(path, app_root)
        except SyntaxError:
            continue

        for imported in imports:
            for target in imported.targets:
                if any(
                    module_matches(target, module)
                    for module in _REMOVED_DIRECT_PROVIDER_MODULES
                ):
                    errors.append(
                        f"{relative}:{imported.line} imports removed direct-provider "
                        f"runtime {target}; External Billing must not use an adapter registry "
                        "(see ADR 0005)"
                    )

        for line, name in _identity_boundary_names(tree):
            if name in _REMOVED_DIRECT_PROVIDER_NAMES:
                errors.append(
                    f"{relative}:{line} references removed {name}; External Billing must "
                    "not be modeled as direct-provider runtime (see ADR 0005)"
                )

        for line, symbol, module in _canonical_model_references(
            tree,
            _REMOVED_LEGACY_MODEL_NAMES,
        ):
            errors.append(
                f"{relative}:{line} references removed legacy billing model "
                f"{symbol} from {module}"
            )

        if path_parts[0] != "models":
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in _REMOVED_LEGACY_MODEL_NAMES:
                errors.append(
                    f"{relative}:{node.lineno} defines removed legacy billing model "
                    f"{node.name}; use only the approved external-billing persistence graph"
                )
            if (
                isinstance(node, ast.ClassDef)
                and node.name in REMOVED_LEGACY_PERSISTED_ENUM_NAMES
            ):
                errors.append(
                    f"{relative}:{node.lineno} defines removed legacy persisted enum "
                    f"{node.name}"
                )
            if not (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
            ):
                continue
            table_name = node.value.split(".", 1)[0]
            if table_name in _REMOVED_LEGACY_TABLE_NAMES:
                errors.append(
                    f"{relative}:{node.lineno} references removed legacy billing table "
                    f"{table_name}"
                )
            elif table_name == "external_billing_accounts":
                errors.append(
                    f"{relative}:{node.lineno} references forbidden table "
                    "external_billing_accounts; external_billing_account_id is opaque "
                    "configuration scope, not a Portal ORM entity (see ADR 0005)"
                )

    migrations_root = root / "apps/api/alembic/versions"
    if migrations_root.exists():
        for path in sorted(migrations_root.glob("*.py")):
            relative = path.relative_to(root).as_posix()
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                ):
                    continue
                table_name = node.value.split(".", 1)[0]
                if table_name in _REMOVED_LEGACY_TABLE_NAMES:
                    errors.append(
                        f"{relative}:{node.lineno} references removed legacy billing table "
                        f"{table_name}"
                    )
                elif table_name == "external_billing_accounts":
                    errors.append(
                        f"{relative}:{node.lineno} references forbidden table "
                        "external_billing_accounts (see ADR 0005)"
                    )

    return errors


def check_python_boundaries(root: Path = ROOT) -> list[str]:
    app_root = root / "apps/api/app"
    if not app_root.exists():
        return []

    errors: list[str] = []
    for path in sorted(app_root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        path_parts = path.relative_to(app_root).parts
        is_sentry_adapter = path_parts == ("infrastructure", "sentry.py")
        in_core = path_parts[0] == "core"
        in_domains = path_parts[0] == "domains"
        in_integrations = path_parts[0] == "integrations"
        in_persistence_infrastructure = (
            len(path_parts) >= 2
            and path_parts[0] == "infrastructure"
            and path_parts[1] in {"persistence", "queries"}
        )
        is_http_dependencies = path_parts == ("http", "dependencies.py")
        is_refactored_application_persistence = (
            _is_refactored_application_persistence_surface(path_parts)
        )
        is_domain_service_or_model = in_domains and path.name in {"service.py", "models.py"}
        is_domain_service_tree = (
            in_domains
            and len(path_parts) >= 3
            and path_parts[2] in {"service.py", "service", "services", "application"}
        )
        is_router = path.name == "router.py"
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
            imports = resolve_python_imports(path, app_root)
        except SyntaxError as error:
            errors.append(
                f"{relative}:{error.lineno or 1} cannot be parsed for dependency boundaries; "
                "fix the Python syntax before running architecture checks"
            )
            continue

        if path_parts in _IDENTITY_RECOVERY_PATHS:
            forbidden_model_references = set(
                _canonical_model_references(
                    tree,
                    _IDENTITY_RECOVERY_FORBIDDEN_MODEL_NAMES,
                )
            )
            for imported in imports:
                for target in imported.targets:
                    module, _, symbol = target.rpartition(".")
                    if (
                        symbol in _IDENTITY_RECOVERY_FORBIDDEN_MODEL_NAMES
                        and module_matches(module, "app.models")
                    ):
                        forbidden_model_references.add(
                            (imported.line, symbol, module)
                        )
                    if any(
                        module_matches(target, module_name)
                        for module_name in _IDENTITY_RECOVERY_FORBIDDEN_MODULES
                    ):
                        errors.append(
                            f"{relative}:{imported.line} imports {target}; "
                            "identity/recovery must not depend on entrypoint, commerce, "
                            "provider, or trial ownership (see ADR 0005)"
                        )
            errors.extend(
                f"{relative}:{line} references {symbol} from {module}; "
                "identity/recovery must not depend on entrypoint, commerce, provider, "
                "or trial ownership (see ADR 0005)"
                for line, symbol, module in sorted(forbidden_model_references)
            )
            for line, name in _identity_boundary_names(tree):
                lowered_name = name.lower()
                if name in _IDENTITY_RECOVERY_FORBIDDEN_NAMES:
                    errors.append(
                        f"{relative}:{line} references {name}; identity/recovery "
                        "must not use entrypoint, commerce, or provider authority "
                        "(see ADR 0005)"
                    )
                elif "entrypoint" in lowered_name or "trial" in lowered_name:
                    errors.append(
                        f"{relative}:{line} references {name}; identity/recovery "
                        "must not require entrypoint or Portal trial state (see ADR 0005)"
                    )
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and re.search(r"\btrial(?:s|ing)?\b", node.value, re.IGNORECASE)
                ):
                    errors.append(
                        f"{relative}:{node.lineno} references Portal trial vocabulary; "
                        "identity/recovery must not require Portal trial state "
                        "(see ADR 0005)"
                    )

        if _is_identity_legal_surface(path_parts):
            for line, name in _identity_boundary_names(tree):
                lowered_name = name.lower()
                if "customer" in lowered_name or lowered_name == "outer_id":
                    errors.append(
                        f"{relative}:{line} references {name}; identity/legal "
                        "must not allocate or bind external billing customers or promote "
                        "PII/provider values into cross-system identity (see ADR 0005)"
                    )
                elif (
                    re.search(r"(?:external|billing|provider)_.*_?id$", lowered_name)
                    and lowered_name
                    not in {"external_billing_account_id", "billing_offer_id"}
                ):
                    errors.append(
                        f"{relative}:{line} references {name}; identity/legal "
                        "must not promote provider identifiers into cross-system identity "
                        "(see ADR 0005)"
                    )
            for imported in imports:
                for target in imported.targets:
                    lowered_target = target.lower()
                    if (
                        "customer" in lowered_target
                        or lowered_target.endswith(".outer_id")
                        or "external_billing" in lowered_target
                    ):
                        errors.append(
                            f"{relative}:{imported.line} imports {target}; "
                            "identity/legal must not own external billing customer "
                            "allocation or binding (see ADR 0005)"
                        )
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                ):
                    continue
                lowered_value = node.value.lower()
                if "customer" in lowered_value or re.search(
                    r"\bouter_id\b", lowered_value
                ):
                    errors.append(
                        f"{relative}:{node.lineno} contains external customer identity "
                        "vocabulary; identity/legal must not own billing customer "
                        "allocation or binding (see ADR 0005)"
                    )

        is_active_domain_presentation = in_domains and _owns_fastapi_api_router(tree)

        for imported in imports:
            rules: list[tuple[str, Callable[[str], bool], str]] = []
            if not is_sentry_adapter:
                rules.append(
                    (
                        "Sentry SDK adapter boundary",
                        lambda target: module_matches(target, "sentry_sdk"),
                        "import app.infrastructure.sentry instead",
                    )
                )
            if in_core:
                rules.append(
                    (
                        "core dependency direction",
                        lambda target: module_matches(target, "app.domains")
                        or module_matches(target, "app.integrations"),
                        "move the dependency to wiring or shared core infrastructure",
                    )
                )
            if in_domains:
                rules.append(
                    (
                        "domain-to-integration dependency",
                        lambda target: module_matches(target, "app.integrations"),
                        "inject a provider-independent service instead of importing an integration",
                    )
                )
            if is_domain_service_or_model:
                rules.append(
                    (
                        "domain service/model-to-router dependency",
                        router_module,
                        "import a service, model, contract, or session dependency instead of a router",
                    )
                )
            if is_domain_service_tree:
                rules.append(
                    (
                        "domain service/application-to-transport dependency",
                        lambda target: module_matches(target, "fastapi")
                        or module_matches(target, "starlette"),
                        "keep FastAPI and Starlette dependencies in presentation modules",
                    )
                )
            if is_refactored_application_persistence:
                rules.append(
                    (
                        "refactored Application persistence boundary",
                        lambda target: module_matches(target, "sqlalchemy")
                        and target not in {"sqlalchemy.orm", "sqlalchemy.orm.Session"},
                        "delegate SQLAlchemy query construction and storage mechanics to focused "
                        "infrastructure capabilities",
                    )
                )
            if is_active_domain_presentation or is_http_dependencies:
                rules.append(
                    (
                        "HTTP Presentation persistence boundary",
                        lambda target: (
                            module_matches(target, "app.infrastructure.queries")
                            or module_matches(target, "app.infrastructure.persistence")
                            or (
                                module_matches(target, "sqlalchemy")
                                and target
                                not in {"sqlalchemy.orm", "sqlalchemy.orm.Session"}
                            )
                        ),
                        "delegate SQLAlchemy query construction and persistence orchestration to "
                        "an inward application/service use case",
                    )
                )
            if in_integrations:
                rules.append(
                    (
                        "integration-to-domain-router dependency",
                        lambda target: module_matches(target, "app.domains")
                        and router_module(target),
                        "call a domain service instead of importing a domain router",
                    )
                )
            if in_persistence_infrastructure:
                rules.append(
                    (
                        "persistence dependency direction",
                        lambda target: (
                            module_matches(target, "fastapi")
                            or module_matches(target, "starlette")
                            or module_matches(target, "app.domains")
                            or module_matches(target, "app.integrations")
                        ),
                        "keep persistence dependent only on models and neutral infrastructure",
                    )
                )
            if is_router:
                rules.append(
                    (
                        "router-to-router dependency",
                        router_module,
                        "import a service, contract, or session dependency instead of a router",
                    )
                )

            for rule_name, predicate, remediation in rules:
                target = next(
                    (candidate for candidate in imported.targets if predicate(candidate)),
                    None,
                )
                if target:
                    errors.append(
                        f"{relative}:{imported.line} imports {target}; violates {rule_name}; "
                        f"{remediation} (see ARCHITECTURE.md)"
                    )

        if is_active_domain_presentation or is_http_dependencies:
            direct_names, module_names = _sqlalchemy_session_symbols(tree)
            if direct_names or module_names:
                visitor = _PresentationPersistenceOrchestrationVisitor(
                    direct_names,
                    module_names,
                )
                visitor.visit(tree)
                owner = (
                    "active domain Presentation"
                    if is_active_domain_presentation
                    else "HTTP dependency composition"
                )
                errors.extend(
                    f"{relative}:{line} calls SQLAlchemy Session.{method}(); {owner} must "
                    "delegate persistence orchestration to an inward application/service use case "
                    "(see ARCHITECTURE.md)"
                    for line, method in visitor.violations
                )

        if is_refactored_application_persistence:
            direct_names, module_names = _sqlalchemy_session_symbols(tree)
            if direct_names or module_names:
                visitor = _ApplicationQueryCompositionVisitor(
                    direct_names,
                    module_names,
                )
                visitor.visit(tree)
                errors.extend(
                    f"{relative}:{line} calls SQLAlchemy Session.{method}(); refactored "
                    "Application code must delegate query composition to focused infrastructure "
                    "capabilities (see ARCHITECTURE.md)"
                    for line, method in visitor.violations
                )

    return errors


def check_canonical_persisted_model_layer(root: Path = ROOT) -> list[str]:
    """Protect the final ANY-326 model ownership and import boundary."""
    app_root = root / "apps/api/app"
    if not app_root.exists():
        return []

    errors: list[str] = []
    billing_model_facade = app_root / "domains/billing/models.py"
    canonical_enum_module = (app_root / "models/enums.py").resolve()
    if billing_model_facade.exists():
        errors.append(
            "apps/api/app/domains/billing/models.py is forbidden; import ORM models from app.models"
        )

    for path in sorted(app_root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            resolved_imports = {
                imported.line: imported.targets
                for imported in resolve_python_imports(path, app_root)
            }
        except SyntaxError as error:
            errors.append(
                f"{relative}:{error.lineno or 1} cannot be parsed for canonical model-layer checks"
            )
            continue

        if path.resolve() != canonical_enum_module:
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name in CANONICAL_PERSISTED_ENUM_NAMES:
                    errors.append(
                        f"{relative}:{node.lineno} defines protected persisted enum {node.name}; "
                        "define it only in apps/api/app/models/enums.py"
                    )

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_targets = tuple(alias.name for alias in node.names)
                if any(
                    module_matches(target, "app.domains.billing.models")
                    for target in imported_targets
                ):
                    errors.append(
                        f"{relative}:{node.lineno} imports ORM models through "
                        "app.domains.billing.models; import them from app.models"
                    )
                if any(
                    module_matches(target, "app.domains.legal.enums")
                    for target in imported_targets
                ):
                    errors.append(
                        f"{relative}:{node.lineno} imports the removed legal enum façade; "
                        "import persisted enums from app.models"
                    )
                continue

            if not isinstance(node, ast.ImportFrom):
                continue

            imported_targets = resolved_imports.get(node.lineno, ())
            if any(
                module_matches(target, "app.domains.billing.models")
                for target in imported_targets
            ):
                errors.append(
                    f"{relative}:{node.lineno} imports ORM models through "
                    "app.domains.billing.models; import them from app.models"
                )
            if any(
                module_matches(target, "app.domains.legal.enums")
                for target in imported_targets
            ):
                errors.append(
                    f"{relative}:{node.lineno} imports the removed legal enum façade; "
                    "import persisted enums from app.models"
                )

            billing_enum_module = "app.domains.billing.enums"
            if billing_enum_module in imported_targets:
                for alias in node.names:
                    if alias.name == "enums":
                        errors.append(
                            f"{relative}:{node.lineno} imports {alias.name} through the removed "
                            "billing enum façade; import it from app.models"
                        )
            for alias in node.names:
                if alias.name in REMOVED_BILLING_ENUM_FACADE_NAMES and (
                    f"{billing_enum_module}.{alias.name}" in imported_targets
                ):
                    errors.append(
                        f"{relative}:{node.lineno} imports {alias.name} through the removed "
                        "billing enum façade; import it from app.models"
                    )

    return errors


def cmd_architecture(_: argparse.Namespace) -> None:
    errors = check_removed_api_compatibility()
    errors.extend(check_removed_billing_architecture())
    errors.extend(check_python_boundaries())
    errors.extend(check_persistence_transaction_ownership())
    errors.extend(check_canonical_persisted_model_layer())
    limits = json.loads((ROOT / "architecture-limits.json").read_text(encoding="utf-8"))
    default_limit = int(limits["defaultMaxLines"])
    exceptions = limits["exceptions"]
    source_roots = (ROOT / "apps/api/app", ROOT / "apps/web/src")
    for source_root in source_roots:
        for path in source_root.rglob("*"):
            if path.suffix not in {".py", ".ts", ".tsx", ".css"} or "generated" in path.parts:
                continue
            relative = path.relative_to(ROOT).as_posix()
            configured = exceptions.get(relative, {})
            maximum = int(configured.get("maxLines", default_limit))
            line_count = len(path.read_text(encoding="utf-8").splitlines())
            if line_count > maximum:
                errors.append(
                    f"{relative} has {line_count} lines (limit {maximum}); split it or document a bounded exception"
                )
    if errors:
        raise HarnessError("Architecture checks failed:\n- " + "\n- ".join(errors))
    print("Architecture checks passed.")


def cmd_harness_smoke(_: argparse.Namespace) -> None:
    config = runtime_config()
    assert config.compose_project == f"payments-{config.worktree_id}"
    assert config.database_name == f"payments_{config.worktree_id}"
    ports = tuple(runtime_ports(config))
    assert runtime_caddy_port(config) in ports
    assert len(set(ports)) == len(ports)
    write_runtime(config)
    env = read_runtime_env()
    caddy_origin = f"http://localhost:{runtime_caddy_port(config)}"
    assert env["APP_ENV"] == "development"
    assert env["INSTANCE_TENANT_ID"] == LOCAL_INSTANCE_TENANT_ID
    assert env["INSTANCE_REGION"] == LOCAL_INSTANCE_REGION
    assert env["CADDY_PORT"] == str(runtime_caddy_port(config))
    assert env["NEXT_PUBLIC_API_BASE_URL"] == caddy_origin
    cors_origins = set(env["CORS_ALLOW_ORIGINS"].split(","))
    assert caddy_origin in cors_origins
    assert env["APP_PUBLIC_BASE_URL"] in cors_origins
    if not re.fullmatch(r"payments-[0-9a-f]{8}", config.compose_project):
        raise HarnessError("Invalid deterministic Compose project name")
    alternative = None
    for suffix in range(1, 100):
        candidate = runtime_config(root=ROOT.parent / f"{ROOT.name}-worktree-{suffix}")
        if set(runtime_ports(candidate)).isdisjoint(runtime_ports(config)):
            alternative = candidate
            break
    if alternative is None:
        raise HarnessError("Could not derive a collision-free second-worktree port set")
    assert alternative.worktree_id != config.worktree_id
    assert alternative.compose_project != config.compose_project
    assert alternative.database_name != config.database_name
    print(
        json.dumps(
            {"current_worktree": asdict(config), "second_worktree": asdict(alternative)},
            indent=2,
        )
    )
    print("Harness smoke check passed.")


def without_fenced_code_blocks(markdown: str) -> str:
    rendered_lines: list[str] = []
    fence = ""
    for line in markdown.splitlines():
        marker = re.fullmatch(r" {0,3}(`{3,}|~{3,})(.*)", line)
        if fence:
            if (
                marker
                and marker[1][0] == fence[0]
                and len(marker[1]) >= len(fence)
                and not marker[2].strip()
            ):
                fence = ""
            rendered_lines.append("")
        elif marker and (marker[1][0] != "`" or "`" not in marker[2]):
            fence = marker[1]
            rendered_lines.append("")
        else:
            rendered_lines.append(line)
    return "\n".join(rendered_lines)


def validate_pr_metadata(title: str, body: str) -> None:
    title_match = re.fullmatch(r"(ANY-[1-9][0-9]*) - \S.*", title)
    if title_match is None:
        raise HarnessError(
            'Invalid PR title. Required format: "ANY-<number> - <summary>"'
        )

    sections = re.findall(
        r"^## Linear issue[ \t]*(?:\n|$)(.*?)(?=^#{1,2}(?:[ \t]|$)|\Z)",
        without_fenced_code_blocks(body),
        re.MULTILINE | re.DOTALL,
    )
    if len(sections) != 1:
        raise HarnessError(
            "The PR body must contain exactly one rendered '## Linear issue' section."
        )

    urls = re.findall(r"https?://[^\s<>]+", sections[0])
    linear_urls = [
        url.rstrip(")") for url in urls
        if re.match(r"https?://linear\.app(?:/|:|$)", url, re.IGNORECASE)
    ]
    issue = (
        re.fullmatch(
            r"https://linear\.app/paveldik/issue/(ANY-[1-9][0-9]*)(?:/[A-Za-z0-9_-]+)?/?",
            linear_urls[0],
        )
        if len(linear_urls) == 1 else None
    )
    if issue is None:
        raise HarnessError(
            "The PR body must contain exactly one full Linear issue URL in "
            "the '## Linear issue' section: https://linear.app/paveldik/issue/ANY-<number> "
            "(optional /slug)."
        )
    if title_match[1] != issue[1]:
        raise HarnessError(
            f"PR title issue {title_match[1]} does not match Linear URL issue {issue[1]}."
        )


def cmd_pr_metadata(args: argparse.Namespace) -> None:
    validate_pr_metadata(args.title, args.body)
    print("PR metadata is valid.")


def cmd_validate_production_env(_: argparse.Namespace) -> None:
    validate_production_deployment_environment()
    print("Production deployment environment is valid.")


def summarize_trivy_report(path: Path) -> TrivyGateSummary:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise HarnessError(f"Cannot read Trivy report {path}: {exc}") from exc

    results = report.get("Results", [])
    if not isinstance(results, list):
        raise HarnessError(f"Invalid Trivy report {path}: Results must be a list")

    critical_vulnerabilities = 0
    fixable_high_vulnerabilities = 0
    high_or_critical_misconfigurations = 0
    high_or_critical_secrets = 0

    for result in results:
        if not isinstance(result, dict):
            raise HarnessError(f"Invalid Trivy report {path}: result must be an object")
        for vulnerability in result.get("Vulnerabilities") or []:
            severity = vulnerability.get("Severity")
            if severity == "CRITICAL":
                critical_vulnerabilities += 1
            elif severity == "HIGH" and vulnerability.get("FixedVersion"):
                fixable_high_vulnerabilities += 1
        for misconfiguration in result.get("Misconfigurations") or []:
            if misconfiguration.get("Severity") in {"HIGH", "CRITICAL"}:
                high_or_critical_misconfigurations += 1
        for secret in result.get("Secrets") or []:
            if secret.get("Severity") in {"HIGH", "CRITICAL"}:
                high_or_critical_secrets += 1

    return TrivyGateSummary(
        report=path.name,
        critical_vulnerabilities=critical_vulnerabilities,
        fixable_high_vulnerabilities=fixable_high_vulnerabilities,
        high_or_critical_misconfigurations=high_or_critical_misconfigurations,
        high_or_critical_secrets=high_or_critical_secrets,
    )


def redact_trivy_report(path: Path) -> int:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise HarnessError(f"Cannot read Trivy report {path}: {exc}") from exc

    results = report.get("Results", [])
    if not isinstance(results, list):
        raise HarnessError(f"Invalid Trivy report {path}: Results must be a list")

    redacted_secrets = 0
    for result in results:
        if not isinstance(result, dict):
            raise HarnessError(f"Invalid Trivy report {path}: result must be an object")
        for secret in result.get("Secrets") or []:
            if not isinstance(secret, dict):
                raise HarnessError(
                    f"Invalid Trivy report {path}: secret must be an object"
                )
            secret.pop("Match", None)
            secret.pop("Code", None)
            redacted_secrets += 1

    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return redacted_secrets


def cmd_trivy(args: argparse.Namespace) -> None:
    report_dir = Path(args.report_dir)
    if args.action == "verify-compose-fixture":
        try:
            report = json.loads(report_dir.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise HarnessError(f"Cannot read Trivy report {report_dir}: {exc}") from exc
        results = report.get("Results", [])
        if not isinstance(results, list):
            raise HarnessError(
                f"Invalid Trivy report {report_dir}: Results must be a list"
            )
        messages = {
            finding.get("Message", "")
            for result in results
            if isinstance(result, dict)
            for finding in result.get("Misconfigurations") or []
            if isinstance(finding, dict) and finding.get("ID") == "ANY-COMPOSE-003"
        }
        missing_services = [
            service
            for service in (
                "var-run-short-syntax",
                "run-short-syntax",
                "var-run-long-syntax",
                "run-long-syntax",
            )
            if not any(service in message for message in messages)
        ]
        if missing_services:
            raise HarnessError(
                "Docker socket policy missed Compose fixture service(s): "
                + ", ".join(missing_services)
            )
        print("Verified Docker socket paths in short and long Compose syntax.")
        return

    if args.action == "verify-iac-fixture":
        try:
            report = json.loads(report_dir.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise HarnessError(f"Cannot read Trivy report {report_dir}: {exc}") from exc
        results = report.get("Results", [])
        if not isinstance(results, list):
            raise HarnessError(
                f"Invalid Trivy report {report_dir}: Results must be a list"
            )
        covered_fixtures = {
            Path(result.get("Target", "")).name
            for result in results
            if isinstance(result, dict) and result.get("Misconfigurations")
        }
        expected_fixtures = {"insecure-pod.json", "insecure-pod.yaml"}
        missing = sorted(expected_fixtures - covered_fixtures)
        if missing:
            raise HarnessError(
                "Trivy did not scan non-Compose IaC fixture(s): " + ", ".join(missing)
            )
        print("Verified non-Compose IaC scanner coverage for YAML and JSON.")
        return

    if args.action == "redact":
        reports = sorted(report_dir.glob("*.json"))
        redacted = sum(redact_trivy_report(path) for path in reports)
        print(f"Redacted secret values from {len(reports)} report(s): {redacted}")
        return

    expected_reports = (
        "filesystem.json",
        "compose.json",
        "api-image.json",
        "web-image.json",
    )
    missing = [name for name in expected_reports if not (report_dir / name).is_file()]
    if missing:
        raise HarnessError("Missing Trivy reports: " + ", ".join(missing))

    summaries = [
        summarize_trivy_report(report_dir / report) for report in expected_reports
    ]
    for summary in summaries:
        print(
            f"{summary.report}: blocking={summary.blocking_findings} "
            f"critical_vulnerabilities={summary.critical_vulnerabilities} "
            f"fixable_high_vulnerabilities={summary.fixable_high_vulnerabilities} "
            f"high_or_critical_misconfigurations="
            f"{summary.high_or_critical_misconfigurations} "
            f"high_or_critical_secrets={summary.high_or_critical_secrets}"
        )

    blocking_findings = sum(summary.blocking_findings for summary in summaries)
    if blocking_findings:
        raise HarnessError(
            f"Trivy policy rejected {blocking_findings} finding(s); "
            "review the redacted workflow artifact for details"
        )
    print("Trivy policy passed.")


def cmd_check(args: argparse.Namespace) -> None:
    check_env = canonical_check_environment()
    cmd_docs(argparse.Namespace())
    cmd_generate(argparse.Namespace(check=True))
    cmd_architecture(argparse.Namespace())
    cmd_lint(argparse.Namespace(target="api"))
    run([tool("npm"), "run", "test:boundaries:web"], env=check_env)
    run(
        [tool("npm"), "--workspace", "@anytoolai/web", "run", "test:components"],
        env=check_env,
    )
    run([tool("npm"), "run", "lint:web"], env=check_env)
    cmd_test(
        argparse.Namespace(target="api-fast", junitxml=None),
        environment=check_env,
    )
    if not args.fast:
        run([tool("npm"), "run", "build:web"], env=check_env)
        cmd_test(
            argparse.Namespace(target="api-postgres", junitxml=None),
            environment=check_env,
        )
        if os.getenv("RUN_E2E") == "true":
            run([tool("npm"), "run", "test:e2e"], env=check_env)
        else:
            print("SKIP: browser suite requires RUN_E2E=true and a running harness stack")


def host_database_url_from_runtime(env: dict[str, str]) -> str:
    user = urllib.parse.quote(env["POSTGRES_USER"], safe="")
    password = urllib.parse.quote(env["POSTGRES_PASSWORD"], safe="")
    database = urllib.parse.quote(env["POSTGRES_DB"], safe="")
    return f"postgresql+psycopg://{user}:{password}@127.0.0.1:{env['POSTGRES_PORT']}/{database}"


def direct_api_environment(*, environ: dict[str, str] | None = None) -> dict[str, str]:
    base_environment = dict(os.environ if environ is None else environ)
    local_env = read_dotenv()
    runtime_env = read_runtime_env()
    defaults = {
        **runtime_env,
        **local_env,
        "DATABASE_URL": host_database_url_from_runtime(runtime_env),
        **base_environment,
    }
    defaults.setdefault("APP_ENV", "development")
    defaults.setdefault("INSTANCE_TENANT_ID", LOCAL_INSTANCE_TENANT_ID)
    defaults.setdefault("INSTANCE_REGION", LOCAL_INSTANCE_REGION)
    defaults.setdefault("APP_PUBLIC_BASE_URL", "http://localhost:3000")
    defaults.setdefault("CORS_ALLOW_ORIGINS", defaults.get("APP_PUBLIC_BASE_URL", "http://localhost:3000"))
    defaults.setdefault("SKIP_LEGAL_SEED", "true")
    return defaults


def cmd_dev_api(_: argparse.Namespace) -> None:
    run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--reload",
            "--no-access-log",
            "--app-dir",
            "apps/api",
        ],
        env=direct_api_environment(),
    )


def cmd_migrate_api(_: argparse.Namespace) -> None:
    run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "apps/api/alembic.ini",
            "upgrade",
            "head",
        ],
        env=direct_api_environment(),
    )


def api_pytest_command(*args: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        *args,
        API_TEST_PATH,
    ]


def api_test_marker_args(target: str) -> list[str]:
    if target == "api-fast":
        return ["-m", "not postgres"]
    if target == "api-postgres":
        return ["-m", "postgres"]
    if target == "api":
        return []
    raise HarnessError(f"Unsupported API test target: {target}")


def api_test_environment(target: str, environment: dict[str, str]) -> dict[str, str]:
    if target == "api-fast":
        return environment

    test_database_url_name = "TEST_POSTGRES_DATABASE_URL"
    if environment.get(test_database_url_name):
        return environment

    explicit_names = (
        "POSTGRES_USER_TEST",
        "POSTGRES_PASSWORD_TEST",
        "POSTGRES_PORT_TEST",
        "POSTGRES_DB_TEST",
        "POSTGRES_HOST_TEST",
    )
    present_names = [name for name in explicit_names if name in environment]
    required_names = explicit_names[:4]
    if present_names:
        missing_names = [name for name in required_names if not environment.get(name)]
        if missing_names:
            raise HarnessError(
                "Incomplete PostgreSQL test configuration; set "
                + ", ".join(required_names)
                + " together, missing: "
                + ", ".join(missing_names)
            )
        return environment

    runtime_env = read_runtime_env()
    runtime_names = ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_PORT")
    missing_runtime_names = [name for name in runtime_names if not runtime_env.get(name)]
    if missing_runtime_names:
        raise HarnessError(
            "Cannot derive local PostgreSQL test configuration; runtime.env is missing: "
            + ", ".join(missing_runtime_names)
        )
    if port_is_free(int(runtime_env["POSTGRES_PORT"])):
        raise HarnessError(
            "Local test PostgreSQL server is not running. Start it with:\n"
            "  python scripts/repo.py test-db up\n"
            "Unix/WSL shortcut:\n"
            "  make test_db_up"
        )

    database_environment = {
        **runtime_env,
        "POSTGRES_DB": f"{runtime_env['POSTGRES_DB']}_tests",
    }
    environment[test_database_url_name] = host_database_url_from_runtime(database_environment)
    return environment


def cmd_test(
    args: argparse.Namespace,
    *,
    environment: dict[str, str] | None = None,
) -> None:
    check_env = api_test_environment(
        args.target,
        canonical_check_environment() if environment is None else environment,
    )
    command = api_pytest_command(*api_test_marker_args(args.target))
    if args.junitxml:
        command.insert(-1, f"--junitxml={args.junitxml}")
    run(command, env=check_env)


def api_coverage_xml_path() -> Path:
    return ROOT / ".harness" / "coverage" / "api" / "coverage.xml"


def cmd_coverage(args: argparse.Namespace) -> None:
    check_env = api_test_environment(args.target, canonical_check_environment())
    coverage_xml = api_coverage_xml_path()
    coverage_xml.parent.mkdir(parents=True, exist_ok=True)
    run(
        api_pytest_command(
            *api_test_marker_args(args.target),
            "--cov=apps/api/app",
            "--cov-report=term-missing",
            f"--cov-report=xml:{coverage_xml}",
        ),
        env=check_env,
    )


def cmd_lint(args: argparse.Namespace) -> None:
    check_env = canonical_check_environment()
    if args.target == "api":
        api_root = ROOT / "apps" / "api"
        run([sys.executable, "-m", "ruff", "check", "."], cwd=api_root, env=check_env)
        run(
            [sys.executable, "-m", "ruff", "format", "--check", "."],
            cwd=api_root,
            env=check_env,
        )


def read_runtime_env() -> dict[str, str]:
    if not RUNTIME_ENV.exists():
        write_runtime(runtime_config())
    values: dict[str, str] = {}
    for line in RUNTIME_ENV.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def fetch_json(url: str) -> object:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


def cmd_observe(args: argparse.Namespace) -> None:
    env = read_runtime_env()
    if args.signal == "logs":
        query = args.query or f'{{service_name="payment-portal-api"}} |= `{args.request_id}`'
        base = f"http://localhost:{env['LOKI_PORT']}/loki/api/v1/query_range"
        url = base + "?" + urllib.parse.urlencode({"query": query, "limit": 100})
    elif args.signal == "metrics":
        if not args.query:
            raise HarnessError("Metrics require --query <PromQL>")
        base = f"http://localhost:{env['PROMETHEUS_PORT']}/api/v1/query"
        url = base + "?" + urllib.parse.urlencode({"query": args.query})
    else:
        if not args.trace_id:
            raise HarnessError("Traces require --trace-id")
        url = f"http://localhost:{env['TEMPO_PORT']}/api/traces/{args.trace_id}"
    print(json.dumps(fetch_json(url), ensure_ascii=True, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor").set_defaults(func=cmd_doctor)
    sub.add_parser("setup").set_defaults(func=cmd_setup)
    up = sub.add_parser("up")
    up.add_argument("--port-offset", type=int, default=0)
    up.add_argument("--reuse", action="store_true")
    up.set_defaults(func=cmd_up)
    sub.add_parser("down").set_defaults(func=cmd_down)
    test_db = sub.add_parser("test-db")
    test_db.add_argument("action", choices=("up", "stop"))
    test_db.set_defaults(func=cmd_test_db)
    reset = sub.add_parser("reset")
    reset.add_argument("--confirm", required=True)
    reset.set_defaults(func=cmd_reset)
    generate = sub.add_parser("generate")
    generate.add_argument("--check", action="store_true")
    generate.set_defaults(func=cmd_generate)
    legal = sub.add_parser("legal")
    legal.add_argument("action", choices=("generate", "check"))
    legal.set_defaults(func=cmd_legal)
    docs = sub.add_parser("docs")
    docs.add_argument("action", choices=("check",))
    docs.set_defaults(func=cmd_docs)
    architecture = sub.add_parser("architecture")
    architecture.add_argument("action", choices=("check",))
    architecture.set_defaults(func=cmd_architecture)
    sub.add_parser("harness-smoke").set_defaults(func=cmd_harness_smoke)
    lint = sub.add_parser("lint")
    lint.add_argument("target", choices=("api",))
    lint.set_defaults(func=cmd_lint)
    test = sub.add_parser("test")
    test.add_argument("target", choices=("api-fast", "api-postgres", "api"))
    test.add_argument("--junitxml")
    test.set_defaults(func=cmd_test)
    coverage = sub.add_parser("coverage")
    coverage.add_argument("target", choices=("api", "api-fast"))
    coverage.set_defaults(func=cmd_coverage)
    check = sub.add_parser("check")
    check.add_argument("--fast", action="store_true")
    check.set_defaults(func=cmd_check)
    sub.add_parser("dev-api").set_defaults(func=cmd_dev_api)
    sub.add_parser("sync-api").set_defaults(func=cmd_sync_api)
    sub.add_parser("lock-api").set_defaults(func=cmd_lock_api)
    sub.add_parser("check-api-lock").set_defaults(func=cmd_check_api_lock)
    sub.add_parser("migrate-api").set_defaults(func=cmd_migrate_api)
    sub.add_parser("validate-production-env").set_defaults(func=cmd_validate_production_env)
    metadata = sub.add_parser("pr-metadata")
    metadata.add_argument("--title", default=os.environ.get("PR_TITLE", ""))
    metadata.add_argument("--body", default=os.environ.get("PR_BODY", ""))
    metadata.set_defaults(func=cmd_pr_metadata)
    trivy = sub.add_parser("trivy")
    trivy.add_argument(
        "action",
        choices=(
            "gate",
            "redact",
            "verify-compose-fixture",
            "verify-iac-fixture",
        ),
    )
    trivy.add_argument("report_dir")
    trivy.set_defaults(func=cmd_trivy)
    observe = sub.add_parser("observe")
    observe.add_argument("signal", choices=("logs", "metrics", "traces"))
    observe.add_argument("--request-id")
    observe.add_argument("--trace-id")
    observe.add_argument("--query")
    observe.set_defaults(func=cmd_observe)
    return parser


def reexec_in_repository_venv_if_required() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {
        "check",
        "check-api-lock",
        "coverage",
        "dev-api",
        "generate",
        "lint",
        "lock-api",
        "migrate-api",
        "sync-api",
        "test",
    }:
        return
    python = (
        REPOSITORY_VENV / "Scripts" / "python.exe"
        if os.name == "nt"
        else REPOSITORY_VENV / "bin" / "python"
    )
    if not python.exists():
        return
    if Path(sys.prefix).resolve() == REPOSITORY_VENV.resolve():
        return
    result = subprocess.run(
        [str(python), str(Path(__file__).resolve()), *sys.argv[1:]],
        cwd=ROOT,
        check=False,
    )
    raise SystemExit(result.returncode)


def main() -> int:
    try:
        reexec_in_repository_venv_if_required()
        args = build_parser().parse_args()
        args.func(args)
    except (HarnessError, subprocess.CalledProcessError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
