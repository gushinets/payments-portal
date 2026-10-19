#!/usr/bin/env python3
"""Read-only documentation/identity watch; never a real producer wire check."""

from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import quote

import httpx


PORTAL = "gushinets/payments-portal"
KERNEL = "gushinets/anytoolai-platform"
PORTAL_PIN = "05d3fcb6a965fcd053d713f49669d1dd25c22978"
KERNEL_PIN = "079eb03e28d7a50b980795c63c3e4533b785d11f"
MAX_SECONDS = 60
MAX_RESPONSE_BYTES = 262144
SELECTED_PRODUCTS = frozenset({"proposal_ai", "client_update_writer", "brief_decoder", "acceptance_builder", "task_finder"})


class ReferenceStatus(StrEnum):
    PASS = "PASS"
    CHANGED = "CHANGE_REVIEW_REQUIRED"
    UNKNOWN = "UNKNOWN_SOURCE_CHECK"


class SourceUnavailable(ValueError):
    """A safe fixed category; no raw responses, URLs or credentials."""


class ProjectionChanged(ValueError):
    """An accessible source no longer has the reviewed structure."""


@dataclass(frozen=True)
class Reference:
    repository: str
    pin: str
    path: str
    projection: str


REFERENCES = (
    Reference(PORTAL, PORTAL_PIN, "docs/superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md", "manifest-spec"),
    Reference(KERNEL, KERNEL_PIN, "apps/platform-api/src/anytoolai_platform_api/bootstrap.py", "composition"),
    Reference(KERNEL, KERNEL_PIN, "packages/backend/platform-core/src/anytoolai_platform_core/config/registry.py", "registry"),
    Reference(KERNEL, KERNEL_PIN, "packages/backend/product-platforms/freelancer-suite/src/anytoolai_freelancer_suite/bundle.py", "bundle"),
    Reference(KERNEL, KERNEL_PIN, "packages/backend/product-platforms/freelancer-suite/src/anytoolai_freelancer_suite/products/proposal_ai/product.yaml", "selected-product"),
)


def markdown_segment(text: str, start: str, end: str) -> str:
    try:
        segment = text.split(start + "\n", 1)[1].split(end + "\n", 1)
    except IndexError:
        raise ProjectionChanged() from None
    if len(segment) != 2:
        raise ProjectionChanged()
    return "\n".join(line.rstrip() for line in segment[0].strip().splitlines())


