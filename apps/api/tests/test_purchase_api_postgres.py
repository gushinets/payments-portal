"""Step 2 evidence is SIMULATED; no live LBX requests or paid grants."""

from __future__ import annotations

import json
from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.infrastructure.persistence.purchase_scopes import PurchaseScopeIdentity, PurchaseScopeReservation
from app.models import (
    AcceptanceKind,
    BillingPurchaseScopeHold,
    DocumentAcceptance,
    DocumentVersion,
    ExternalBillingCustomer,
    ExternalCreateOperation,
    LegalAcceptanceEvent,
    PurchaseIntent,
    User,
)
from apps.api.tests.support.purchases import PurchaseHarness, assert_no_purchase, edit_profile
from apps.api.tests.support.purchases import harness as harness
from tools.kernel_manifest_mock.server import MockConfig, Scenario


pytestmark = [pytest.mark.postgres, pytest.mark.usefixtures("mapping_clock")]


def test_authenticated_review_is_db_only_exact_and_private(harness: PurchaseHarness) -> None:
    response = harness.client.get("/api/purchases/review/proposal_ai")
    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "missing_session"}}
    assert response.headers["cache-control"] == "no-store"
    review = harness.review()
    assert review == harness.review()
    assert harness.source_calls == []
    assert review["availability"] == "SIMULATED_PREVIEW"
    assert review["initial_amount"] == "214.08"
    assert review["offer"]["money"]["recurring_amount"] == "200.02"
    assert review["offer"]["allowance"]["quantity"] == "25"
    assert review["recurring_required"] is False
    assert {doc["doc_type"] for doc in review["documents"]} == {"privacy", "pd_consent", "offer"}
    encoded = json.dumps(review)
    for private in ("organization_id", "external_billing_account_id", "selected_evidence", "tariff_id", "publisher"):
        assert private not in encoded
    assert_no_purchase(harness)


def test_new_purchase_commits_one_exact_commercial_event_and_hold(harness: PurchaseHarness) -> None:
    review = harness.review()
    response = harness.post(harness.payload())
    assert response.status_code == 202, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["state"] == "created" and body["next_action"] == "wait"
    assert body["continue_available"] is False
    assert body["accepted_terms"] == review
    assert harness.source_calls == ["kernel"]  # genuine loopback HTTP to the existing mock
    with harness.factory() as db:
        intent = db.get(PurchaseIntent, UUID(body["purchase_intent_id"]))
        assert intent is not None
        assert intent.accepted_snapshot_schema_version == "v1"
        snapshot = intent.accepted_snapshot
        assert snapshot["review"]["seller"]["organization_id"] == 21
        assert snapshot["review"]["mapping"]["material"]["technical"]["allowance"] == 25
        assert snapshot["review"]["mapping"]["material"]["terms"]["quantity"]["selected"] == "2"
        assert snapshot["admission"]["mapping"]["evidence_mode"] == "SIMULATED"
        assert "deadline" not in snapshot["admission"]
        event = db.get(LegalAcceptanceEvent, intent.legal_acceptance_event_id)
        assert event is not None and event.accepted_commercial_fingerprint == review["fingerprint"]
        documents = db.scalars(
            select(DocumentAcceptance).where(DocumentAcceptance.legal_acceptance_event_id == event.id)
        ).all()
        assert len(documents) == len(review["documents"])
        assert {str(doc.document_version_id) for doc in documents} == {
            doc["document_version_id"] for doc in review["documents"]
        }
        for model in (PurchaseIntent, BillingPurchaseScopeHold, ExternalBillingCustomer):
            assert db.scalar(select(func.count()).select_from(model)) == 1
        assert db.scalar(select(func.count()).select_from(ExternalCreateOperation)) == 0


def test_replay_and_status_preserve_accepted_truth_without_profile_or_live_sources(harness: PurchaseHarness) -> None:
    payload = harness.payload()
    first = harness.post(payload)
    assert first.status_code == 202, first.text
    harness.server.config = MockConfig(app_env="test", token="offline", scenario=Scenario.UNAVAILABLE)
    harness.profile_path.unlink()
    payload["documents"].reverse()  # canonical meaning is independent of selection order
    for _ in range(2):
        replay = harness.post(payload)
        assert replay.status_code == 202, replay.text
        assert replay.json() == first.json()
    intent_id = first.json()["purchase_intent_id"]
    status = harness.client.get("/api/purchases/" + intent_id, headers=harness.headers)
    assert status.status_code == 200 and status.json() == first.json()
    occupied = harness.post(payload, "different-key")
    assert occupied.status_code == 409 and occupied.json()["detail"]["code"] == "purchase_scope_occupied"
    assert harness.source_calls == ["kernel"]
    with harness.factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(LegalAcceptanceEvent)
                .where(LegalAcceptanceEvent.external_billing_account_id.is_not(None))
            )
            == 1
        )


