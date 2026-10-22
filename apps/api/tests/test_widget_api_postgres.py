"""Fresh proof, authorization and outage isolation over the real PG boundary."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import asyncio
from datetime import timedelta
from threading import Event, Lock
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AuthSession,
    BillingPurchaseScopeHold,
    BillingWorkItem,
    DocumentAcceptance,
    ExternalBillingCustomer,
    ExternalCreateOperation,
    ExternalCreateOperationKind,
    ExternalCreateOperationState,
    ExternalSubscription,
    ExternalSubscriptionCommercialAccessStatus,
    ExternalSubscriptionFinancialAccessStatus,
    ExternalSubscriptionLifecycleStatus,
    PurchaseIntent,
    PurchaseIntentState,
    User,
)
from app.domains.purchases.preparation_contracts import PreparationProof
from app.infrastructure.persistence.external_creates import claim_external_create
from app.infrastructure.preflight import PreflightBudget
from app.infrastructure.queries import widget as widget_queries
from app.integrations.lbx.purchase_preparation import LbxPurchasePreparation
from apps.api.tests.support.purchases import PurchaseHarness
from apps.api.tests.support.purchases import harness as harness
from apps.api.tests.test_purchase_preparation_postgres import Traffic, admitted, edit_recording, resume
from apps.api.tests.test_purchase_preparation_postgres import traffic as traffic
from tools.kernel_manifest_mock.server import MockConfig, Scenario


pytestmark = [pytest.mark.postgres, pytest.mark.usefixtures("mapping_clock")]


def linked(harness: PurchaseHarness) -> str:
    intent_id = admitted(harness)
    response = resume(harness, intent_id)
    assert response.status_code == 202 and response.json()["state"] == "linked", response.text
    return intent_id


def bootstrap(harness: PurchaseHarness, intent_id: str | None = None, token: str | None = None) -> httpx.Response:
    return harness.client.post(
        "/api/billing/widget-bootstrap",
        headers={
            "Authorization": "Bearer " + (token or harness.token),
        },
        json={"product_id": "proposal_ai", "purchase_intent_id": intent_id},
    )


def test_each_explicit_open_repeats_point_proof_but_no_sale_or_create(
    harness: PurchaseHarness,
    traffic: Traffic,
) -> None:
    intent_id = linked(harness)
    posts, kernel = traffic.posts.copy(), list(harness.source_calls)
    traffic.requests.clear()
    harness.server.config = MockConfig(app_env="test", token="offline", scenario=Scenario.UNAVAILABLE)
    # Manage uses original subscription terms, not current catalog or profile.
    harness.profile_path.unlink()
    first, second = bootstrap(harness, intent_id), bootstrap(harness)
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert first.headers["cache-control"] == "no-store"
    assert first.headers["referrer-policy"] == "no-referrer"
    assert first.json()["mode"] == "SIMULATED"
    assert first.json()["credential"].startswith("SIMULATED:")
    assert "." not in first.json()["credential"]
    assert first.json()["credential"] != second.json()["credential"]
    assert first.json()["disableCreateSubscription"] is True
    assert first.json()["disableEditSubscription"] is True
    for suffix in ("/users/1501", "/agreements/1601", "/subscriptions/1701"):
        assert traffic.requests.count(("GET", suffix)) == 2
    assert traffic.posts == {} and posts == {"/users": 1, "/agreements": 1, "/subscriptions": 1}
    assert harness.source_calls == kernel


@pytest.mark.parametrize(
    "history_state",
    [ExternalSubscriptionLifecycleStatus.ENDED, ExternalSubscriptionLifecycleStatus.INACTIVE],
)
def test_widget_selects_current_hold_link_and_rejects_a_nonterminal_competitor(
    harness: PurchaseHarness, traffic: Traffic, history_state: ExternalSubscriptionLifecycleStatus
) -> None:
    intent_id = linked(harness)
    with harness.factory.begin() as db:
        current = db.scalars(
            select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == UUID(intent_id))
        ).one()
        current_id = current.subscription_id
        db.add(
            ExternalSubscription(
                customer_id=current.customer_id,
                user_id=current.user_id,
                product_id=current.product_id,
                external_billing_account_id=current.external_billing_account_id,
                external_subscription_id="historical-subscription",
                external_agreement_id="historical-agreement",
                lifecycle_status=history_state,
                financial_access_status=ExternalSubscriptionFinancialAccessStatus.BLOCKED,
                commercial_access_status=ExternalSubscriptionCommercialAccessStatus.INELIGIBLE,
                last_authoritative_read_at=harness.now - timedelta(days=30),
                projection_valid_until=harness.now - timedelta(days=30),
                # Imported history may have a newer local row timestamp than A2.
                created_at=current.created_at + timedelta(days=1),
            )
        )
    traffic.requests.clear()
    response = bootstrap(harness)
    if history_state == ExternalSubscriptionLifecycleStatus.ENDED:
        assert response.status_code == 200, response.text
        assert {path for method, path in traffic.requests if method == "GET" and path != "/auth"} == {
            "/users/1501",
            "/agreements/1601",
            "/subscriptions/1701",
        }
        assert bootstrap(harness, intent_id).status_code == 200
    else:
        assert response.status_code == 409, response.text
        assert response.json() == {"detail": {"code": "manual_review_required"}}
        assert "credential" not in response.text
        assert traffic.requests == []
    assert traffic.posts == {}
    with harness.factory() as db:
        hold = db.scalars(select(BillingPurchaseScopeHold)).one()
        assert hold.purchase_intent_id == UUID(intent_id)
        assert hold.subscription_id == current_id


@pytest.mark.parametrize("kind", [ExternalCreateOperationKind.AGREEMENT, ExternalCreateOperationKind.SUBSCRIPTION])
def test_unknown_create_for_other_product_does_not_block_proven_widget(
    harness: PurchaseHarness, traffic: Traffic, kind: ExternalCreateOperationKind
) -> None:
    intent_id = linked(harness)
    other_id = uuid4()
    with harness.factory.begin() as db:
        current = db.get(PurchaseIntent, UUID(intent_id))
        assert current is not None
        other = PurchaseIntent(
            purchase_intent_id=other_id,
            user_id=current.user_id,
            customer_id=current.customer_id,
            external_billing_account_id=current.external_billing_account_id,
            product_id="other-product",
            billing_offer_id=current.billing_offer_id,
            mapping_revision_id=current.mapping_revision_id,
            accepted_commercial_fingerprint=current.accepted_commercial_fingerprint,
            client_idempotency_key=uuid4().hex,
            accepted_snapshot_schema_version="v1",
            # Only the other product's persisted operation scope is needed;
            # this fixture is never admitted, advanced or used as Widget proof.
            accepted_snapshot={},
            legal_acceptance_event_id=current.legal_acceptance_event_id,
            state=PurchaseIntentState.AWAITING_EXTERNAL_RESULT,
        )
        db.add(other)
        db.flush()
        db.add(
            BillingPurchaseScopeHold(
                user_id=current.user_id,
                product_id=other.product_id,
                tenant_id="anytoolai",
                region="ru",
                external_billing_account_id=current.external_billing_account_id,
                purchase_intent_id=other.purchase_intent_id,
            )
        )
        operation = ExternalCreateOperation(
            create_operation_id=uuid4(),
            external_billing_account_id=current.external_billing_account_id,
            customer_id=current.customer_id,
            purchase_intent_id=other.purchase_intent_id,
            operation_kind=kind,
            operation_state=ExternalCreateOperationState.UNSENT,
            request_correlation_key=uuid4().hex,
        )
        db.add(operation)
        db.flush()
        # Use the existing local claim mechanics so UNKNOWN retains its
        # mandatory fence, fixed deadline and durable recovery work item.
        # No provider request is made by this fixture.
        claim = claim_external_create(db, operation.create_operation_id, now=harness.now)
        assert claim is not None
        operation.operation_state = ExternalCreateOperationState.UNKNOWN
    posts = traffic.posts.copy()
    response = bootstrap(harness, intent_id)
    assert response.status_code == 200, response.text
    assert traffic.posts == posts
    with harness.factory() as db:
        unresolved = db.scalars(
            select(ExternalCreateOperation).where(
                ExternalCreateOperation.operation_state == ExternalCreateOperationState.UNKNOWN,
            )
        ).one()
        assert unresolved.purchase_intent_id == other_id
        assert unresolved.bound_external_object_id is None
        work_item = db.scalars(
            select(BillingWorkItem).where(
                BillingWorkItem.coalescing_key == f"external-create:{unresolved.create_operation_id}",
            )
        ).one()
        assert work_item.work_state == "pending"
        assert work_item.next_attempt_at == unresolved.unknown_recovery_deadline_at


@pytest.mark.parametrize("binding", ["external_agreement_id", "external_subscription_id"])
def test_conflicting_current_subscription_binding_denies_widget(
    harness: PurchaseHarness, traffic: Traffic, binding: str
) -> None:
    intent_id = linked(harness)
    with harness.factory.begin() as db:
        current = db.scalars(
            select(ExternalSubscription).where(
                ExternalSubscription.purchase_intent_id == UUID(intent_id),
            )
        ).one()
        setattr(current, binding, "9999")
    traffic.requests.clear()
    response = bootstrap(harness, intent_id)
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": {"code": "billing_not_ready"}}
    assert "credential" not in response.text
    assert traffic.requests == []


@pytest.mark.parametrize(
    "record,field,value,code",
    [
        ("user", "outer_id", "different-original-key", "identity_conflict"),
        ("user", "user_id", 9999, "identity_conflict"),
        ("agreement", "user_id", 9999, "identity_conflict"),
        ("agreement", "organization_id", 9999, "identity_conflict"),
        ("subscription", "agreement_id", 9999, "identity_conflict"),
        ("subscription", "total_price", 1, "commercial_terms_conflict"),
        ("subscription", "currency_symbol", "usd", "commercial_terms_conflict"),
        ("subscription", "period_length", 2, "commercial_terms_conflict"),
    ],
)
def test_current_owner_and_effective_material_must_still_match(
    harness: PurchaseHarness,
    traffic: Traffic,
    record: str,
    field: str,
    value: object,
    code: str,
) -> None:
    intent_id = linked(harness)
    edit_recording(harness, record, lambda row: row.update({field: value}))
    response = bootstrap(harness, intent_id)
    assert response.status_code == 409, response.text
    assert response.json() == {"detail": {"code": code}}
    assert "credential" not in response.text
    assert traffic.posts == {"/users": 1, "/agreements": 1, "/subscriptions": 1}


@pytest.mark.parametrize("field,value", [("price", 100.02), ("multiplicator", 1), ("price", None)])
def test_effective_service_override_or_missing_evidence_denies_widget(
    harness: PurchaseHarness,
    traffic: Traffic,
    field: str,
    value: object,
) -> None:
    intent_id = linked(harness)
    edit_recording(harness, "subscription", lambda row: row["services"][0].update({field: value}))
    assert bootstrap(harness, intent_id).status_code == 409


def test_non_owner_selector_and_client_provider_details_are_rejected(
    harness: PurchaseHarness, traffic: Traffic
) -> None:
    intent_id = linked(harness)
    assert bootstrap(harness, intent_id, harness.other_token).status_code in (404, 409)
    assert bootstrap(harness, str(uuid4())).status_code == 404
    assert harness.client.post("/api/billing/widget-bootstrap", json={"product_id": "proposal_ai"}).status_code == 401
    assert (
        harness.client.post(
            "/api/billing/widget-bootstrap",
            headers=harness.headers,
            json={"product_id": "proposal_ai", "ident_type": 6, "ident": "1501"},
        ).status_code
        == 422
    )


@pytest.mark.parametrize("fault", ["email", "customer"])
def test_local_eligibility_is_rechecked_on_every_open(harness: PurchaseHarness, traffic: Traffic, fault: str) -> None:
    intent_id = linked(harness)
    with harness.factory.begin() as db:
        if fault == "email":
            db.get(User, harness.user_id).email_verified_at = None
        else:
            db.scalars(select(ExternalBillingCustomer)).one().provider_customer_id = "9999"
    assert bootstrap(harness, intent_id).status_code in (403, 409)


@pytest.mark.parametrize("fault", ["missing", "hash"])
def test_incomplete_or_conflicting_consent_read_denies_widget_without_rewriting_evidence(
    harness: PurchaseHarness, traffic: Traffic, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    intent_id = linked(harness)
    assert bootstrap(harness, intent_id).status_code == 200
    read_acceptances = widget_queries.document_acceptances
    with harness.factory() as db:
        intent = db.get(PurchaseIntent, UUID(intent_id))
        assert intent is not None
        event_id = intent.legal_acceptance_event_id
        expected = {(row.document_version_id, row.acceptance_text_hash) for row in read_acceptances(db, event_id)}
    assert expected

    def faulty_read(db: Session, selected_event_id: UUID) -> list[DocumentAcceptance]:
        rows = read_acceptances(db, selected_event_id)
        if selected_event_id != event_id:
            return rows
        if fault == "missing":
            return []
        row = rows[0]
        # Read-boundary fault injection only: this transient copy is never
        # attached to the Session. Stored acceptances remain append-only.
        conflicting = DocumentAcceptance(
            id=row.id,
            legal_acceptance_event_id=row.legal_acceptance_event_id,
            tenant_id=row.tenant_id,
            region=row.region,
            user_id=row.user_id,
            document_version_id=row.document_version_id,
            acceptance_kind=row.acceptance_kind,
            acceptance_text_hash="0" * 64,
            created_at=row.created_at,
        )
        return [conflicting, *rows[1:]]

    monkeypatch.setattr(widget_queries, "document_acceptances", faulty_read)
    response = bootstrap(harness, intent_id)
    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "billing_not_ready"}}
    with harness.factory() as db:
        assert {
            (row.document_version_id, row.acceptance_text_hash) for row in read_acceptances(db, event_id)
        } == expected
    assert traffic.posts == {"/users": 1, "/agreements": 1, "/subscriptions": 1}


@pytest.mark.parametrize("kind", list(ExternalCreateOperationKind))
def test_unknown_create_blocks_widget_even_for_a_previously_linked_subscription(
    harness: PurchaseHarness,
    traffic: Traffic,
    kind: ExternalCreateOperationKind,
) -> None:
    intent_id = linked(harness)
    with harness.factory.begin() as db:
        operation = db.scalars(
            select(ExternalCreateOperation).where(
                ExternalCreateOperation.operation_kind == kind,
            )
        ).one()
        operation.operation_state = ExternalCreateOperationState.UNKNOWN
    result = bootstrap(harness, intent_id)
    assert result.status_code == 409
    assert result.json() == {"detail": {"code": "manual_review_required"}}


def test_logout_during_point_proof_discards_bootstrap(
    harness: PurchaseHarness, traffic: Traffic, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = LbxPurchasePreparation.prove

    async def prove(
        self: LbxPurchasePreparation, kind: ExternalCreateOperationKind, object_id: int, budget: PreflightBudget
    ) -> PreparationProof[int]:
        result = await original(self, kind, object_id, budget)
        with harness.factory.begin() as db:
            session = db.scalars(select(AuthSession).where(AuthSession.user_id == harness.user_id)).one()
            session.revoked_at = harness.now
        return result

    intent_id = linked(harness)
    monkeypatch.setattr(LbxPurchasePreparation, "prove", prove)
    assert bootstrap(harness, intent_id).status_code == 403


def test_parallel_opens_during_kernel_outage_are_read_only_and_status_stays_available(
    harness: PurchaseHarness,
    traffic: Traffic,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intent_id = linked(harness)
    harness.server.config = MockConfig(app_env="test", token="offline", scenario=Scenario.UNAVAILABLE)
    both_reading, release, lock = Event(), Event(), Lock()
    active = 0
    original = LbxPurchasePreparation.prove

    async def held_proof(
        self: LbxPurchasePreparation, kind: ExternalCreateOperationKind, object_id: int, budget: PreflightBudget
    ) -> PreparationProof[int]:
        nonlocal active
        with lock:
            active += 1
            if active == 2:
                both_reading.set()
        if not await asyncio.to_thread(release.wait, 5):
            raise AssertionError("human test did not release proof barrier")
        return await original(self, kind, object_id, budget)

    monkeypatch.setattr(LbxPurchasePreparation, "prove", held_proof)
    with ThreadPoolExecutor(max_workers=2) as pool:
        opens = [pool.submit(bootstrap, harness, intent_id) for _ in range(2)]
        try:
            assert both_reading.wait(5)
            status = harness.client.get(f"/api/purchases/{intent_id}", headers=harness.headers)
            assert status.status_code == 200
        finally:
            release.set()
        assert all(item.result().status_code == 200 for item in opens)
    assert traffic.posts == {"/users": 1, "/agreements": 1, "/subscriptions": 1}


def test_lbx_recorded_read_outage_denies_widget_without_hiding_persisted_status(
    harness: PurchaseHarness,
    traffic: Traffic,
) -> None:
    intent_id = linked(harness)
    (harness.profile_path.parent / "recordings" / "user.json").unlink()
    response = bootstrap(harness, intent_id)
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "billing_not_ready"}}
    assert harness.client.get(f"/api/purchases/{intent_id}", headers=harness.headers).status_code == 200