def project(source: str, kind: str) -> Any:
    """Only reviewed manifest segments and selected identity facts, never exec."""
    if kind == "manifest-spec":
        return {
            "auth": markdown_segment(source, "## Service authentication", "## Capability Manifest"),
            "manifest": markdown_segment(source, "## Capability Manifest", "### Portal import and freshness"),
        }
    if kind == "selected-product":
        result = {}
        for field in ("product_id", "product_platform"):
            matches = re.findall(rf"^{field}:\s*([^\s#]+)\s*$", source, re.MULTILINE)
            if len(matches) != 1:
                raise ProjectionChanged()
            result[field] = matches[0]
        return result
    try:
        tree = ast.parse(source)
        if kind == "composition":
            defaults = next(
                node for node in tree.body
                if isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "DEFAULT_PRODUCT_BUNDLES"
            )
            runtime = next(
                node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "build_runtime"
            )
            roots = next(
                node.value for node in runtime.body
                if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "extra_product_roots" for target in node.targets)
            )
            registry_call = next(
                node for node in ast.walk(runtime)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "build_config_registry"
            )
            registry_roots = next(item.value for item in registry_call.keywords if item.arg == "extra_product_roots")
            return {
                "default_suite": any(
                    isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "FreelancerSuiteBundle" for node in ast.walk(defaults)
                ),
                "kernel_demo_identity": any(
                    isinstance(node, ast.Constant) and node.value == "kernel_demo" for node in ast.walk(runtime)
                ),
                "product_roots": ast.dump(roots, include_attributes=False),
                "registry_product_roots": ast.dump(registry_roots, include_attributes=False),
            }
        if kind == "bundle":
            bundle = next(
                node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "FreelancerSuiteBundle"
            )
            roots = next(
                node for node in bundle.body if isinstance(node, ast.FunctionDef) and node.name == "config_roots"
            )
            # Additional products are outside the retained fixture's provenance.
            literals = {
                node.value for node in ast.walk(roots)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            }
            bundle_id = next(
                node.value for node in bundle.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "bundle_id" for target in node.targets)
            )
            return {"bundle_id": ast.literal_eval(bundle_id), "selected_roots": sorted(SELECTED_PRODUCTS & literals)}
        if kind == "registry":
            registry = next(
                node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ConfigRegistry"
            )
            products = next(
                node for node in registry.body if isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name) and node.target.id == "products"
            )
            lookup = next(
                node for node in registry.body if isinstance(node, ast.FunctionDef) and node.name == "get_product"
            )
            # Ignore method docstrings and unrelated registry entries/quotas.
            returns = [
                ast.dump(node, include_attributes=False) for node in ast.walk(lookup) if isinstance(node, ast.Return)
            ]
            return {"products": ast.dump(products.annotation, include_attributes=False), "lookup": returns}
    except (SyntaxError, StopIteration, ValueError, TypeError):
        raise ProjectionChanged() from None
    raise ProjectionChanged()


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class GitHubReader:
    """One fixed GitHub API origin; bounded reads, no redirects/retry/fallback."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    async def read(self, path: str, *, raw: bool = False, ref: str | None = None) -> bytes:
        headers = {"Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json"}
        async with self.http.stream("GET", path, headers=headers, params={"ref": ref} if ref else None) as response:
            if response.status_code != 200:
                # A 404 may mean lack of private-repo permission, not deletion.
                raise SourceUnavailable("source_http_unavailable")
            result = bytearray()
            async for part in response.aiter_bytes():
                if len(result) + len(part) > MAX_RESPONSE_BYTES:
                    raise SourceUnavailable("source_response_limit")
                result.extend(part)
        return bytes(result)

    async def default_commit(self, repository: str) -> str:
        metadata = json.loads(await self.read(f"/repos/{repository}"))
        branch = metadata["default_branch"]
        if not isinstance(branch, str) or not branch:
            raise SourceUnavailable("source_default_branch_unknown")
        commit = json.loads(await self.read(f"/repos/{repository}/commits/{quote(branch, safe='')}"))["sha"]
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise SourceUnavailable("source_commit_unknown")
        return commit

    async def file(self, reference: Reference, commit: str) -> str:
        content = await self.read(f"/repos/{reference.repository}/contents/{reference.path}", raw=True, ref=commit)
        return content.decode("utf-8")


async def check_references(http: httpx.AsyncClient) -> dict[str, Any]:
    reports: list[dict[str, str]] = []
    pending: dict[str, str] = {}
    reader = GitHubReader(http)

    async def collect() -> None:
        commits = {}
        for repository in (PORTAL, KERNEL):
            pending.update(repository=repository, path="default-branch commit")
            commits[repository] = await reader.default_commit(repository)
        for reference in REFERENCES:
            pending.update(repository=reference.repository, path=reference.path)
            pinned = await reader.file(reference, reference.pin)
            current = await reader.file(reference, commits[reference.repository])
            try:
                baseline = fingerprint(project(pinned, reference.projection))
            except ProjectionChanged:
                raise SourceUnavailable("pinned_projection_unavailable") from None
            try:
                observed = fingerprint(project(current, reference.projection))
            except ProjectionChanged:
                # Accessible but changed/deleted sections must require review.
                observed = "UNRECOGNIZED_SOURCE_STRUCTURE"
            reports.append({
                "repository": reference.repository, "path": reference.path,
                "pin": reference.pin, "observed_commit": commits[reference.repository],
                "pinned_fingerprint": baseline, "observed_fingerprint": observed,
                "status": ReferenceStatus.PASS if baseline == observed else ReferenceStatus.CHANGED,
            })

    try:
        async with asyncio.timeout(MAX_SECONDS):
            await collect()
    except (SourceUnavailable, httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError):
        status = ReferenceStatus.UNKNOWN
        unavailable = {**pending, "status": ReferenceStatus.UNKNOWN}
    else:
        status = ReferenceStatus.CHANGED if any(item["status"] == ReferenceStatus.CHANGED for item in reports) else ReferenceStatus.PASS
        unavailable = None
    # Known drift remains actionable even if another source cannot be checked.
    if any(item["status"] == ReferenceStatus.CHANGED for item in reports):
        status = ReferenceStatus.CHANGED
    return {
        "LOCAL_SPEC_CONFORMANCE": "NOT_RUN",
        "REFERENCE_SOURCE_CHECK": status,
        "REFERENCE_WATCH_OPERATIONAL": "NOT_YET_OPERATIONAL",
        "REAL_KERNEL_CONFORMANCE": "DEFERRED_NOT_IMPLEMENTED",
        "source_access_complete": len(reports) == len(REFERENCES),
        "unavailable_reference": unavailable,
        "references": reports,
    }


async def run() -> dict[str, Any]:
    # Explicit read-only fine-grained credential, scoped to BOTH source repos.
    # No raw.githubusercontent.com/public URL fallback for private sources.
    token = os.environ.get("KERNEL_REFERENCE_GITHUB_TOKEN", "")
    headers = {"X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(
        base_url="https://api.github.com", headers=headers, timeout=5,
        follow_redirects=False, trust_env=False,
    ) as http:
        return await check_references(http)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        report = asyncio.run(run())
    except (ValueError, httpx.HTTPError, OSError):
        # Client/credential setup failures must not print sensitive exception data.
        report = {
            "LOCAL_SPEC_CONFORMANCE": "NOT_RUN",
            "REFERENCE_SOURCE_CHECK": ReferenceStatus.UNKNOWN,
            "REFERENCE_WATCH_OPERATIONAL": "NOT_YET_OPERATIONAL",
            "REAL_KERNEL_CONFORMANCE": "DEFERRED_NOT_IMPLEMENTED",
            "source_access_complete": False,
            "unavailable_reference": {"path": "source client configuration", "status": ReferenceStatus.UNKNOWN},
            "references": [],
        }
    print(json.dumps(report, indent=2))
    if report["REFERENCE_SOURCE_CHECK"] == ReferenceStatus.PASS:
        return 0
    return 1 if report["REFERENCE_SOURCE_CHECK"] == ReferenceStatus.CHANGED else 2


if __name__ == "__main__":
    raise SystemExit(main())
