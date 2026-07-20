#!/usr/bin/env python3
"""Cross-platform repository and agent harness for Payment Portal."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Iterable


ROOT = Path(__file__).resolve().parents[1]
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
LEGAL_DOCS_ROOT = ROOT / "docs" / "legal" / "ru"


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


def write_runtime(config: RuntimeConfig) -> None:
    HARNESS_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_JSON.write_text(json.dumps(asdict(config), indent=2) + "\n", encoding="utf-8")
    caddy_origin = f"http://localhost:{runtime_caddy_port(config)}"
    values = {
        "COMPOSE_PROJECT_NAME": config.compose_project,
        "POSTGRES_DB": config.database_name,
        "POSTGRES_USER": "anytoolai",
        "POSTGRES_PASSWORD": "anytoolai-local-only",
        "POSTGRES_PORT": str(config.postgres_port),
        "DATABASE_URL": (
            f"postgresql+psycopg://anytoolai:anytoolai-local-only@postgres:5432/"
            f"{config.database_name}"
        ),
        "WEB_PORT": str(config.web_port),
        "API_PORT": str(config.api_port),
        "CADDY_PORT": str(runtime_caddy_port(config)),
        "NEXT_PUBLIC_API_BASE_URL": caddy_origin,
        "CORS_ALLOW_ORIGINS": caddy_origin,
        "GRAFANA_PORT": str(config.grafana_port),
        "LOKI_PORT": str(config.loki_port),
        "PROMETHEUS_PORT": str(config.prometheus_port),
        "TEMPO_PORT": str(config.tempo_port),
        "OTLP_GRPC_PORT": str(config.otlp_grpc_port),
        "OTLP_HTTP_PORT": str(config.otlp_http_port),
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://observability:4318",
        "OTEL_SERVICE_NAME": "payment-portal-api",
        "CLOUDPAYMENTS_ENABLED": "false",
        "NEXT_PUBLIC_CLOUDPAYMENTS_ENABLED": "false",
    }
    RUNTIME_ENV.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
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
    commands = (["git", "--version"], ["python", "--version"], ["node", "--version"], ["npm", "--version"], ["docker", "--version"])
    for command in commands:
        try:
            executable = tool(command[0])
            result = run([executable, *command[1:]], capture=True)
            print((result.stdout or result.stderr).strip())
        except (HarnessError, subprocess.CalledProcessError) as exc:
            failures.append(str(exc))
    try:
        run([tool("docker"), "compose", "version"], capture=True)
    except (HarnessError, subprocess.CalledProcessError) as exc:
        failures.append(str(exc))
    required = [ROOT / ".env.example", ROOT / "package-lock.json", ROOT / "apps/api/requirements-dev.txt"]
    for path in required:
        if not path.exists():
            failures.append(f"Missing required file: {path.relative_to(ROOT)}")
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
    tool("python")
    tool("npm")
    venv = ROOT / ".venv"
    if not venv.exists():
        run([sys.executable, "-m", "venv", str(venv)])
    venv_python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    run([str(venv_python), "-m", "pip", "install", "-r", "apps/api/requirements-dev.txt"])
    run([tool("npm"), "ci"])
    run([tool("npm"), "run", "playwright:install"])
    config = runtime_config()
    write_runtime(config)
    print(f"Setup complete for worktree {config.worktree_id}.")


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
    os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    os.environ.setdefault("SKIP_LEGAL_SEED", "true")
    from app.database import Base  # type: ignore
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


def generate_all(*, check: bool) -> bool:
    stale = generate_legal(check=check)
    stale |= write_or_check(GENERATED_DB, render_db_schema(), check=check)
    stale |= write_or_check(GENERATED_OPENAPI, render_openapi(), check=check)
    stale |= write_or_check(GENERATED_TOKENS, render_tokens(), check=check)
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
INITIAL_MIGRATION = (
    ROOT
    / "apps"
    / "api"
    / "alembic"
    / "versions"
    / "20260707_0001_foundation_identity_legal_provider.py"
)
CORE_AUTHORITY_LINKS = {
    ROOT / "AGENTS.md": (
        ROOT / "README.md",
        ROOT / "ARCHITECTURE.md",
        ROOT / "docs" / "PRODUCT.md",
        ROOT / "docs" / "architecture" / "payment-portal-data-model.md",
        ROOT / "docs" / "product" / "ru-mvp.md",
        ROOT / "docs" / "DESIGN.md",
        ROOT / "docs" / "SECURITY.md",
        ROOT / "docs" / "RELIABILITY.md",
        ROOT / "docs" / "engineering" / "AGENT_WORKFLOW.md",
        ROOT / "docs" / "exec-plans",
    ),
    ROOT / "docs" / "README.md": (
        ROOT / "ARCHITECTURE.md",
        ROOT / "docs" / "PRODUCT.md",
        ROOT / "docs" / "product" / "ru-mvp.md",
        ROOT / "docs" / "DESIGN.md",
        ROOT / "docs" / "architecture" / "payment-portal-data-model.md",
        ROOT / "docs" / "engineering" / "AGENT_WORKFLOW.md",
        ROOT / "docs" / "RELIABILITY.md",
        ROOT / "docs" / "SECURITY.md",
        ROOT / "docs" / "legal" / "README.md",
        ROOT / "docs" / "exec-plans" / "README.md",
    ),
}


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
        ROOT / "docs/product/ru-mvp.md",
    ]
    for path in required:
        if not path.exists():
            errors.append(f"Missing authoritative document: {path.relative_to(ROOT)}")
    errors.extend(check_knowledge_hierarchy())
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
    model_text = (ROOT / "apps/api/app/models.py").read_text(encoding="utf-8")
    documented = (ROOT / "docs/architecture/payment-portal-data-model.md").read_text(encoding="utf-8")
    for table in re.findall(r'__tablename__\s*=\s*"([^"]+)"', model_text):
        if f"`{table}`" not in documented:
            errors.append(f"Implemented table missing from canonical data model: {table}")
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


def check_python_boundaries(root: Path = ROOT) -> list[str]:
    app_root = root / "apps/api/app"
    if not app_root.exists():
        return []

    errors: list[str] = []
    for path in sorted(app_root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        path_parts = path.relative_to(app_root).parts
        in_core = path_parts[0] == "core"
        in_domains = path_parts[0] == "domains"
        in_integrations = path_parts[0] == "integrations"
        is_domain_service_or_model = in_domains and path.name in {"service.py", "models.py"}
        is_router = path.name == "router.py"

        try:
            imports = resolve_python_imports(path, app_root)
        except SyntaxError as error:
            errors.append(
                f"{relative}:{error.lineno or 1} cannot be parsed for dependency boundaries; "
                "fix the Python syntax before running architecture checks"
            )
            continue

        for imported in imports:
            rules: list[tuple[str, Callable[[str], bool], str]] = []
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
            if in_integrations:
                rules.append(
                    (
                        "integration-to-domain-router dependency",
                        lambda target: module_matches(target, "app.domains")
                        and router_module(target),
                        "call a domain service instead of importing a domain router",
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

    return errors


def cmd_architecture(_: argparse.Namespace) -> None:
    errors = check_python_boundaries()
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
    assert env["CADDY_PORT"] == str(runtime_caddy_port(config))
    assert env["NEXT_PUBLIC_API_BASE_URL"] == caddy_origin
    assert env["CORS_ALLOW_ORIGINS"] == caddy_origin
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


def cmd_pr_title(args: argparse.Namespace) -> None:
    pattern = re.compile(r"^ANY-[1-9][0-9]* - \S.*$")
    if not pattern.fullmatch(args.title):
        raise HarnessError(
            'Invalid PR title. Required format: "ANY-<number> - <summary>"'
        )
    print("PR title is valid.")


def cmd_check(args: argparse.Namespace) -> None:
    check_env = canonical_check_environment()
    cmd_docs(argparse.Namespace())
    cmd_generate(argparse.Namespace(check=True))
    cmd_architecture(argparse.Namespace())
    run([tool("npm"), "run", "test:boundaries:web"], env=check_env)
    run([tool("npm"), "run", "lint:web"], env=check_env)
    run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "--ignore",
            "apps/api/tests/test_alembic_postgres.py",
            "apps/api/tests",
        ],
        env=check_env,
    )
    if not args.fast:
        run([tool("npm"), "run", "build:web"], env=check_env)
        postgres_url = os.getenv("TEST_POSTGRES_DATABASE_URL")
        if postgres_url:
            run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-p",
                    "no:cacheprovider",
                    "apps/api/tests/test_alembic_postgres.py",
                ],
                env=check_env,
            )
        else:
            print("SKIP: PostgreSQL integration test requires TEST_POSTGRES_DATABASE_URL")
        if os.getenv("RUN_E2E") == "true":
            run([tool("npm"), "run", "test:e2e"], env=check_env)
        else:
            print("SKIP: browser suite requires RUN_E2E=true and a running harness stack")


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
    check = sub.add_parser("check")
    check.add_argument("--fast", action="store_true")
    check.set_defaults(func=cmd_check)
    title = sub.add_parser("pr-title")
    title.add_argument("title")
    title.set_defaults(func=cmd_pr_title)
    observe = sub.add_parser("observe")
    observe.add_argument("signal", choices=("logs", "metrics", "traces"))
    observe.add_argument("--request-id")
    observe.add_argument("--trace-id")
    observe.add_argument("--query")
    observe.set_defaults(func=cmd_observe)
    return parser


def reexec_in_repository_venv_if_required() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {"check", "generate"}:
        return
    python = (
        ROOT / ".venv" / "Scripts" / "python.exe"
        if os.name == "nt"
        else ROOT / ".venv" / "bin" / "python"
    )
    if not python.exists():
        return
    if Path(sys.executable).resolve() == python.resolve():
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
