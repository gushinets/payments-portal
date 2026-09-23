from __future__ import annotations

import argparse
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import scripts.repo as repo
from scripts.repo import (
    canonical_check_environment,
    check_canonical_persisted_model_layer,
    check_documented_metadata_tables,
    check_external_billing_documentation_precedence,
    check_expected_legal_versions,
    check_required_markdown_link_content,
    direct_api_environment,
    host_database_url_from_runtime,
    api_test_environment,
    build_parser,
    validate_production_caddy_domain,
    validate_production_deployment_environment,
    uv_environment,
)


@pytest.mark.parametrize(
    "body",
    [
        "## Linear issue\nhttps://linear.app/paveldik/issue/ANY-337",
        "## Linear issue\nhttps://linear.app/paveldik/issue/ANY-337/add-validation\n",
        "## Linear issue\n[Ticket](https://linear.app/paveldik/issue/ANY-337)\n",
        "## Linear issue\n<https://linear.app/paveldik/issue/ANY-337>\n",
        "## Summary\nhttps://example.com\n## Linear issue\n"
        "https://linear.app/paveldik/issue/ANY-337\n## Debt\n"
        "https://linear.app/paveldik/issue/ANY-999/other\n",
        "## Linear issue\nhttps://linear.app/paveldik/issue/ANY-337\nhttps://example.com\uff0fabc",
    ],
)
def test_pr_metadata_accepts_matching_issue(body: str) -> None:
    repo.validate_pr_metadata("ANY-337 - Add validation", body)


@pytest.mark.parametrize(
    "title",
    [
        "337 - Add validation",
        "ANY-0 - Add validation",
        "ANY-337",
        "ANY-337 -",
        "ANY-337 - ",
        "ANY-337 -  summary",
        "ANY-abc - Add validation",
        "ANY-0337 - Add validation",
        "ANY-337: Add validation",
        "ANY-337 - summary\n",
    ],
)
def test_pr_metadata_rejects_invalid_title(title: str) -> None:
    with pytest.raises(repo.HarnessError, match="Invalid PR title.*Required format"):
        repo.validate_pr_metadata(title, "## Linear issue\nhttps://linear.app/paveldik/issue/ANY-337")


@pytest.mark.parametrize(
    "body",
    [
        "",
        "## Summary\nhttps://linear.app/paveldik/issue/ANY-337",
        "## Linear issue\n## Linear issue\n",
        "```md\n## Linear issue\nhttps://linear.app/paveldik/issue/ANY-337\n```",
    ],
)
def test_pr_metadata_requires_one_rendered_section(body: str) -> None:
    with pytest.raises(repo.HarnessError, match="exactly one rendered '## Linear issue' section"):
        repo.validate_pr_metadata("ANY-337 - Add validation", body)


@pytest.mark.parametrize(
    "content",
    [
        "",
        "ANY-337",
        "https://linear.app/other/issue/ANY-337",
        "https://example.com/paveldik/issue/ANY-337",
        "http://linear.app/paveldik/issue/ANY-337",
        "https://linear.app.evil.test/paveldik/issue/ANY-337",
        "https://linear.app/paveldik/issue/ANY-337oops",
        "[Ticket](https://linear.app/paveldik/issue/ANY-337(extra))",
        "https://linear.app/paveldik/issue/ANY-0",
        "https://linear.app/paveldik/issue/ANY-337\nhttps://linear.app/paveldik/issue/ANY-338",
        "https://linear.app/paveldik/issue/ANY-337\nhttps://linear.app/paveldik/issue/ANY-337",
        "https://linear.app/paveldik/issue/ANY-337\nhttps://linear.app/other/issue/ANY-338",
        "## Summary\nhttps://linear.app/paveldik/issue/ANY-337",
        "```\nhttps://linear.app/paveldik/issue/ANY-337\n```",
    ],
)
def test_pr_metadata_requires_one_full_linear_url(content: str) -> None:
    with pytest.raises(repo.HarnessError, match="exactly one full Linear issue URL"):
        repo.validate_pr_metadata("ANY-337 - Add validation", "## Linear issue\n" + content)


@pytest.mark.parametrize("fence", ["```", "~~~", "````", "~~~~"])
@pytest.mark.parametrize("real_issue", ["ANY-337", "ANY-338"])
def test_pr_metadata_uses_real_section_after_fenced_markdown(fence: str, real_issue: str) -> None:
    body = (
        f"{fence}md\n## Linear issue\nhttps://linear.app/paveldik/issue/ANY-337/fake\n"
        f"{fence}\n\n## Linear issue\nhttps://linear.app/paveldik/issue/{real_issue}/real\n"
    )
    if real_issue == "ANY-337":
        repo.validate_pr_metadata("ANY-337 - Add validation", body)
    else:
        with pytest.raises(repo.HarnessError, match="ANY-337 does not match Linear URL issue ANY-338"):
            repo.validate_pr_metadata("ANY-337 - Add validation", body)


def test_pr_metadata_ignores_different_issue_in_fenced_section() -> None:
    repo.validate_pr_metadata(
        "ANY-337 - Add validation",
        "```md\n## Linear issue\nhttps://linear.app/paveldik/issue/ANY-999/fake\n```\n"
        "## Linear issue\nhttps://linear.app/paveldik/issue/ANY-337/real",
    )


@pytest.mark.parametrize("closing", ["~~~", "``", "```not-a-close"])
def test_pr_metadata_does_not_close_fence_with_invalid_marker(closing: str) -> None:
    body = f"```md\n{closing}\n## Linear issue\nhttps://linear.app/paveldik/issue/ANY-337"
    with pytest.raises(repo.HarnessError, match="exactly one rendered"):
        repo.validate_pr_metadata("ANY-337 - Add validation", body)


