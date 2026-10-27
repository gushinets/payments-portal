"""GET-only operator diagnosis and durable, redacted CREATE failure evidence."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing import bootstrap_account
from app.composition.customer_diagnostics import diagnose_customer
from app.composition.sources import source_resources
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.customers import (
    apply_customer_read,
    claim_customer_send,
    record_customer_create_failure,
    record_customer_receipt,
    reserve_customer,
)
from app.models import BillingWorkItem, ExternalBillingCustomer, ExternalCreateOperation, ManualReviewCase, User
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step2_postgres import TOKEN, seed

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("empty", "create_outcome_unknown"),
        ("saved_failure", "email_conflict"),
        ("historical", "email_conflict"),
        ("found", "customer_found_unbound"),
        ("foreign_owner", "identity_conflict"),
        ("key_mismatch", "identity_conflict"),
        ("receipt", "customer_found_unbound"),
        ("bound", "binding_verified"),
        ("email_only", "email_candidates_unproven"),
        ("wrong_receipt", "identity_conflict"),
        ("multiple", "candidates_ambiguous"),
        ("unavailable", "source_unavailable"),
    ],
)
def test_diagnosis_is_read_only_and_requires_original_identity(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], mode: str, expected: str
) -> None:
    factory = postgres_session_factory
    config = step1_settings(lbx_max_get_attempts=2)
    seed(factory)
    current = claim_customer_send(factory, config, TOKEN, reserve_customer(factory, config, TOKEN))
    if mode == "saved_failure":
        record_customer_create_failure(factory, current, http_status=500, lbx_code=500, reason="email_not_unique")
    if mode == "historical":
        with factory() as db:
            db.add(
                ManualReviewCase(
                    reason_code="owner_requested_curl_create_probe",
                    scope_kind="create_operation",
                    scope_reference=str(current.operation_id),
                    case_state="open",
                    evidence_schema_version="curl-customer-comparison:v1",
                    evidence_document={
                        "comparison_outcome": {
                            "owner_http": 500,
                            "owner_lbx_code": 500,
                            "safe_provider_reason": "email_must_be_unique",
                            "raw_error": "SECRET-EMAIL-AND-TOKEN",
                        }
                    },
                )
            )
            db.commit()
    if mode in {"receipt", "wrong_receipt", "bound"}:
        record_customer_receipt(factory, current, 345)
    if mode == "bound":
        apply_customer_read(factory, current, provider_id="345", outer_key=current.outer_key)
    with factory() as db:
        user_id = db.scalar(select(User.id))
    if mode == "foreign_owner":
        with factory() as db:
            other = User(
                id=uuid4(),
                tenant_id=config.instance_tenant_id,
                region=config.instance_region,
                email="other@example.com",
                email_normalized="other@example.com",
            )
            db.add(other)
            db.flush()
            db.add(
                ExternalBillingCustomer(
                    user_id=other.id,
                    billing_customer_key="foreign-key",
                    external_billing_account_id=config.lbx_external_billing_account_id,
                    provider_origin=config.lbx_provider_origin,
                    provider_customer_id="345",
                )
            )
            db.commit()
    calls = []
    statements = []
    connections_before = migrated_database.pool.checkedout()

    def respond(request: httpx.Request) -> httpx.Response:
        assert migrated_database.pool.checkedout() == connections_before  # No SQL session across HTTP.
        calls.append(request)
        assert request.method == "GET"
        if request.url.path.endswith("/auth"):
            data = {"token": "SECRET-TOKEN", "expires_in": 600}
        elif mode == "unavailable":
            return httpx.Response(403, json={"code": 403, "response": {"error": "SECRET-EMAIL-AND-TOKEN"}})
        elif request.url.path.endswith("/users"):
            body = json.loads(request.content)
            assert body["show_passwords"] is False
            ids = []
            if "outer_id" in body and mode in {"found", "multiple", "bound", "foreign_owner", "key_mismatch"}:
                assert body["outer_id"] == current.outer_key
                ids = [345, 346] if mode == "multiple" else [345]
            elif "email" in body and mode == "email_only":
                ids = [345]
            data = [{"user_id": value} for value in ids]
        else:
            assert request.url.path.endswith(("/users/345", "/users/346"))
            data = {
                "user_id": int(request.url.path.rsplit("/", 1)[1]),
                "outer_id": "other-key"
                if mode in {"email_only", "wrong_receipt", "key_mismatch"}
                else current.outer_key,
                "password": "SECRET-PASSWORD",
            }
        return httpx.Response(200, json={"code": 200, "response": data})

    def capture(
        conn: object, cursor: object, statement: str, parameters: object, context: object, executemany: bool
    ) -> None:
        statements.append(statement)

    event.listen(migrated_database, "before_cursor_execute", capture)
    try:
        result = asyncio.run(
            diagnose_customer(config, factory=factory, user_id=user_id, lbx_transport=httpx.MockTransport(respond))
        )
    finally:
        event.remove(migrated_database, "before_cursor_execute", capture)
    assert result["diagnosis"] == expected
    if expected == "customer_found_unbound":
        assert result["next_action"] == "open_billing_to_recover_existing_customer"
    if expected == "email_conflict":
        assert result["next_action"] == "correct_email_conflict_then_open_billing"
    if mode != "unavailable":
        assert result["lbx_error"] is None
    assert all(
        not result[key] for key in ("writes_performed", "create_performed", "retry_authorized", "widget_checked")
    )
    assert all(statement.lstrip().split()[0].upper() in {"SELECT", "SET"} for statement in statements)
    assert any("SET TRANSACTION READ ONLY" in statement for statement in statements)
    rendered = json.dumps(result)
    assert all(secret not in rendered for secret in ("SECRET", "synthetic@example.com", current.outer_key))
    if mode in {"historical", "saved_failure"}:
        assert result["create_responses"][0]["http_status"] == 500
        assert result["create_responses"][0]["reason"] == "email_not_unique"


@pytest.mark.parametrize("verified", [False, True])
def test_diagnose_missing_slot_does_not_allocate_or_contact_billing(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], verified: bool
) -> None:
    factory = postgres_session_factory
    seed(factory, verified=verified)
    with factory() as db:
        user_id = db.scalar(select(User.id))

    def forbidden(request: httpx.Request) -> httpx.Response:
        pytest.fail("Missing slot must not allocate identity or contact Billing")

    result = asyncio.run(
        diagnose_customer(
            step1_settings(), factory=factory, user_id=user_id, lbx_transport=httpx.MockTransport(forbidden)
        )
    )
    assert result["diagnosis"] == "not_provisioned"
    with factory() as db:
        assert db.scalar(select(ExternalCreateOperation)) is None


@pytest.mark.parametrize("failure", ["email_not_unique", "unknown"])
def test_create_500_is_retained_without_email_or_retry_and_diagnosed(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], failure: str
) -> None:
    factory = postgres_session_factory
    config = step1_settings(lbx_max_get_attempts=2)
    seed(factory)
    posts = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth"):
            data = {"token": "SECRET-TOKEN", "expires_in": 600}
        elif request.method == "POST":
            posts.append(request)
            message = (
                "Invalid email SECRET-EMAIL. Email must be unique" if failure == "email_not_unique" else "SECRET-BODY"
            )
            return httpx.Response(500, json={"code": 500, "response": {"error": message}})
        else:
            assert request.method == "GET" and request.url.path.endswith("/users")
            data = []
        return httpx.Response(200, json={"code": 200, "response": data})

    async def scenario() -> dict[str, object]:
        async with source_resources(config, lbx_transport=httpx.MockTransport(respond)) as sources:
            for _ in range(2):
                with pytest.raises(BillingRefused):
                    await bootstrap_account(sources, config, factory=factory, token=TOKEN)
        with factory() as db:
            user_id = db.scalar(select(User.id))
        return await diagnose_customer(
            config, factory=factory, user_id=user_id, lbx_transport=httpx.MockTransport(respond)
        )

    result = asyncio.run(scenario())
    assert len(posts) == 2
    assert result["diagnosis"] == ("email_conflict" if failure == "email_not_unique" else "create_outcome_unknown")
    with factory() as db:
        operation = db.scalar(select(ExternalCreateOperation))
        work = db.scalar(select(BillingWorkItem))
        saved = work.payload_document["last_failed_create"]
        assert saved["http_status"] == saved["lbx_code"] == 500
        assert saved["reason"] == ("email_not_unique" if failure == "email_not_unique" else "provider_rejected")
        assert "SECRET" not in json.dumps(work.payload_document)
        assert operation.send_fence is not None and operation.operation_state == "unknown"


def test_failure_evidence_cannot_overwrite_new_fence_or_receipt(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    seed(factory)
    config = step1_settings()
    current = claim_customer_send(factory, config, TOKEN, reserve_customer(factory, config, TOKEN))
    for stale in (replace(current, fence=uuid4()), replace(current, outer_key="other")):
        record_customer_create_failure(factory, stale, http_status=500, lbx_code=500, reason="email_not_unique")
    record_customer_receipt(factory, current, 345)
    record_customer_create_failure(factory, current, http_status=500, lbx_code=500, reason="email_not_unique")
    with factory() as db:
        assert "last_failed_create" not in db.scalar(select(BillingWorkItem)).payload_document


@pytest.mark.parametrize(
    "invalid",
    [
        {"http_status": True},
        {"http_status": 999},
        {"lbx_code": "500"},
        {"recorded_at": "yesterday"},
        {"reason": "SECRET-RAW-ERROR"},
    ],
)
def test_diagnostic_evidence_is_allowlisted(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], invalid: dict[str, object]
) -> None:
    from app.domains.billing.contracts import CREATE_RESPONSE_SCHEMA
    from app.domains.billing.customer_diagnostics import load_customer_diagnostics

    factory = postgres_session_factory
    config = step1_settings()
    seed(factory)
    claim_customer_send(factory, config, TOKEN, reserve_customer(factory, config, TOKEN))
    with factory() as db:
        user_id = db.scalar(select(User.id))
        work = db.scalar(select(BillingWorkItem))
        work.payload_document = {
            "last_failed_create": {
                "schema_version": CREATE_RESPONSE_SCHEMA,
                "http_status": 500,
                "lbx_code": 500,
                "reason": "email_not_unique",
                "recorded_at": "2026-10-26T01:00:00+00:00",
                **invalid,
            }
        }
        db.commit()
    result = load_customer_diagnostics(factory, config, user_id).report
    assert "SECRET" not in json.dumps(result)
    if "reason" in invalid:
        assert result["create_responses"][0]["reason"] == "unknown"
    else:
        assert result["create_responses"] == []


def test_diagnosis_refuses_foreign_contour_without_http(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    config = step1_settings()
    with factory() as db:
        foreign = User(
            id=uuid4(),
            tenant_id="another-tenant",
            region=config.instance_region,
            email="foreign@example.com",
            email_normalized="foreign@example.com",
        )
        db.add(foreign)
        db.commit()
        user_id = foreign.id
    with pytest.raises(BillingRefused, match="billing_customer_user_not_found"):
        asyncio.run(diagnose_customer(config, factory=factory, user_id=user_id))
