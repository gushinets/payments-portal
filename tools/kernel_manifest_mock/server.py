"""Standalone simulated manifest producer; never imported by Portal runtime."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .documentation import SWAGGER_HTML, openapi_document


MANIFEST_PATH = "/internal/v1/capability-manifest"
MANIFEST_SCOPE = {"tenant_id": "anytoolai", "region": "ru"}
CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/contracts/kernel-capability-manifest/v1"
)
FIXTURE_PATH = CONTRACT_PATH / "fixtures/valid-manifest.json"
MAX_DELAY_SECONDS = 60
REQUEST_TIMEOUT_SECONDS = 5


class Scenario(StrEnum):
    VALID = "valid"
    DISABLED_PRODUCT = "disabled-product"
    MISSING_PRODUCT = "missing-product"
    DISABLED_METRIC = "disabled-metric"
    MISSING_METRIC = "missing-metric"
    WRONG_SCHEMA = "wrong-schema"
    MALFORMED_JSON = "malformed-json"
    PARTIAL = "partial"
    WRONG_TYPE = "wrong-type"
    DUPLICATE_PRODUCT = "duplicate-product"
    DUPLICATE_METRIC = "duplicate-metric"
    INVALID_REFERENCE = "invalid-reference"
    WRONG_TENANT = "wrong-tenant"
    WRONG_REGION = "wrong-region"
    DIGEST_MISMATCH = "digest-mismatch"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class MockConfig:
    app_env: str
    token: str = field(repr=False)
    scenario: Scenario = Scenario.VALID
    delay_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.app_env not in {"development", "test"}:
            raise ValueError(
                "Kernel manifest mock requires APP_ENV=development or test"
            )
        if (
            not self.token
            or not self.token.isascii()
            or any(not 33 <= ord(char) <= 126 for char in self.token)
        ):
            raise ValueError(
                "KERNEL_MOCK_TOKEN must be an explicit nonempty development token "
                "without whitespace"
            )
        if not 0 < self.delay_seconds <= MAX_DELAY_SECONDS:
            raise ValueError(
                f"delay_seconds must be positive and at most {MAX_DELAY_SECONDS}"
            )


def semantic_version(manifest: dict[str, Any]) -> str:
    """Mock-local provisional digest; reject invalid identities before hashing."""
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise ValueError("Unsupported schema_version")
    for name in ("tenant_id", "region"):
        if not isinstance(manifest[name], str) or not manifest[name]:
            raise ValueError("Invalid manifest scope")

    identities: dict[str, set[str]] = {}
    for collection, identity, fields in (
        ("products", "product_id", {"product_id", "enabled"}),
        (
            "usage_metrics",
            "metric_key",
            {"metric_key", "product_id", "unit", "enabled"},
        ),
    ):
        rows = manifest[collection]
        if not isinstance(rows, list):
            raise ValueError("Invalid manifest collection")
        seen: set[str] = set()
        for row in rows:
            if (
                not isinstance(row, dict)
                or set(row) != fields
                or type(row["enabled"]) is not bool
            ):
                raise ValueError("Invalid manifest entry")
            if any(
                not isinstance(row[name], str) or not row[name]
                for name in fields - {"enabled"}
            ):
                raise ValueError("Invalid manifest identity or unit")
            if row[identity] in seen:
                raise ValueError("Duplicate manifest identity")
            seen.add(row[identity])
        identities[collection] = seen
    if any(
        metric["product_id"] not in identities["products"]
        for metric in manifest["usage_metrics"]
    ):
        raise ValueError("Metric references an unknown product")

    semantic = {
        "schema_version": manifest["schema_version"],
        "tenant_id": manifest["tenant_id"],
        "region": manifest["region"],
        "products": sorted(
            manifest["products"], key=lambda product: product["product_id"]
        ),
        "usage_metrics": sorted(
            manifest["usage_metrics"], key=lambda metric: metric["metric_key"]
        ),
    }
    canonical = json.dumps(
        semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def response_manifest(fixture: dict[str, Any], scenario: Scenario) -> dict[str, Any]:
    manifest = copy.deepcopy(fixture)
    manifest["generated_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    if scenario == Scenario.DISABLED_PRODUCT:
        selected = next(
            product
            for product in manifest["products"]
            if product["product_id"] == "proposal_ai"
        )
        selected["enabled"] = False
    elif scenario == Scenario.MISSING_PRODUCT:
        manifest["products"] = [
            product
            for product in manifest["products"]
            if product["product_id"] != "proposal_ai"
        ]
        manifest["usage_metrics"] = []
    elif scenario == Scenario.DISABLED_METRIC:
        manifest["usage_metrics"][0]["enabled"] = False
    elif scenario == Scenario.MISSING_METRIC:
        manifest["usage_metrics"] = []
    elif scenario == Scenario.WRONG_TENANT:
        manifest["tenant_id"] = "other-test-tenant"
    elif scenario == Scenario.WRONG_REGION:
        manifest["region"] = "other-test-region"
    manifest["manifest_version"] = semantic_version(manifest)

    # Deliberately corrupt an otherwise complete response AFTER normal validation.
    # These successful responses are fault injection, never valid producer behavior.
    if scenario == Scenario.WRONG_SCHEMA:
        manifest["schema_version"] = 2
    elif scenario == Scenario.PARTIAL:
        del manifest["usage_metrics"]
    elif scenario == Scenario.WRONG_TYPE:
        manifest["usage_metrics"][0]["enabled"] = "true"
    elif scenario == Scenario.DUPLICATE_PRODUCT:
        manifest["products"].append(copy.deepcopy(manifest["products"][0]))
    elif scenario == Scenario.DUPLICATE_METRIC:
        manifest["usage_metrics"].append(copy.deepcopy(manifest["usage_metrics"][0]))
    elif scenario == Scenario.INVALID_REFERENCE:
        manifest["usage_metrics"][0]["product_id"] = "absent-test-product"
    elif scenario == Scenario.DIGEST_MISMATCH:
        manifest["manifest_version"] = "sha256:" + "0" * 64
    return manifest


class ManifestMockServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], config: MockConfig) -> None:
        self.config = config
        self.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        semantic_version(self.fixture)
        schema = json.loads(
            (CONTRACT_PATH / "manifest.schema.json").read_text(encoding="utf-8")
        )
        self.openapi = openapi_document(
            schema, self.fixture, MANIFEST_PATH, MANIFEST_SCOPE
        )
        super().__init__(address, ManifestMockHandler)


class ManifestMockHandler(BaseHTTPRequestHandler):
    server: ManifestMockServer

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(REQUEST_TIMEOUT_SECONDS)

    def log_message(self, format: str, *args: object) -> None:
        # Never log request targets, headers, credentials or raw error payloads.
        pass

    def _send(
        self, status: int, body: bytes, content_type: str = "application/json"
    ) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if status == 401:
                self.send_header("WWW-Authenticate", "Bearer")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # Expected when a timeout scenario outlives its caller's read deadline.
            pass

    def _error(self, status: int, code: str) -> None:
        self._send(status, json.dumps({"detail": {"code": code}}).encode("utf-8"))

    def do_GET(self) -> None:
        target = urlsplit(self.path)
        if target.path in {"/docs", "/openapi.json"}:
            if self.headers.get("Origin") is not None:
                self._error(403, "browser_access_forbidden")
                return
            if target.path == "/docs":
                self._send(200, SWAGGER_HTML.encode("utf-8"), "text/html; charset=utf-8")
            else:
                self._send(
                    200, json.dumps(self.server.openapi, ensure_ascii=False).encode("utf-8")
                )
            return
        if target.path != MANIFEST_PATH:
            self._error(404, "not_found")
            return
        config = self.server.config
        authorization = self.headers.get_all("Authorization", [])
        expected = f"Bearer {config.token}".encode("utf-8")
        if (
            len(authorization) != 1
            or not secrets.compare_digest(authorization[0].encode("utf-8"), expected)
            or config.scenario == Scenario.UNAUTHORIZED
        ):
            self._error(401, "invalid_service_auth")
            return
        if self.headers.get("Origin") is not None:
            self._error(403, "browser_access_forbidden")
            return
        scope = parse_qs(target.query, keep_blank_values=True)
        if (
            scope != {name: [value] for name, value in MANIFEST_SCOPE.items()}
            or config.scenario == Scenario.FORBIDDEN
        ):
            self._error(403, "scope_forbidden")
            return
        if config.scenario == Scenario.UNAVAILABLE:
            self._error(503, "manifest_unavailable")
            return
        if config.scenario == Scenario.TIMEOUT:
            time.sleep(config.delay_seconds)
        if config.scenario == Scenario.MALFORMED_JSON:
            self._send(200, b'{"schema_version":')
            return
        payload = response_manifest(self.server.fixture, config.scenario)
        self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _method_not_allowed(self) -> None:
        self._error(405, "method_not_allowed")

    do_HEAD = _method_not_allowed
    do_POST = _method_not_allowed
    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed
    do_OPTIONS = _method_not_allowed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SIMULATED development-only Kernel manifest HTTP mock"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument(
        "--scenario", type=Scenario, choices=list(Scenario), default=Scenario.VALID
    )
    parser.add_argument("--delay-seconds", type=float, default=2.0)
    args = parser.parse_args()
    try:
        config = MockConfig(
            app_env=os.environ.get("APP_ENV", ""),
            token=os.environ.get("KERNEL_MOCK_TOKEN", ""),
            scenario=args.scenario,
            delay_seconds=args.delay_seconds,
        )
    except ValueError as error:
        parser.error(str(error))
    with ManifestMockServer((args.host, args.port), config) as server:
        print(
            f"SIMULATED Kernel manifest mock on {args.host}:{server.server_port}; "
            f"scenario={config.scenario}",
            flush=True,
        )
        print(f"Read-only Swagger UI: http://{args.host}:{server.server_port}/docs", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