@pytest.mark.parametrize(
    ("title", "body", "exit_code", "message"),
    [
        (
            "ANY-337 - Add validation",
            "## Linear issue\nhttps://linear.app/paveldik/issue/ANY-337",
            0,
            "PR metadata is valid.",
        ),
        ("ANY-0 - Invalid", "", 1, "Invalid PR title"),
        ("ANY-337 - Missing section", "", 1, "exactly one rendered"),
        (
            "ANY-337 - Mismatch",
            "## Linear issue\nhttps://linear.app/paveldik/issue/ANY-338",
            1,
            "ANY-337 does not match Linear URL issue ANY-338",
        ),
    ],
)
def test_pr_metadata_cli_reports_validation_without_traceback(
    title: str,
    body: str,
    exit_code: int,
    message: str,
) -> None:
    result = subprocess.run(
        [sys.executable, str(repo.ROOT / "scripts/repo.py"), "pr-metadata"],
        env={**os.environ, "PR_TITLE": title, "PR_BODY": body},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == exit_code
    assert message in result.stdout + result.stderr
    assert "Traceback" not in result.stderr


def _write_api_source(root: Path, relative: str, source: str) -> None:
    path = root / "apps/api/app" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_canonical_persisted_model_guard_rejects_billing_model_facade(tmp_path: Path) -> None:
    _write_api_source(tmp_path, "domains/billing/models.py", "from app.models import Order\n")

    errors = check_canonical_persisted_model_layer(tmp_path)

    assert any("domains/billing/models.py is forbidden" in error for error in errors)


def test_canonical_persisted_model_guard_rejects_billing_model_import(tmp_path: Path) -> None:
    _write_api_source(tmp_path, "feature.py", "from app.domains.billing.models import Order\n")

    errors = check_canonical_persisted_model_layer(tmp_path)

    assert any("imports ORM models through app.domains.billing.models" in error for error in errors)


def test_canonical_persisted_model_guard_rejects_duplicate_enum_definition(tmp_path: Path) -> None:
    _write_api_source(tmp_path, "feature.py", "class PaymentStatus: pass\n")

    errors = check_canonical_persisted_model_layer(tmp_path)

    assert any("defines protected persisted enum PaymentStatus" in error for error in errors)


def test_canonical_persisted_model_guard_rejects_removed_enum_facades(tmp_path: Path) -> None:
    _write_api_source(
        tmp_path,
        "feature.py",
        "from app.domains.billing.enums import PaymentStatus\nfrom app.domains.legal.enums import AcceptanceKind\n",
    )

    errors = check_canonical_persisted_model_layer(tmp_path)

    assert any("imports PaymentStatus through the removed billing enum façade" in error for error in errors)
    assert any("imports the removed legal enum façade" in error for error in errors)


def test_canonical_persisted_model_guard_allows_canonical_definition(tmp_path: Path) -> None:
    _write_api_source(tmp_path, "models/enums.py", "class PaymentStatus: pass\n")

    assert check_canonical_persisted_model_layer(tmp_path) == []


def test_canonical_persisted_model_guard_allows_unrelated_provider_enum(tmp_path: Path) -> None:
    _write_api_source(
        tmp_path,
        "domains/billing/enums.py",
        "from enum import StrEnum\n\nclass ProviderSubscriptionState(StrEnum):\n    ACTIVE = 'active'\n",
    )

    assert check_canonical_persisted_model_layer(tmp_path) == []


def test_canonical_persisted_model_guard_rejects_relative_billing_model_import(tmp_path: Path) -> None:
    _write_api_source(tmp_path, "domains/checkout/feature.py", "from ..billing.models import Order\n")

    errors = check_canonical_persisted_model_layer(tmp_path)

    assert any("imports ORM models through app.domains.billing.models" in error for error in errors)


def test_canonical_persisted_model_guard_rejects_relative_billing_enum_import(tmp_path: Path) -> None:
    _write_api_source(tmp_path, "domains/checkout/feature.py", "from ..billing.enums import PaymentStatus\n")

    errors = check_canonical_persisted_model_layer(tmp_path)

    assert any("imports PaymentStatus through the removed billing enum façade" in error for error in errors)


def test_canonical_persisted_model_guard_rejects_relative_legal_enum_import(tmp_path: Path) -> None:
    _write_api_source(tmp_path, "domains/checkout/feature.py", "from ..legal.enums import AcceptanceKind\n")

    errors = check_canonical_persisted_model_layer(tmp_path)

    assert any("imports the removed legal enum façade" in error for error in errors)


def test_canonical_persisted_model_guard_allows_relative_provider_enum_import(tmp_path: Path) -> None:
    _write_api_source(
        tmp_path,
        "domains/billing/enums.py",
        "from enum import StrEnum\n\nclass ProviderSubscriptionState(StrEnum):\n    ACTIVE = 'active'\n",
    )
    _write_api_source(
        tmp_path,
        "domains/checkout/feature.py",
        "from ..billing.enums import ProviderSubscriptionState\n",
    )

    assert check_canonical_persisted_model_layer(tmp_path) == []


def test_consistent_knowledge_fixture_passes() -> None:
    root = Path("repository").resolve()
    source = root / "AGENTS.md"
    authority = root / "docs" / "PRODUCT.md"

    assert (
        check_required_markdown_link_content(
            source,
            "[Product](docs/PRODUCT.md)\n",
            [authority],
            root=root,
        )
        == []
    )
    assert (
        check_expected_legal_versions(
            "2026-07-11",
            [
                ("docs/README.md", ["2026-07-11"], 1),
                ("migration", ["2026-07-11"] * 6, 6),
            ],
        )
        == []
    )


def test_missing_core_authority_link_is_actionable() -> None:
    root = Path("repository").resolve()
    source = root / "AGENTS.md"
    authority = root / "docs" / "PRODUCT.md"

    assert check_required_markdown_link_content(
        source,
        "# Repository map\n",
        [authority],
        root=root,
    ) == [f"Missing core authority link in AGENTS.md: {Path('docs') / 'PRODUCT.md'}"]


@pytest.mark.parametrize(
    ("source_relative", "target_relative"),
    [
        (
            source,
            target,
        )
        for source in (
            "AGENTS.md",
            "README.md",
            "apps/api/AGENTS.md",
            "ARCHITECTURE.md",
            "docs/README.md",
            "docs/PRODUCT.md",
            "docs/RELIABILITY.md",
            "docs/engineering/CODING_CONVENTIONS.md",
            "docs/architecture/contours.md",
            "docs/architecture/billing-authority.md",
        )
        for target in (
            "docs/architecture/decisions/0005-external-billing-boundary.md",
            "docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md",
            "docs/superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md",
        )
    ]
    + [
        (
            "docs/architecture/payment-providers.md",
            "docs/architecture/decisions/0005-external-billing-boundary.md",
        ),
        (
            "docs/architecture/payment-providers.md",
            "docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md",
        ),
        (
            "docs/architecture/payment-portal-data-model.md",
            "docs/architecture/decisions/0005-external-billing-boundary.md",
        ),
        (
            "docs/architecture/payment-portal-data-model.md",
            "docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md",
        ),
        (
            "docs/architecture/platform-kernel-contract.md",
            "docs/architecture/decisions/0005-external-billing-boundary.md",
        ),
        (
            "docs/architecture/platform-kernel-contract.md",
            "docs/superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md",
        ),
    ]
    + [
        (
            source,
            "docs/architecture/decisions/0005-external-billing-boundary.md",
        )
        for source in (
            "docs/architecture/decisions/0001-multi-contour-billing.md",
            "docs/architecture/decisions/0002-plan-based-checkout-identity.md",
            "docs/architecture/decisions/0004-billing-authority-and-consistency.md",
            "docs/architecture/decisions/README.md",
        )
    ],
)
def test_external_billing_authority_graph_is_guarded_and_consistent(
    source_relative: str,
    target_relative: str,
) -> None:
    source = repo.ROOT / source_relative
    target = repo.ROOT / target_relative

    assert target in repo.CORE_AUTHORITY_LINKS[source]
    assert repo.check_required_markdown_links(source, [target]) == []


def _write_external_billing_documentation_fixture(root: Path) -> None:
    documents = {
        "AGENTS.md": ("For all new billing work, follow this target authority chain in order:\n"),
        "docs/RELIABILITY.md": (
            "Status: authoritative operational requirements; target "
            "external-billing semantics delegated\n"
            "Target external-billing authority\n"
        ),
        "docs/architecture/contours.md": (
            "Status: authoritative target architecture; implemented product remains `ru`\n"
            "Target billing ownership authority:\n"
        ),
        "docs/PRODUCT.md": (
            "Status: authoritative\nTarget billing ownership and authoritative facts follow, in precedence order,\n"
        ),
        "docs/architecture/decisions/0005-external-billing-boundary.md": ("Status: accepted\n"),
        "docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md": (
            "Status: accepted implementation baseline\n"
        ),
        "docs/superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md": (
            "Status: accepted implementation baseline\n"
        ),
        "docs/architecture/decisions/0002-plan-based-checkout-identity.md": (
            "Status: superseded for new billing development\n"
        ),
        "docs/architecture/decisions/0004-billing-authority-and-consistency.md": (
            "Status: superseded for new billing development\n"
        ),
        "docs/architecture/billing-authority.md": (
            "Status: superseded target architecture; retained "
            "historical/current-state reference\n"
            "This document is not an authority for new billing development.\n"
        ),
        "docs/architecture/payment-providers.md": (
            "LEGACY / TRANSITIONAL REFERENCE — NOT TARGET ARCHITECTURE\n"
            "Status: retained current-state characterization of the "
            "direct-provider boundary\n"
        ),
        "docs/architecture/payment-portal-data-model.md": (
            "Status: authoritative current-state schema reference; not target external-billing "
            "persistence design\n"
            "CURRENT-STATE SCHEMA REFERENCE — NOT TARGET PERSISTENCE DESIGN\n"
        ),
        "docs/architecture/platform-kernel-contract.md": (
            "Status: superseded planned contract; retained historical context only\nSUPERSEDED CONTRACT NOTICE\n"
        ),
    }
    for relative, content in documents.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for filename in repo.SUPERSEDED_BILLING_PLANS:
        path = root / "docs/exec-plans/superseded" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Retained history\n", encoding="utf-8")


def test_external_billing_documentation_precedence_accepts_consistent_fixture(
    tmp_path: Path,
) -> None:
    _write_external_billing_documentation_fixture(tmp_path)

    assert check_external_billing_documentation_precedence(root=tmp_path) == []


def test_external_billing_documentation_precedence_reports_wrong_status(
    tmp_path: Path,
) -> None:
    _write_external_billing_documentation_fixture(tmp_path)
    relative = Path("docs/architecture/decisions/0005-external-billing-boundary.md")
    (tmp_path / relative).write_text("Status: proposed\n", encoding="utf-8")

    assert check_external_billing_documentation_precedence(root=tmp_path) == [
        "Incorrect external-billing documentation classification in "
        f"{relative.as_posix()}: expected exactly one active status "
        "'status: accepted', found 'status: proposed'"
    ]


def test_external_billing_documentation_precedence_rejects_historical_expected_status(
    tmp_path: Path,
) -> None:
    _write_external_billing_documentation_fixture(tmp_path)
    relative = Path("docs/architecture/decisions/0005-external-billing-boundary.md")
    (tmp_path / relative).write_text(
        "Status: proposed\n\nPrevious status: accepted\n",
        encoding="utf-8",
    )

    assert check_external_billing_documentation_precedence(root=tmp_path) == [
        "Incorrect external-billing documentation classification in "
        f"{relative.as_posix()}: expected exactly one active status "
        "'status: accepted', found 'status: proposed'"
    ]


def test_external_billing_documentation_precedence_rejects_status_after_header(
    tmp_path: Path,
) -> None:
    _write_external_billing_documentation_fixture(tmp_path)
    relative = Path("docs/architecture/decisions/0005-external-billing-boundary.md")
    (tmp_path / relative).write_text(
        "# Document\n\n## Historical context\n\nStatus: accepted\n",
        encoding="utf-8",
    )

    assert check_external_billing_documentation_precedence(root=tmp_path) == [
        "Incorrect external-billing documentation classification in "
        f"{relative.as_posix()}: expected exactly one active status "
        "'status: accepted', found none"
    ]


def test_external_billing_documentation_precedence_rejects_multiple_active_statuses(
    tmp_path: Path,
) -> None:
    _write_external_billing_documentation_fixture(tmp_path)
    relative = Path("docs/architecture/decisions/0005-external-billing-boundary.md")
    (tmp_path / relative).write_text(
        "Status: accepted\nStatus: proposed\n\n## Historical context\n",
        encoding="utf-8",
    )

    assert check_external_billing_documentation_precedence(root=tmp_path) == [
        "Incorrect external-billing documentation classification in "
        f"{relative.as_posix()}: expected exactly one active status "
        "'status: accepted', found 'status: accepted', 'status: proposed'"
    ]


def test_external_billing_documentation_precedence_requires_banner_in_header(
    tmp_path: Path,
) -> None:
    _write_external_billing_documentation_fixture(tmp_path)
    relative = Path("docs/architecture/payment-portal-data-model.md")
    (tmp_path / relative).write_text(
        "Status: authoritative current-state schema reference; not target "
        "external-billing persistence design\n\n"
        "## Historical context\n\n"
        "CURRENT-STATE SCHEMA REFERENCE — NOT TARGET PERSISTENCE DESIGN\n",
        encoding="utf-8",
    )

    assert check_external_billing_documentation_precedence(root=tmp_path) == [
        "Incorrect external-billing documentation classification in "
        f"{relative.as_posix()}: expected header marker "
        "'current-state schema reference — not target persistence design'"
    ]


@pytest.mark.parametrize(
    ("relative", "stale_authority", "expected_marker"),
    [
        (
            Path("docs/RELIABILITY.md"),
            "ANY-497 external billing command flows and reconciliation remain future work.\n",
            "any-497 external billing command flows and reconciliation remain future work",
        ),
        (
            Path("docs/architecture/contours.md"),
            "Billing ownership: [ADR 0004](decisions/0004-billing-authority-and-consistency.md)\n",
            "billing ownership: [adr 0004]",
        ),
        (
            Path("docs/PRODUCT.md"),
            "The private regional entitlement/access API for Platform Kernel is planned under ANY-79.\n",
            "private regional entitlement/access api for platform kernel is planned under any-79",
        ),
    ],
)
def test_external_billing_documentation_precedence_rejects_stale_executable_authority(
    tmp_path: Path,
    relative: Path,
    stale_authority: str,
    expected_marker: str,
) -> None:
    _write_external_billing_documentation_fixture(tmp_path)
    path = tmp_path / relative
    path.write_text(path.read_text(encoding="utf-8") + stale_authority, encoding="utf-8")

    assert check_external_billing_documentation_precedence(root=tmp_path) == [
        f"Stale executable billing authority in {relative.as_posix()}: marker {expected_marker!r}"
    ]


def test_external_billing_documentation_precedence_allows_historical_any_497_reference(
    tmp_path: Path,
) -> None:
    _write_external_billing_documentation_fixture(tmp_path)
    reliability = tmp_path / "docs/RELIABILITY.md"
    reliability.write_text(
        reliability.read_text(encoding="utf-8") + "ANY-497 was cancelled and superseded by ANY-504.\n",
        encoding="utf-8",
    )

    assert check_external_billing_documentation_precedence(root=tmp_path) == []


def test_external_billing_documentation_precedence_rejects_reactivated_plan(
    tmp_path: Path,
) -> None:
    _write_external_billing_documentation_fixture(tmp_path)
    filename = repo.SUPERSEDED_BILLING_PLANS[0]
    active = tmp_path / "docs/exec-plans/active" / filename
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_text("# Incorrectly active\n", encoding="utf-8")
    relative = Path("docs/exec-plans/active") / filename

    assert check_external_billing_documentation_precedence(root=tmp_path) == [
        f"Superseded billing execution plan must not remain active: {relative.as_posix()}"
    ]


def test_external_billing_documentation_precedence_requires_retained_plan(
    tmp_path: Path,
) -> None:
    _write_external_billing_documentation_fixture(tmp_path)
    filename = repo.SUPERSEDED_BILLING_PLANS[-1]
    (tmp_path / "docs/exec-plans/superseded" / filename).unlink()
    relative = Path("docs/exec-plans/superseded") / filename

    assert check_external_billing_documentation_precedence(root=tmp_path) == [
        f"Missing retained superseded billing execution plan: {relative.as_posix()}"
    ]


def _normalized_document(relative: str) -> str:
    return " ".join((repo.ROOT / relative).read_text(encoding="utf-8").split())


def test_adr_0001_keeps_distinct_billing_integration_boundaries() -> None:
    adr = repo.ROOT / "docs/architecture/decisions/0001-multi-contour-billing.md"
    content = " ".join(adr.read_text(encoding="utf-8").split())

    assert "Portal-managed direct-provider flow" in content
    assert "external-billing-managed flow" in content
    assert "does not register a `PaymentProviderAdapter`" in content

    assert "Each contour registers its own payment-provider adapter." not in content


def test_external_billing_authority_sources_keep_ownership_distinct() -> None:
    adr = _normalized_document("docs/architecture/decisions/0005-external-billing-boundary.md")
    billing_design = _normalized_document("docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md")
    access_design = _normalized_document("docs/superpowers/specs/2026-09-15-portal-kernel-access-contract-design.md")

    assert "External Billing owns commercial billing truth and lifecycle" in adr
    assert "Payment Portal owns AnyToolAI identity and legal acceptance" in adr
    assert "Platform Kernel owns technical product and metric vocabulary" in adr
    assert "External Billing is not a `PaymentProviderAdapter`" in adr
    assert "Platform Kernel never communicates directly with LBX" in billing_design
    assert "Platform Kernel never calls External Billing directly" in access_design


def test_billing_consistency_docs_require_retry_safe_unknown_outcomes() -> None:
    reliability = _normalized_document("docs/RELIABILITY.md")
    billing_design = _normalized_document("docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md")

    assert "retry-safe orchestration" in reliability
    assert "do not assume every external command is idempotent" in reliability
    assert "outbound billing commands must be idempotent" not in reliability
    assert "A timeout or lost response is neither confirmed success nor confirmed failure" in reliability
    assert "Multiple plausible matches are ambiguous and never auto-bind" in billing_design


def test_billing_design_separates_provider_facts_from_paid_access() -> None:
    billing_design = _normalized_document("docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md")

    assert "Payments Portal is the authority for the derived **paid** access projection" in billing_design
    assert "Platform Kernel never consumes provider-specific billing facts" in billing_design
    assert "payment state, or manual operator input never create or resize a quota bucket" in billing_design
    assert "Payload content does not directly mutate entitlement" in billing_design


def test_external_billing_design_replaces_portal_commercial_orders() -> None:
    billing_design = _normalized_document("docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md")

    assert "`PurchaseIntent` is orchestration state, not a commercial Order" in billing_design
    assert "There is no Portal-owned commercial Order" in billing_design


def test_billing_docs_require_missed_notification_recovery() -> None:
    reliability = _normalized_document("docs/RELIABILITY.md")
    billing_design = _normalized_document("docs/superpowers/specs/2026-09-15-external-billing-boundary-design.md")

    reliability_normalized = reliability.lower()
    assert "notifications are completely missed" in reliability_normalized
    assert "correctness must not depend solely on webhook delivery" in reliability_normalized
    assert "Webhook is a priority hint only" in billing_design
    assert "Scheduled reconciliation/discovery is the correctness backstop" in billing_design


def test_reliability_docs_acknowledge_only_after_durable_webhook_receipt() -> None:
    reliability = (repo.ROOT / "docs/RELIABILITY.md").read_text(encoding="utf-8")
    normalized = " ".join(reliability.lower().split())

    assert normalized.index("authenticated and minimally validated") < normalized.index("durably persisted")
    assert normalized.index("durably persisted") < normalized.index("acknowledged according to integration policy")
    assert "processing, retry, and reconciliation then belong to payment portal" in normalized
    assert "retrying an application-level http failure" in normalized


def test_security_docs_keep_durable_webhook_receipt_safe_by_construction() -> None:
    security = (repo.ROOT / "docs/SECURITY.md").read_text(encoding="utf-8")

    assert "whitelist and redact data before storage" in security
    assert "Never persist raw query-string secrets" in security


def test_observability_docs_preserve_correlation_and_ownership_contract() -> None:
    reliability = (repo.ROOT / "docs/RELIABILITY.md").read_text(encoding="utf-8")
    security = (repo.ROOT / "docs/SECURITY.md").read_text(encoding="utf-8")
    reliability_normalized = " ".join(reliability.replace("`", "").lower().split())
    security_normalized = " ".join(security.replace("`", "").lower().split())

    for local_id in ("order_id", "payment_id", "subscription_id", "webhook_event_id", "run_id"):
        assert local_id in reliability_normalized
    assert "must never be metric labels" in reliability_normalized
    for local_id in ("order_id", "payment_id", "subscription_id", "webhook_event_id", "run_id"):
        assert local_id in security_normalized
    assert "must never become metric labels" in security_normalized
    assert "refund_id remains a local durable business and audit lookup reference" in reliability_normalized
    assert "not a new any-437 telemetry emission" in security_normalized

    assert "production monitoring and alerting work" in reliability_normalized
    assert "belongs to any-86" in reliability_normalized
    assert "sentry is a separate optional outbound backend application-error destination" in reliability_normalized
    assert (
        "does not replace the otlp backend, json logs, prometheus/opentelemetry metrics, or persisted state"
        in reliability_normalized
    )

    assert (
        "a failed run starts with subscription_expiry_run_started and ends with subscription_expiry_run_failed"
        in reliability_normalized
    )
    assert (
        "must not emit subscription_expiry_transition_committed or subscription_expiry_run_succeeded"
        in reliability_normalized
    )


def test_missing_external_billing_authority_link_is_actionable() -> None:
    root = Path("repository").resolve()
    source_relative = Path("apps") / "api" / "AGENTS.md"
    target_relative = Path("docs") / "architecture" / "decisions" / "0005-external-billing-boundary.md"
    source = root / source_relative
    authority = root / target_relative

    assert check_required_markdown_link_content(
        source,
        "# API Agent Guide\n",
        [authority],
        root=root,
    ) == [f"Missing core authority link in {source_relative}: {target_relative}"]


def test_stale_documented_legal_version_is_rejected() -> None:
    errors = check_expected_legal_versions("2026-07-11", [("docs/README.md", ["2026-07-02"], 1)])

    assert errors == [
        "Current legal version mismatch in docs/README.md: expected 1 occurrence(s) of 2026-07-11, found 2026-07-02"
    ]


def test_migration_legal_version_mismatch_is_rejected() -> None:
    errors = check_expected_legal_versions("2026-07-11", [("initial migration", ["2026-07-11"] * 5, 6)])

    assert errors == [
        "Current legal version mismatch in initial migration: expected 6 occurrence(s) "
        "of 2026-07-11, found 2026-07-11, 2026-07-11, 2026-07-11, "
        "2026-07-11, 2026-07-11"
    ]


def test_canonical_metadata_table_entry_is_accepted() -> None:
    assert (
        check_documented_metadata_tables(
            ["documented_table"],
            "| `documented_table` | Implemented | Purpose |\n",
        )
        == []
    )


def test_metadata_table_name_only_in_prose_is_still_missing() -> None:
    assert check_documented_metadata_tables(
        ["referenced_table"],
        "The `referenced_table` relation is discussed elsewhere.\n",
    ) == ["Implemented table missing from canonical data model: referenced_table"]


def test_missing_metadata_tables_are_reported_sorted() -> None:
    assert check_documented_metadata_tables(
        ["zeta_table", "documented_table", "alpha_table"],
        "| `documented_table` | Implemented | Purpose |\n",
    ) == [
        "Implemented table missing from canonical data model: alpha_table",
        "Implemented table missing from canonical data model: zeta_table",
    ]


def test_check_docs_uses_imported_metadata_tables(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FakeMetadata:
        tables = {
            "documented_table": object(),
            "metadata_only_table": object(),
        }

    class FakeBase:
        metadata = FakeMetadata()

    for required in (
        "AGENTS.md",
        "ARCHITECTURE.md",
        "docs/README.md",
        "docs/architecture/payment-portal-data-model.md",
        "docs/architecture/contours.md",
        "docs/architecture/region-resolver-contract.md",
        "docs/architecture/payment-providers.md",
        "docs/product/ru-mvp.md",
    ):
        path = tmp_path / required
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    (tmp_path / "docs/architecture/payment-portal-data-model.md").write_text(
        "| `documented_table` | Implemented | Purpose |\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(repo, "ROOT", tmp_path)
    monkeypatch.setattr(repo, "check_knowledge_hierarchy", lambda: [])
    monkeypatch.setattr(repo, "check_external_billing_documentation_precedence", lambda: [])
    monkeypatch.setattr(repo, "engineering_markdown_files", lambda: [])
    monkeypatch.setattr(repo, "import_api", lambda: (FakeBase, object()))

    assert repo.check_docs() == ["Implemented table missing from canonical data model: metadata_only_table"]


def test_canonical_checks_use_a_worktree_scoped_temp_directory(tmp_path: Path) -> None:
    first_root = tmp_path / "first-worktree"
    second_root = tmp_path / "second-worktree"
    original = {
        "PATH": "tools",
        "TEMP": "unreadable-system-temp",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:4318",
    }

    first = canonical_check_environment(root=first_root, environ=original)
    second = canonical_check_environment(root=second_root, environ=original)

    first_temp = (first_root / ".harness" / "tmp").resolve()
    second_temp = (second_root / ".harness" / "tmp").resolve()
    assert first["PATH"] == "tools"
    assert original["TEMP"] == "unreadable-system-temp"
    assert {first[name] for name in ("TEMP", "TMP", "TMPDIR")} == {str(first_temp)}
    assert {second[name] for name in ("TEMP", "TMP", "TMPDIR")} == {str(second_temp)}
    assert first["OTEL_EXPORTER_OTLP_ENDPOINT"] == ""
    assert second["OTEL_EXPORTER_OTLP_ENDPOINT"] == ""
    assert first["INSTANCE_TENANT_ID"] == "anytoolai"
    assert first["INSTANCE_REGION"] == "ru"
    assert second["INSTANCE_TENANT_ID"] == "anytoolai"
    assert second["INSTANCE_REGION"] == "ru"
    assert first_temp.is_dir()
    assert second_temp.is_dir()
    assert first_temp != second_temp


def test_production_compose_derives_database_url_from_postgres_environment() -> None:
    production_compose = Path("docker-compose.prod.yml").read_text(encoding="utf-8")
    production_example = Path(".env.production.example").read_text(encoding="utf-8")

    assert "DATABASE_URL=" not in production_example
    assert "DATABASE_URL: ${DATABASE_URL:?" not in production_compose
    assert "POSTGRES_DB: ${POSTGRES_DB:?POSTGRES_DB is required}" in production_compose
    assert "POSTGRES_USER: ${POSTGRES_USER:?POSTGRES_USER is required}" in production_compose
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}" in production_compose
    assert "POSTGRES_HOST: postgres" in production_compose
    assert "POSTGRES_PORT: 5432" in production_compose


def test_validate_production_caddy_domain_accepts_public_hostname() -> None:
    assert validate_production_caddy_domain("payments.example.test") == "payments.example.test"


@pytest.mark.parametrize(
    "value, message",
    [
        ("", "CADDY_DOMAIN is required"),
        ("https://payments.example.test", "CADDY_DOMAIN must not include a URL scheme"),
        ("localhost", "CADDY_DOMAIN must not use a loopback host in production"),
        ("127.0.0.1", "CADDY_DOMAIN must not use a loopback host in production"),
        ("[::1]", "CADDY_DOMAIN must not use a loopback host in production"),
        ("payments.example.test:443", "CADDY_DOMAIN must be a bare public hostname"),
        ("payments.example.test/path", "CADDY_DOMAIN must be a bare public hostname"),
    ],
)
def test_validate_production_caddy_domain_rejects_invalid_hostnames(value: str, message: str) -> None:
    with pytest.raises(repo.HarnessError, match=message):
        validate_production_caddy_domain(value)


def test_validate_production_deployment_environment_requires_public_caddy_domain() -> None:
    with pytest.raises(repo.HarnessError, match="CADDY_DOMAIN must not use a loopback host in production"):
        validate_production_deployment_environment(environ={"CADDY_DOMAIN": "localhost"})


def test_alembic_uses_validated_application_database_url() -> None:
    alembic_env = Path("apps/api/alembic/env.py").read_text(encoding="utf-8")

    assert "from app.core.settings import settings" in alembic_env
    assert 'os.getenv("DATABASE_URL")' not in alembic_env
    assert 'config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))' in alembic_env


def test_direct_api_environment_uses_host_database_url_from_runtime(
    monkeypatch,
) -> None:
    runtime_env = {
        "APP_ENV": "development",
        "APP_PUBLIC_BASE_URL": "http://localhost:39000",
        "CORS_ALLOW_ORIGINS": "http://localhost:39000",
        "DATABASE_URL": "postgresql+psycopg://anytoolai:anytoolai-local-only@postgres:5432/payments_test",
        "POSTGRES_DB": "payments_test",
        "POSTGRES_USER": "anytoolai",
        "POSTGRES_PASSWORD": "anytoolai-local-only",
        "POSTGRES_PORT": "32053",
    }
    monkeypatch.setattr(repo, "read_dotenv", dict)
    monkeypatch.setattr(repo, "read_runtime_env", lambda: runtime_env)

    environment = direct_api_environment(environ={})

    assert environment["APP_ENV"] == "development"
    assert environment["INSTANCE_TENANT_ID"] == "anytoolai"
    assert environment["INSTANCE_REGION"] == "ru"
    assert environment["DATABASE_URL"] == (
        "postgresql+psycopg://anytoolai:anytoolai-local-only@127.0.0.1:32053/payments_test"
    )
    assert environment["SKIP_LEGAL_SEED"] == "true"


def test_direct_api_environment_preserves_process_overrides(
    monkeypatch,
) -> None:
    runtime_env = {
        "APP_ENV": "development",
        "APP_PUBLIC_BASE_URL": "http://localhost:39000",
        "CORS_ALLOW_ORIGINS": "http://localhost:39000",
        "POSTGRES_DB": "payments_test",
        "POSTGRES_USER": "anytoolai",
        "POSTGRES_PASSWORD": "anytoolai-local-only",
        "POSTGRES_PORT": "32053",
    }
    monkeypatch.setattr(repo, "read_dotenv", lambda: {"LOG_LEVEL": "DEBUG", "DATABASE_URL": "sqlite:///dotenv.db"})
    monkeypatch.setattr(repo, "read_runtime_env", lambda: runtime_env)

    environment = direct_api_environment(
        environ={
            "LOG_LEVEL": "WARNING",
            "DATABASE_URL": "sqlite:///process.db",
        }
    )

    assert environment["LOG_LEVEL"] == "WARNING"
    assert environment["DATABASE_URL"] == "sqlite:///process.db"


def test_direct_api_environment_keeps_host_database_url_over_local_dotenv(
    monkeypatch,
) -> None:
    runtime_env = {
        "APP_ENV": "development",
        "APP_PUBLIC_BASE_URL": "http://localhost:39000",
        "CORS_ALLOW_ORIGINS": "http://localhost:39000",
        "POSTGRES_DB": "payments_test",
        "POSTGRES_USER": "anytoolai",
        "POSTGRES_PASSWORD": "anytoolai-local-only",
        "POSTGRES_PORT": "32053",
    }
    monkeypatch.setattr(
        repo,
        "read_dotenv",
        lambda: {"DATABASE_URL": "postgresql+psycopg://anytoolai:anytoolai@postgres:5432/anytoolai"},
    )
    monkeypatch.setattr(repo, "read_runtime_env", lambda: runtime_env)

    environment = direct_api_environment(environ={})

    assert environment["DATABASE_URL"] == (
        "postgresql+psycopg://anytoolai:anytoolai-local-only@127.0.0.1:32053/payments_test"
    )


def test_host_database_url_from_runtime_url_encodes_credentials() -> None:
    assert (
        host_database_url_from_runtime(
            {
                "POSTGRES_DB": "payments/test",
                "POSTGRES_USER": "any/tool",
                "POSTGRES_PASSWORD": "secret value",
                "POSTGRES_PORT": "32053",
            }
        )
        == "postgresql+psycopg://any%2Ftool:secret%20value@127.0.0.1:32053/payments%2Ftest"
    )


def test_uv_environment_targets_root_venv_without_activation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(repo, "ROOT", tmp_path)

    environment = uv_environment(
        environ={"PATH": "tools", "VIRTUAL_ENV": "/wrong/.venv"},
        python="/usr/bin/python3.12",
    )

    assert environment["UV_PROJECT_ENVIRONMENT"] == str((tmp_path / ".venv").resolve())
    assert environment["UV_PYTHON"] == "/usr/bin/python3.12"
    assert environment["UV_PYTHON_DOWNLOADS"] == "never"
    assert "VIRTUAL_ENV" not in environment
    assert environment["PATH"] == "tools"


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["test", "api"], "api"),
        (["sync-api"], "sync-api"),
        (["lock-api"], "lock-api"),
        (["check-api-lock"], "check-api-lock"),
        (["migrate-api"], "migrate-api"),
    ],
)
def test_repository_parser_accepts_api_tooling_commands(argv: list[str], expected: str) -> None:
    parsed = build_parser().parse_args(argv)
    assert parsed.command == expected if expected != "api" else parsed.target == expected