@pytest.mark.parametrize("field", ["expected_fingerprint", "revision_id", "commercial_confirmation", "documents"])
def test_changed_replay_meaning_conflicts_before_sources(harness: PurchaseHarness, field: str) -> None:
    payload = harness.payload()
    assert harness.post(payload).status_code == 202
    payload[field] = {
        "expected_fingerprint": "sha256:" + "0" * 64,
        "revision_id": str(uuid4()),
        "commercial_confirmation": False,
        "documents": payload["documents"][:-1],
    }[field]
    response = harness.post(payload)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "idempotency_conflict"
    assert harness.source_calls == ["kernel"]


@pytest.mark.parametrize("fault", ["no_confirmation", "no_document", "wrong_hash", "recurring", "account", "no_key"])
def test_registration_acceptance_does_not_replace_purchase_consent(harness: PurchaseHarness, fault: str) -> None:
    payload = harness.payload()
    if fault == "no_confirmation":
        payload["commercial_confirmation"] = False
    elif fault == "no_document":
        payload["documents"].pop()
    elif fault == "wrong_hash":
        payload["documents"][0]["acceptance_text_hash"] = "0" * 64
    elif fault == "recurring":
        payload["recurring_confirmation"] = True
    elif fault == "account":
        payload["external_billing_account_id"] = "browser-account"
    response = (
        harness.client.post("/api/purchases", headers=harness.headers, json=payload)
        if fault == "no_key"
        else harness.post(payload)
    )
    assert response.status_code == 422
    assert harness.source_calls == []
    assert_no_purchase(harness)


def test_non_owner_status_is_404_and_existing_status_survives_eligibility_change(harness: PurchaseHarness) -> None:
    first = harness.post(harness.payload())
    assert first.status_code == 202, first.text
    path = "/api/purchases/" + first.json()["purchase_intent_id"]
    response = harness.client.get(path, headers={"Authorization": "Bearer " + harness.other_token})
    assert response.status_code == 404
    with harness.factory.begin() as db:
        user = db.get(User, harness.user_id)
        assert user is not None
        user.email_verified_at = None
    # Existing owned intents remain readable/replayable; eligibility is new-only.
    assert harness.client.get(path, headers=harness.headers).status_code == 200


def test_unverified_user_cannot_start_new_purchase(harness: PurchaseHarness) -> None:
    payload = harness.payload()
    with harness.factory.begin() as db:
        user = db.get(User, harness.user_id)
        assert user is not None
        user.email_verified_at = None
    assert harness.post(payload).status_code == 403
    assert harness.source_calls == []
    assert_no_purchase(harness)


def test_recurring_profile_requires_exact_recurring_document_and_confirmation(harness: PurchaseHarness) -> None:
    with harness.factory.begin() as db:
        offer = db.scalar(select(DocumentVersion).where(DocumentVersion.doc_type == "offer"))
        assert offer is not None
        db.add(
            DocumentVersion(
                id=uuid4(),
                tenant_id="anytoolai",
                region="ru",
                legal_entity_id=offer.legal_entity_id,
                doc_type="recurring_consent",
                version="SIMULATED-v1",
                title="SIMULATED recurring consent",
                url_path="/ru/simulated-recurring-fixture",
                content_hash="sha256:" + "1" * 64,
                published_at=harness.now,
                effective_from=harness.now,
                is_active=True,
                requires_acceptance=True,
            )
        )
    edit_profile(harness, lambda profile: profile.update(recurring_required=True))
    payload = harness.payload()
    assert payload["recurring_confirmation"] is True
    payload["recurring_confirmation"] = False
    assert harness.post(payload).status_code == 422
    assert_no_purchase(harness)
    payload["recurring_confirmation"] = True
    response = harness.post(payload)
    assert response.status_code == 202, response.text
    with harness.factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(DocumentAcceptance)
                .where(DocumentAcceptance.acceptance_kind == AcceptanceKind.RECURRING_CONSENT)
            )
            == 1
        )


def test_lost_commit_ack_is_resolved_by_original_key_without_second_admission(
    harness: PurchaseHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.exc import OperationalError
    from app.domains.purchases import service

    original = service.reserve_purchase_scope

    def reserve(
        factory: sessionmaker[Session],
        *,
        scope: PurchaseScopeIdentity,
        client_idempotency_key: str,
        create_intent: Callable[[Session], PurchaseIntent],
        replay_matches: Callable[[PurchaseIntent], bool],
    ) -> PurchaseScopeReservation:
        result = original(
            factory,
            scope=scope,
            client_idempotency_key=client_idempotency_key,
            create_intent=create_intent,
            replay_matches=replay_matches,
        )
        if not result.replay and not result.occupied:
            raise OperationalError("SIMULATED lost COMMIT acknowledgement", {}, RuntimeError("connection lost"))
        return result

    monkeypatch.setattr(service, "reserve_purchase_scope", reserve)
    response = harness.post(harness.payload())
    assert response.status_code == 202, response.text
    assert harness.source_calls == ["kernel"]
    with harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(PurchaseIntent)) == 1