def test_test_db_commands_target_only_postgres(monkeypatch) -> None:
    config = repo.RuntimeConfig(
        worktree_id="test",
        compose_project="payments-test",
        database_name="payments_test",
        web_port=3000,
        api_port=8000,
        postgres_port=5432,
        grafana_port=3001,
        loki_port=3100,
        prometheus_port=9090,
        tempo_port=3200,
        otlp_grpc_port=4317,
        otlp_http_port=4318,
    )
    invocations: list[list[str]] = []
    monkeypatch.setattr(repo, "load_runtime", lambda: config)
    monkeypatch.setattr(repo, "write_runtime", lambda _: None)
    monkeypatch.setattr(repo, "compose_command", lambda _: ["docker", "compose"])
    monkeypatch.setattr(repo, "run", lambda command, **_: invocations.append(command))

    repo.cmd_test_db(argparse.Namespace(action="up"))
    repo.cmd_test_db(argparse.Namespace(action="stop"))

    assert invocations == [
        ["docker", "compose", "up", "-d", "--no-deps", "--wait", "postgres"],
        ["docker", "compose", "stop", "postgres"],
    ]


def test_api_test_environment_preserves_explicit_url(monkeypatch) -> None:
    environment = {"TEST_POSTGRES_DATABASE_URL": "postgresql+psycopg://explicit/db_tests"}
    monkeypatch.setattr(repo, "read_runtime_env", lambda: (_ for _ in ()).throw(AssertionError()))

    assert api_test_environment("api-postgres", environment) is environment


def test_api_test_environment_preserves_complete_explicit_postgres_configuration(monkeypatch) -> None:
    environment = {
        "POSTGRES_USER_TEST": "test-user",
        "POSTGRES_PASSWORD_TEST": "test-password",
        "POSTGRES_PORT_TEST": "5432",
        "POSTGRES_DB_TEST": "payments_test",
        "POSTGRES_HOST_TEST": "localhost",
    }
    monkeypatch.setattr(repo, "read_runtime_env", lambda: (_ for _ in ()).throw(AssertionError()))

    assert api_test_environment("api", environment) is environment


def test_api_test_environment_rejects_partial_explicit_postgres_configuration() -> None:
    with pytest.raises(repo.HarnessError, match="Incomplete PostgreSQL test configuration"):
        api_test_environment("api-postgres", {"POSTGRES_USER_TEST": "test-user"})


def test_api_test_environment_derives_worktree_test_database_url(monkeypatch) -> None:
    runtime_env = {
        "POSTGRES_DB": "payments_worktree",
        "POSTGRES_USER": "anytoolai",
        "POSTGRES_PASSWORD": "local-password",
        "POSTGRES_PORT": "32053",
    }
    monkeypatch.setattr(repo, "read_runtime_env", lambda: runtime_env)
    monkeypatch.setattr(repo, "port_is_free", lambda _: False)
    environment: dict[str, str] = {}

    result = api_test_environment("api", environment)

    assert result["TEST_POSTGRES_DATABASE_URL"] == (
        "postgresql+psycopg://anytoolai:local-password@127.0.0.1:32053/payments_worktree_tests"
    )


def test_api_test_environment_ignores_empty_explicit_url(monkeypatch) -> None:
    runtime_env = {
        "POSTGRES_DB": "payments_worktree",
        "POSTGRES_USER": "anytoolai",
        "POSTGRES_PASSWORD": "local-password",
        "POSTGRES_PORT": "32053",
    }
    monkeypatch.setattr(repo, "read_runtime_env", lambda: runtime_env)
    monkeypatch.setattr(repo, "port_is_free", lambda _: False)
    environment = {"TEST_POSTGRES_DATABASE_URL": ""}

    result = api_test_environment("api", environment)

    assert result["TEST_POSTGRES_DATABASE_URL"] != ""
    assert result["TEST_POSTGRES_DATABASE_URL"].endswith("/payments_worktree_tests")


def test_api_fast_test_environment_does_not_require_postgres(monkeypatch) -> None:
    monkeypatch.setattr(repo, "read_runtime_env", lambda: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(repo, "port_is_free", lambda _: (_ for _ in ()).throw(AssertionError()))

    assert api_test_environment("api-fast", {}) == {}


def test_makefile_contains_only_test_database_shortcuts() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    targets = [
        line[:-1]
        for line in makefile.splitlines()
        if line and not line.startswith((" ", "\t", "#")) and line.endswith(":")
    ]

    assert targets == ["test_db_up", "test_db_stop"]


def test_generated_registration_acceptance_contract_matches_backend_authority() -> None:
    generated = repo.GENERATED_REGISTRATION_ACCEPTANCE_TS.read_text(encoding="utf-8")

    assert generated == repo.render_registration_acceptance_typescript()


def test_registration_acceptance_generator_rejects_nonliteral_text(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "acceptance_text.py"
    source.write_text(
        'REGISTRATION_PERSONAL_CONSENT_TEXT = build_text()\nREGISTRATION_OFFER_CONSENT_TEXT = "Offer"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(repo, "REGISTRATION_ACCEPTANCE_TEXT_SOURCE", source)

    with pytest.raises(
        repo.HarnessError,
        match="Registration acceptance text must be a string literal",
    ):
        repo.registration_acceptance_texts()


def test_fast_check_passes_the_scoped_environment_to_every_subprocess(
    monkeypatch,
) -> None:
    check_environment = {"TEMP": "worktree-temp"}
    invocations: list[tuple[list[str], dict[str, str] | None]] = []

    monkeypatch.setattr(repo, "canonical_check_environment", lambda: check_environment)
    monkeypatch.setattr(repo, "cmd_docs", lambda _: None)
    monkeypatch.setattr(repo, "cmd_generate", lambda _: None)
    monkeypatch.setattr(repo, "cmd_architecture", lambda _: None)
    monkeypatch.setattr(repo, "tool", lambda name: name)
    monkeypatch.setattr(
        repo,
        "run",
        lambda command, **kwargs: invocations.append((command, kwargs.get("env"))),
    )

    repo.cmd_check(argparse.Namespace(fast=True))

    assert len(invocations) == 6
    assert all(environment is check_environment for _, environment in invocations)
    assert any(command[-3:] == ["ruff", "check", "."] for command, _ in invocations)
    assert any(command[-4:] == ["ruff", "format", "--check", "."] for command, _ in invocations)
    assert any("test:components" in command for command, _ in invocations)
    assert any(command[-3:] == ["-m", "not postgres", "apps/api/tests"] for command, _ in invocations)


def test_full_check_runs_explicit_postgres_partition(
    monkeypatch,
) -> None:
    check_environment = {
        "POSTGRES_USER_TEST": "test-user",
        "POSTGRES_PASSWORD_TEST": "test-password",
        "POSTGRES_PORT_TEST": "5432",
        "POSTGRES_DB_TEST": "payment_portal_test",
    }
    invocations: list[tuple[list[str], dict[str, str] | None]] = []

    monkeypatch.delenv("TEST_POSTGRES_DATABASE_URL", raising=False)
    monkeypatch.delenv("RUN_E2E", raising=False)
    monkeypatch.setattr(repo, "canonical_check_environment", lambda: check_environment)
    monkeypatch.setattr(repo, "cmd_docs", lambda _: None)
    monkeypatch.setattr(repo, "cmd_generate", lambda _: None)
    monkeypatch.setattr(repo, "cmd_architecture", lambda _: None)
    monkeypatch.setattr(repo, "tool", lambda name: name)
    monkeypatch.setattr(
        repo,
        "run",
        lambda command, **kwargs: invocations.append((command, kwargs.get("env"))),
    )

    repo.cmd_check(argparse.Namespace(fast=False))

    postgres_invocations = [
        (command, environment)
        for command, environment in invocations
        if command[-3:] == ["-m", "postgres", "apps/api/tests"]
    ]
    assert postgres_invocations == [
        (
            [
                repo.sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-m",
                "postgres",
                "apps/api/tests",
            ],
            check_environment,
        )
    ]


def test_api_coverage_writes_xml_to_stable_harness_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    check_environment = {"TEMP": "worktree-temp"}
    invocations: list[tuple[list[str], dict[str, str] | None]] = []

    monkeypatch.setattr(repo, "ROOT", tmp_path)
    monkeypatch.setattr(repo, "canonical_check_environment", lambda: check_environment)
    monkeypatch.setattr(
        repo,
        "run",
        lambda command, **kwargs: invocations.append((command, kwargs.get("env"))),
    )

    repo.cmd_coverage(argparse.Namespace(target="api-fast"))

    coverage_xml = tmp_path / ".harness" / "coverage" / "api" / "coverage.xml"
    assert coverage_xml.parent.is_dir()
    assert invocations == [
        (
            [
                repo.sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-m",
                "not postgres",
                "--cov=apps/api/app",
                "--cov-report=term-missing",
                f"--cov-report=xml:{coverage_xml}",
                "apps/api/tests",
            ],
            check_environment,
        )
    ]


def test_write_runtime_excludes_cloudpayments_configuration(
    monkeypatch,
    tmp_path: Path,
) -> None:
    harness_dir = tmp_path / ".harness"
    runtime_json = harness_dir / "runtime.json"
    runtime_env = harness_dir / "runtime.env"
    monkeypatch.setattr(repo, "HARNESS_DIR", harness_dir)
    monkeypatch.setattr(repo, "RUNTIME_JSON", runtime_json)
    monkeypatch.setattr(repo, "RUNTIME_ENV", runtime_env)
    monkeypatch.setattr(
        repo,
        "read_dotenv",
        lambda: {
            "CLOUDPAYMENTS_PUBLIC_ID": "pk_from_dotenv",
            "CLOUDPAYMENTS_API_SECRET": "secret-from-dotenv",
            "CLOUDPAYMENTS_ENABLED": "true",
        },
    )
    monkeypatch.setenv("CLOUDPAYMENTS_PUBLIC_ID", "pk_from_process")
    monkeypatch.setenv("CLOUDPAYMENTS_API_SECRET", "secret-from-process")
    monkeypatch.setenv("CLOUDPAYMENTS_ENABLED", "true")

    repo.write_runtime(
        repo.RuntimeConfig(
            worktree_id="test",
            compose_project="payment-portal-test",
            database_name="payment_portal_test",
            web_port=3000,
            api_port=8000,
            postgres_port=5432,
            grafana_port=3001,
            loki_port=3100,
            prometheus_port=9090,
            tempo_port=3200,
            otlp_grpc_port=4317,
            otlp_http_port=4318,
        )
    )

    assert stat.S_IMODE(harness_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(runtime_env.stat().st_mode) == 0o600
    runtime_contents = runtime_env.read_text(encoding="utf-8")
    assert "APP_ENV=development" in runtime_contents
    assert "INSTANCE_TENANT_ID=anytoolai" in runtime_contents
    assert "INSTANCE_REGION=ru" in runtime_contents
    assert "CLOUDPAYMENTS_PUBLIC_ID" not in runtime_contents
    assert "CLOUDPAYMENTS_API_SECRET" not in runtime_contents
    assert "CLOUDPAYMENTS_ENABLED" not in runtime_contents


def test_write_runtime_does_not_leave_secret_when_protection_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    harness_dir = tmp_path / ".harness"
    runtime_json = harness_dir / "runtime.json"
    runtime_env = harness_dir / "runtime.env"
    monkeypatch.setattr(repo, "HARNESS_DIR", harness_dir)
    monkeypatch.setattr(repo, "RUNTIME_JSON", runtime_json)
    monkeypatch.setattr(repo, "RUNTIME_ENV", runtime_env)
    monkeypatch.setattr(repo, "read_dotenv", lambda: {"SMTP_PASSWORD": "super-secret"})

    def fail_protection(path: Path) -> None:
        assert path.read_text(encoding="utf-8") == ""
        raise repo.HarnessError("protection failed")

    monkeypatch.setattr(repo, "protect_runtime_env_file", fail_protection)

    with pytest.raises(repo.HarnessError, match="protection failed"):
        repo.write_runtime(
            repo.RuntimeConfig(
                worktree_id="test",
                compose_project="payment-portal-test",
                database_name="payment_portal_test",
                web_port=3000,
                api_port=8000,
                postgres_port=5432,
                grafana_port=3001,
                loki_port=3100,
                prometheus_port=9090,
                tempo_port=3200,
                otlp_grpc_port=4317,
                otlp_http_port=4318,
            )
        )

    assert not runtime_env.exists()
    assert all(
        "super-secret" not in path.read_text(encoding="utf-8") for path in harness_dir.iterdir() if path.is_file()
    )


def test_runtime_env_windows_acl_removes_inheritance_for_current_user() -> None:
    invocations: list[list[str]] = []

    repo.protect_runtime_env_file(
        Path("C:/repo/.harness/runtime.env"),
        os_name="nt",
        environ={
            "USERNAME": "agent",
            "USERDOMAIN": "WORKSTATION",
            "COMPUTERNAME": "WORKSTATION",
        },
        runner=lambda command: invocations.append(command),
        icacls_path="icacls",
    )

    assert invocations == [
        [
            "icacls",
            "C:/repo/.harness/runtime.env",
            "/inheritance:r",
            "/grant:r",
            "agent:RW",
        ]
    ]


def test_harness_directory_windows_acl_removes_inheritance_for_current_user() -> None:
    invocations: list[list[str]] = []

    repo.protect_private_directory(
        Path("C:/repo/.harness"),
        os_name="nt",
        environ={
            "USERNAME": "agent",
            "USERDOMAIN": "WORKSTATION",
            "COMPUTERNAME": "WORKSTATION",
        },
        runner=lambda command: invocations.append(command),
        icacls_path="icacls",
    )

    assert invocations == [
        [
            "icacls",
            "C:/repo/.harness",
            "/inheritance:r",
            "/grant:r",
            "agent:(OI)(CI)F",
        ]
    ]


def test_runtime_env_windows_acl_preserves_domain_user() -> None:
    invocations: list[list[str]] = []

    repo.protect_runtime_env_file(
        Path("C:/repo/.harness/runtime.env"),
        os_name="nt",
        environ={
            "USERNAME": "agent",
            "USERDOMAIN": "ANYTOOL",
            "COMPUTERNAME": "WORKSTATION",
        },
        runner=lambda command: invocations.append(command),
        icacls_path="icacls",
    )

    assert invocations[0][-1] == "ANYTOOL\\agent:RW"


def test_runtime_env_windows_acl_requires_current_user() -> None:
    with pytest.raises(repo.HarnessError, match="current user is unknown"):
        repo.protect_runtime_env_file(
            Path("C:/repo/.harness/runtime.env"),
            os_name="nt",
            environ={},
            runner=lambda command: None,
            icacls_path="icacls",
        )
