"""SIMULATED HTTP/PG fault evidence. No real account mutation is enabled."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack
from dataclasses import replace
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

import app.composition.purchases as composition
from app.domains.purchases import router as purchase_http
from app.domains.purchases.preparation import PreparationStep, PurchasePreparation
from app.domains.purchases.contracts import PurchaseAdmissionProof
from app.infrastructure.persistence.external_creates import ExternalCreateClaim
from app.infrastructure.preflight import PreflightBudget
from app.domains.purchases.service import PurchaseApplication
from app.domains.purchases.transactions import release_purchase_scope
from app.infrastructure.persistence.purchase_scopes import PurchaseScopeIdentity, PurchaseScopeReleaseEvidence
from app.integrations.lbx.client import API_PATH
from app.integrations.lbx.preparation import ProofState
from app.integrations.lbx.preparation_profile import PreparationProfile
from app.integrations.lbx.purchase_preparation import LbxPurchasePreparation
from app.integrations.lbx.recorded_preparation import RecordedPreparationTransport
from app.models import (
    BillingProductAccessScope,
    BillingPurchaseScopeHold,
    BillingStateObservation,
    BillingWorkItem,
    ExternalBillingCustomer,
    ExternalBillingCustomerBindingState,
    ExternalCreateOperation,
    ExternalCreateOperationKind,
    ExternalCreateOperationState,
    ExternalSubscription,
    ExternalSubscriptionCommercialAccessStatus,
    ExternalSubscriptionFinancialAccessStatus,
    ExternalSubscriptionLifecycleStatus,
    ManualReviewCase,
    PurchaseIntent,
    PurchaseIntentState,
    PurchaseScopeHoldState,
    PurchaseScopeReleaseKind,
    User,
)
from apps.api.tests.support.purchases import PurchaseHarness, edit_profile, edit_preparation_profile
from apps.api.tests.support.purchases import harness as harness
from tools.kernel_manifest_mock.server import MockConfig, Scenario


pytestmark = [pytest.mark.postgres, pytest.mark.usefixtures("mapping_clock")]


def application(harness: PurchaseHarness) -> PurchaseApplication:
    return harness.client.app.dependency_overrides[purchase_http.application]()


def preparation(harness: PurchaseHarness) -> PurchasePreparation:
    value = application(harness).preparation
    assert value is not None
    return value


def admitted(harness: PurchaseHarness) -> str:
    result = harness.post(harness.payload())
    assert result.status_code == 202, result.text
    return result.json()["purchase_intent_id"]


def resume(harness: PurchaseHarness, intent_id: str) -> httpx.Response:
    return harness.client.post(f"/api/purchases/{intent_id}/continue", headers=harness.headers)


def audited_release(harness: PurchaseHarness) -> None:
    with harness.factory() as db:
        hold = db.scalars(select(BillingPurchaseScopeHold)).one()
        scope = PurchaseScopeIdentity(
            hold.user_id, hold.product_id, hold.tenant_id, hold.region, hold.external_billing_account_id
        )
        epoch = hold.ownership_epoch
    release_purchase_scope(
        harness.factory,
        scope=scope,
        expected_epoch=epoch,
        evidence=PurchaseScopeReleaseEvidence(
            PurchaseScopeReleaseKind.AUDITED_SUPPORT, "SIMULATED:reviewed-release", "operator:test", harness.now
        ),
    )


def edit_recording(harness: PurchaseHarness, name: str, change: Callable[[object], None]) -> None:
    path = harness.profile_path.parent / "recordings" / f"{name}.json"
    body = json.loads(path.read_bytes())
    change(body["response"])
    path.write_text(json.dumps(body))


@dataclass
class Traffic:
    harness: PurchaseHarness
    requests: list[tuple[str, str]] = field(default_factory=list)
    faults: dict[str, str] = field(default_factory=dict)
    point_aliases: dict[str, tuple[str, str]] = field(default_factory=dict)
    subscription_status: int = 201

    @property
    def posts(self) -> Counter[str]:
        return Counter(path for method, path in self.requests if method == "POST" and path != "/auth")

    def transport(
        self, directory: Path, profile: PreparationProfile, *, substitutions: dict[str, str] | None = None
    ) -> httpx.MockTransport:
        base = RecordedPreparationTransport(directory, profile, substitutions=substitutions)

        async def respond(request: httpx.Request) -> httpx.Response:
            suffix = request.url.path.removeprefix(API_PATH)
            self.requests.append((request.method, suffix))
            if request.method == "GET" and suffix in self.point_aliases:
                original_path, identity_field = self.point_aliases[suffix]
                response = await base.handle_async_request(
                    httpx.Request("GET", request.url.copy_with(path=API_PATH + original_path))
                )
                body = response.json()
                body["response"][identity_field] = int(suffix.rsplit("/", 1)[1])
                return httpx.Response(response.status_code, json=body)
            if request.method == "POST" and suffix in ("/users", "/agreements", "/subscriptions"):
                # A separate session can see the already committed fence and
                # due item while transport runs. No transaction/lock spans I/O.
                kind = {"/users": "customer", "/agreements": "agreement", "/subscriptions": "subscription"}[suffix]
                with self.harness.factory() as db:
                    operation = db.scalars(
                        select(ExternalCreateOperation).where(
                            ExternalCreateOperation.operation_kind == ExternalCreateOperationKind(kind)
                        )
                    ).one()
                    assert operation.operation_state in (
                        ExternalCreateOperationState.POSSIBLE_SEND,
                        ExternalCreateOperationState.UNKNOWN,
                        ExternalCreateOperationState.BOUND,
                    )
                    assert operation.send_fencing_token == 1
                    assert operation.unknown_recovery_deadline_at == operation.unknown_since + timedelta(hours=2)
                    item = db.scalars(
                        select(BillingWorkItem).where(
                            BillingWorkItem.coalescing_key == f"external-create:{operation.create_operation_id}"
                        )
                    ).one()
                    assert item.next_attempt_at == operation.unknown_recovery_deadline_at
                    if suffix == "/subscriptions":
                        agreement = db.scalars(
                            select(ExternalCreateOperation).where(
                                ExternalCreateOperation.operation_kind == ExternalCreateOperationKind.AGREEMENT
                            )
                        ).one()
                        assert agreement.operation_state == ExternalCreateOperationState.BOUND
                        assert agreement.bound_external_object_id == "1601"
                fault = self.faults.get(suffix)
                if fault == "timeout":
                    raise httpx.ReadTimeout("SIMULATED lost acknowledgement", request=request)
                if fault is not None:
                    return httpx.Response(int(fault))
            response = await base.handle_async_request(request)
            if request.method == "POST" and suffix == "/subscriptions":
                return httpx.Response(self.subscription_status, content=response.content, headers=response.headers)
            return response

        return httpx.MockTransport(respond)


@pytest.fixture
def traffic(harness: PurchaseHarness, monkeypatch: pytest.MonkeyPatch) -> Traffic:
    value = Traffic(harness)
    monkeypatch.setattr(composition, "RecordedPreparationTransport", value.transport)
    return value


@pytest.mark.parametrize("subscription_status", [200, 201])
@pytest.mark.parametrize("outer_id_case", ["matching", "changed", "null", "absent"])
def test_complete_proof_links_only_an_expired_denying_projection(
    harness: PurchaseHarness, traffic: Traffic, subscription_status: int, outer_id_case: str
) -> None:
    traffic.subscription_status = subscription_status
    intent_id = admitted(harness)

    def change_hint(row: dict) -> None:
        if outer_id_case == "absent":
            row.pop("outer_id")
        elif outer_id_case != "matching":
            row["outer_id"] = None if outer_id_case == "null" else "provider-updated-label"

    edit_recording(harness, "subscription", change_hint)
    with harness.factory() as db:
        original = db.get(PurchaseIntent, UUID(intent_id)).accepted_snapshot
        assert original["review"]["preparation_fingerprint"].startswith("sha256:")
        original_epoch = db.scalars(select(BillingPurchaseScopeHold)).one().ownership_epoch
    response = resume(harness, intent_id)
    assert response.status_code == 202, response.text
    assert response.json()["state"] == "linked"
    assert traffic.posts == {"/users": 1, "/agreements": 1, "/subscriptions": 1}
    assert harness.source_calls == ["kernel"] * 4
    with harness.factory() as db:
        assert db.get(PurchaseIntent, UUID(intent_id)).accepted_snapshot == original
        operations = db.scalars(select(ExternalCreateOperation)).all()
        assert len(operations) == 3
        assert all(op.operation_state == ExternalCreateOperationState.BOUND for op in operations)
        assert all(op.recovery_hint_document["point_proven_at"] for op in operations)
        assert all("server_username" not in json.dumps(op.recovery_hint_document) for op in operations)
        subscription = db.scalars(select(ExternalSubscription)).one()
        assert subscription.external_subscription_id == "1701"
        assert subscription.financial_access_status == ExternalSubscriptionFinancialAccessStatus.BLOCKED
        assert subscription.commercial_access_status == ExternalSubscriptionCommercialAccessStatus.INELIGIBLE
        assert subscription.projection_valid_until <= harness.now
        assert subscription.latest_observation_id is None
        for model in (BillingStateObservation, BillingProductAccessScope):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert all(item.work_state == "completed" for item in db.scalars(select(BillingWorkItem)))
        hold = db.scalars(select(BillingPurchaseScopeHold)).one()
        assert hold.hold_state == PurchaseScopeHoldState.HELD
        assert hold.subscription_id == subscription.subscription_id
        assert hold.ownership_epoch == original_epoch + 1
    count = list(traffic.requests)
    assert resume(harness, intent_id).json() == response.json()
    assert traffic.requests == count


@pytest.mark.parametrize("path", ["/users", "/agreements", "/subscriptions"])
@pytest.mark.parametrize("fault", ["timeout", "500"])
def test_ambiguous_post_recovers_by_get_after_restart_without_reposting(
    harness: PurchaseHarness, traffic: Traffic, path: str, fault: str
) -> None:
    intent_id = admitted(harness)
    traffic.faults[path] = fault
    first = resume(harness, intent_id)
    assert first.status_code == 202, first.text
    assert first.json()["state"] == "awaiting_external_result"
    before = traffic.posts.copy()
    if path == "/subscriptions":
        edit_recording(harness, "subscription", lambda row: row.pop("outer_id"))
    # Every HTTP request composes a fresh application/client. Persisted original
    # commands suffice even with Kernel offline and the current profile removed.
    harness.server.config = MockConfig(app_env="test", token="offline", scenario=Scenario.UNAVAILABLE)
    edit_preparation_profile(
        harness, lambda profile: profile.update(is_offer=False, service_composition="account_default_single")
    )
    harness.profile_path.unlink()
    use_case = preparation(harness)
    calls = len(harness.source_calls)
    harness.client.portal.call(lambda: use_case.advance(harness.user_id, UUID(intent_id), read_only=True))
    assert traffic.posts == before
    assert len(harness.source_calls) == calls
    with harness.factory() as db:
        kind = ExternalCreateOperationKind(
            {"/users": "customer", "/agreements": "agreement", "/subscriptions": "subscription"}[path]
        )
        operation = db.scalars(
            select(ExternalCreateOperation).where(ExternalCreateOperation.operation_kind == kind)
        ).one()
        assert operation.operation_state == ExternalCreateOperationState.BOUND
        assert operation.send_fencing_token == 1
        assert operation.recovery_hint_document["profile"]["is_offer"] is True
        assert operation.recovery_hint_document["profile"]["service_composition"] == "explicit_single"


@pytest.mark.parametrize("count", [0, 2])
@pytest.mark.parametrize("name", ["users", "agreements", "subscriptions"])
def test_zero_or_many_discovery_never_reposts_and_retains_scope(
    harness: PurchaseHarness, traffic: Traffic, count: int, name: str
) -> None:
    intent_id = admitted(harness)
    path = "/" + name
    traffic.faults[path] = "timeout"
    assert resume(harness, intent_id).status_code == 202

    def candidates(rows: list[dict]) -> None:
        if count == 0:
            rows.clear()
        else:
            field = {"users": "user_id", "agreements": "agreement_id", "subscriptions": "subscription_id"}[name]
            original_id = rows[0][field]
            rows.append({**rows[0], field: original_id + 1})
            # Both list candidates need readable point evidence with matching
            # original correlation/ownership to establish actual ambiguity.
            traffic.point_aliases[f"{path}/{original_id + 1}"] = (f"{path}/{original_id}", field)

    edit_recording(harness, name, candidates)
    before = traffic.posts.copy()
    for _ in range(2):
        response = resume(harness, intent_id)
        assert response.status_code == 202, response.text
    assert traffic.posts == before
    with harness.factory() as db:
        intent = db.get(PurchaseIntent, UUID(intent_id))
        assert intent.state == (
            PurchaseIntentState.AWAITING_EXTERNAL_RESULT if count == 0 else PurchaseIntentState.MANUAL_REVIEW
        )
        assert db.scalars(select(BillingPurchaseScopeHold)).one().hold_state == PurchaseScopeHoldState.HELD
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == (0 if count == 0 else 1)
    assert harness.post(harness.payload(), key="new-key").status_code == 409


def test_crash_after_claim_before_packet_has_durable_deadline_and_requires_reads(
    harness: PurchaseHarness, traffic: Traffic
) -> None:
    intent_id = admitted(harness)
    use_case = preparation(harness)
    step = use_case._next(harness.user_id, UUID(intent_id), read_only=False)
    assert step is not None
    proof = harness.client.portal.call(use_case.fresh_compare, step.accepted.review)
    assert use_case._claim(harness.user_id, UUID(intent_id), step, proof) is not None
    edit_recording(harness, "users", lambda rows: rows.clear())
    assert traffic.posts == {}
    response = resume(harness, intent_id)
    assert response.status_code == 202 and response.json()["state"] == "awaiting_external_result"
    assert traffic.posts == {}
    harness.now += timedelta(hours=2)
    use_case = preparation(harness)
    assert use_case.escalate_overdue(harness.user_id, UUID(intent_id), principal="operator:test") == 1
    assert use_case.escalate_overdue(harness.user_id, UUID(intent_id), principal="operator:test") == 0
    inspected = harness.client.portal.call(use_case.inspect, harness.user_id, UUID(intent_id))
    assert inspected is not None and inspected.state == ProofState.UNRESOLVED
    with harness.factory() as db:
        assert db.scalars(select(BillingWorkItem)).one().work_state == "completed"
        assert db.scalars(select(ManualReviewCase)).one().evidence_document["principal"] == "operator:test"
        assert db.scalars(select(BillingPurchaseScopeHold)).one().hold_state == PurchaseScopeHoldState.HELD
        assert (
            db.scalars(select(ExternalBillingCustomer)).one().binding_state
            == ExternalBillingCustomerBindingState.UNBOUND
        )


def test_concurrent_continuations_claim_each_create_once(harness: PurchaseHarness, traffic: Traffic) -> None:
    intent_id = admitted(harness)
    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = list(executor.map(lambda _: resume(harness, intent_id), range(8)))
    assert all(response.status_code in (202, 503) for response in responses)
    assert resume(harness, intent_id).status_code == 202
    assert all(count == 1 for count in traffic.posts.values())
    with harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(ExternalSubscription)) == 1


@pytest.mark.parametrize(
    "kind,name,missing",
    [
        (ExternalCreateOperationKind.CUSTOMER, "user", "outer_id"),
        (ExternalCreateOperationKind.AGREEMENT, "agreement", "is_offer"),
        (ExternalCreateOperationKind.SUBSCRIPTION, "subscription", "total_price"),
    ],
)
def test_incomplete_competing_recovery_does_not_fence_successful_create(
    harness: PurchaseHarness,
    traffic: Traffic,
    monkeypatch: pytest.MonkeyPatch,
    kind: ExternalCreateOperationKind,
    name: str,
    missing: str,
) -> None:
    intent_id = UUID(admitted(harness))
    use_case = preparation(harness)
    original_create = LbxPurchasePreparation.create
    path = harness.profile_path.parent / "recordings" / f"{name}.json"
    original_recording = path.read_bytes()

    async def race() -> None:
        started, finish = asyncio.Event(), asyncio.Event()

        async def delayed_create(
            self: LbxPurchasePreparation, selected: ExternalCreateOperationKind, budget: PreflightBudget
        ) -> int:
            result = await original_create(self, selected, budget)
            if selected == kind:
                started.set()
                await finish.wait()
            return result

        monkeypatch.setattr(LbxPurchasePreparation, "create", delayed_create)
        first = asyncio.create_task(use_case.advance(harness.user_id, intent_id))
        try:
            async with asyncio.timeout(10):
                await started.wait()
                with harness.factory() as db:
                    operation = db.scalars(
                        select(ExternalCreateOperation).where(ExternalCreateOperation.operation_kind == kind)
                    ).one()
                    original_fence = (operation.send_fencing_token, operation.scope_ownership_epoch)
                edit_recording(harness, name, lambda row: row.pop(missing))
                # Several continuations observe incomplete GETs while the
                # original POST is still waiting for its acknowledgement.
                for _ in range(2):
                    await use_case.advance(harness.user_id, intent_id, read_only=True)
                with harness.factory() as db:
                    operation = db.scalars(
                        select(ExternalCreateOperation).where(ExternalCreateOperation.operation_kind == kind)
                    ).one()
                    assert operation.operation_state == ExternalCreateOperationState.UNKNOWN
                    assert (operation.send_fencing_token, operation.scope_ownership_epoch) == original_fence
                    assert db.get(PurchaseIntent, intent_id).state == PurchaseIntentState.AWAITING_EXTERNAL_RESULT
                    assert db.scalars(select(BillingPurchaseScopeHold)).one().hold_state == PurchaseScopeHoldState.HELD
                    assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0
        finally:
            path.write_bytes(original_recording)
            finish.set()
            await first

    harness.client.portal.call(race)
    assert application(harness).status(harness.user_id, intent_id).state == "linked"
    assert traffic.posts == {"/users": 1, "/agreements": 1, "/subscriptions": 1}
    with harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(ExternalSubscription)) == 1
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0


@pytest.mark.parametrize("missing", [True, False])
def test_incomplete_customer_point_read_remains_recoverable_without_identity_conflict(
    harness: PurchaseHarness, traffic: Traffic, missing: bool
) -> None:
    intent_id = admitted(harness)
    path = harness.profile_path.parent / "recordings/user.json"
    original = path.read_bytes()
    edit_recording(harness, "user", lambda row: row.pop("outer_id") if missing else row.update(outer_id=None))
    for _ in range(2):
        response = resume(harness, intent_id)
        assert response.status_code == 202, response.text
        assert response.json()["state"] == "awaiting_external_result"
    assert traffic.posts == {"/users": 1}
    with harness.factory() as db:
        assert (
            db.scalars(select(ExternalBillingCustomer)).one().binding_state
            == ExternalBillingCustomerBindingState.UNBOUND
        )
        assert db.scalars(select(ExternalCreateOperation)).one().operation_state == ExternalCreateOperationState.UNKNOWN
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0
    widget = harness.client.post(
        "/api/billing/widget-bootstrap",
        headers=harness.headers,
        json={"product_id": "proposal_ai", "purchase_intent_id": intent_id},
    )
    assert widget.status_code == 409, widget.text
    assert traffic.posts == {"/users": 1}
    path.write_bytes(original)
    assert resume(harness, intent_id).json()["state"] == "linked"
    assert traffic.posts == {"/users": 1, "/agreements": 1, "/subscriptions": 1}


def test_same_bound_result_after_link_epoch_advance_is_harmless(
    harness: PurchaseHarness, traffic: Traffic, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent_id = admitted(harness)
    original_bind = PurchasePreparation._bind
    results: list[tuple[PreparationStep, int]] = []

    def remember_result(
        self: PurchasePreparation, user_id: UUID, purchase_id: UUID, step: PreparationStep, object_id: int
    ) -> bool:
        results.append((step, object_id))
        return original_bind(self, user_id, purchase_id, step, object_id)

    monkeypatch.setattr(PurchasePreparation, "_bind", remember_result)
    response = resume(harness, intent_id)
    assert response.status_code == 202, response.text
    assert response.json()["state"] == "linked"
    assert len(results) == 3
    use_case = preparation(harness)
    for step, object_id in results:
        assert not original_bind(use_case, harness.user_id, UUID(intent_id), step, object_id)
    with harness.factory() as db:
        hold = db.scalars(select(BillingPurchaseScopeHold)).one()
        assert hold.ownership_epoch == results[-1][0].hold_epoch + 1
        assert db.get(PurchaseIntent, UUID(intent_id)).state == PurchaseIntentState.LINKED
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0
        assert db.scalar(select(func.count()).select_from(ExternalSubscription)) == 1
    assert traffic.posts == {"/users": 1, "/agreements": 1, "/subscriptions": 1}


@pytest.mark.parametrize("failure", ["terms", "date", "ineligible"])
def test_unsent_drift_date_or_ineligibility_cannot_send(
    harness: PurchaseHarness, traffic: Traffic, failure: str
) -> None:
    intent_id = admitted(harness)
    if failure == "date":
        harness.now += timedelta(days=1)
    elif failure == "terms":
        edit_profile(harness, lambda value: value["inputs"]["policy"].update(renewal_terms="SIMULATED changed"))
    else:
        with harness.factory.begin() as db:
            db.get(User, harness.user_id).email_verified_at = None
    response = resume(harness, intent_id)
    assert response.status_code in (403, 409, 503), response.text
    assert traffic.posts == {}
    with harness.factory() as db:
        for operation in db.scalars(select(ExternalCreateOperation)):
            assert operation.operation_state == ExternalCreateOperationState.UNSENT
            assert operation.unknown_since is None
        assert db.scalar(select(func.count()).select_from(BillingWorkItem)) == 0


@pytest.mark.parametrize("kind", list(ExternalCreateOperationKind))
@pytest.mark.parametrize("saved_unsent", [False, True])
@pytest.mark.parametrize("field,value", [("is_offer", False), ("service_composition", "account_default_single")])
def test_preparation_pin_blocks_changed_config_before_each_unsent_create(
    harness: PurchaseHarness,
    traffic: Traffic,
    monkeypatch: pytest.MonkeyPatch,
    kind: ExternalCreateOperationKind,
    saved_unsent: bool,
    field: str,
    value: object,
) -> None:
    intent_id = UUID(admitted(harness))
    use_case = preparation(harness)
    original_bind = PurchasePreparation._bind
    previous = {
        ExternalCreateOperationKind.AGREEMENT: ExternalCreateOperationKind.CUSTOMER,
        ExternalCreateOperationKind.SUBSCRIPTION: ExternalCreateOperationKind.AGREEMENT,
    }.get(kind)
    if previous is not None:

        def stop_after_previous(
            self: PurchasePreparation, user_id: UUID, purchase_id: UUID, step: PreparationStep, object_id: int
        ) -> bool:
            bound = original_bind(self, user_id, purchase_id, step, object_id)
            return bound and step.kind != previous

        with monkeypatch.context() as patch:
            patch.setattr(PurchasePreparation, "_bind", stop_after_previous)
            assert resume(harness, str(intent_id)).status_code == 202
    if saved_unsent:
        step = use_case._next(harness.user_id, intent_id, read_only=False)
        assert step is not None and step.kind == kind and step.state == ExternalCreateOperationState.UNSENT
    before = traffic.posts.copy()
    with harness.factory() as db:
        accepted = db.get(PurchaseIntent, intent_id).accepted_snapshot
    edit_preparation_profile(harness, lambda profile: profile.update({field: value}))
    response = resume(harness, str(intent_id))
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "commercial_terms_conflict"
    assert traffic.posts == before
    with harness.factory() as db:
        assert db.get(PurchaseIntent, intent_id).accepted_snapshot == accepted
        for operation in db.scalars(select(ExternalCreateOperation)):
            if operation.operation_kind == kind:
                assert operation.operation_state == ExternalCreateOperationState.UNSENT
                assert operation.send_fencing_token == 0


@pytest.mark.parametrize(
    "name,field,value",
    [
        ("user", "outer_id", "wrong-owner"),
        ("agreement", "organization_id", 999),
        ("subscription", "total_price", 999),
        ("subscription", "currency_symbol", "usd"),
    ],
)
def test_receipt_without_complete_matching_point_proof_blocks_link(
    harness: PurchaseHarness, traffic: Traffic, name: str, field: str, value: object
) -> None:
    intent_id = admitted(harness)
    edit_recording(harness, name, lambda row: row.update({field: value}))
    response = resume(harness, intent_id)
    assert response.status_code == 202, response.text
    assert response.json()["state"] == "manual_review"
    with harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(ExternalSubscription)) == 0
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 1
        assert db.scalars(select(BillingPurchaseScopeHold)).one().hold_state == PurchaseScopeHoldState.HELD
        customer = db.scalars(select(ExternalBillingCustomer)).one()
        assert customer.binding_state == (
            ExternalBillingCustomerBindingState.IDENTITY_CONFLICT
            if name == "user"
            else ExternalBillingCustomerBindingState.BOUND
        )
    assert traffic.posts["/subscriptions"] == (1 if name == "subscription" else 0)
    before = traffic.posts.copy()
    assert resume(harness, intent_id).json()["state"] == "manual_review"
    assert traffic.posts == before


def test_existing_customer_prior_selected_subscription_blocks_new_subscription(
    harness: PurchaseHarness, traffic: Traffic
) -> None:
    intent_id = admitted(harness)
    with harness.factory.begin() as db:
        customer = db.scalars(select(ExternalBillingCustomer)).one()
        customer.provider_customer_id = "1501"
        customer.binding_state = ExternalBillingCustomerBindingState.BOUND
    response = resume(harness, intent_id)
    assert response.status_code == 202, response.text
    assert response.json()["state"] == "manual_review"
    assert traffic.posts == {"/agreements": 1}
    assert ("GET", "/subscriptions") in traffic.requests


@pytest.mark.parametrize("complete_empty", [True, False])
def test_existing_customer_b12_requires_a_complete_trustworthy_customer_list(
    harness: PurchaseHarness, traffic: Traffic, complete_empty: bool
) -> None:
    intent_id = admitted(harness)
    with harness.factory.begin() as db:
        customer = db.scalars(select(ExternalBillingCustomer)).one()
        customer.provider_customer_id = "1501"
        customer.binding_state = ExternalBillingCustomerBindingState.BOUND
    if complete_empty:
        edit_recording(harness, "subscriptions", lambda rows: rows.clear())
    else:
        edit_recording(harness, "subscriptions", lambda rows: rows[0].pop("agreement_id"))
    response = resume(harness, intent_id)
    assert response.status_code == (202 if complete_empty else 503), response.text
    assert traffic.posts["/users"] == 0
    assert traffic.posts["/subscriptions"] == (1 if complete_empty else 0)
    with harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(ExternalSubscription)) == (1 if complete_empty else 0)


def test_owned_status_and_product_resume_are_db_only_during_outage(harness: PurchaseHarness, traffic: Traffic) -> None:
    intent_id = admitted(harness)
    traffic.faults["/users"] = "timeout"
    assert resume(harness, intent_id).status_code == 202
    harness.profile_path.unlink()
    calls = list(traffic.requests)
    for path in (f"/api/purchases/{intent_id}", "/api/billing/products/proposal_ai/status"):
        response = harness.client.get(path, headers=harness.headers)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["purchase_intent_id"] == intent_id
    assert traffic.requests == calls
    other = {"Authorization": "Bearer " + harness.other_token}
    assert harness.client.post(f"/api/purchases/{intent_id}/continue", headers=other).status_code == 404
    assert harness.client.get(f"/api/purchases/{intent_id}", headers=other).status_code == 404
    assert traffic.requests == calls


def test_released_attempt_is_history_and_new_hold_is_current(harness: PurchaseHarness, traffic: Traffic) -> None:
    old_id = admitted(harness)
    old = application(harness).status(harness.user_id, UUID(old_id))
    audited_release(harness)
    response = harness.client.get("/api/billing/products/proposal_ai/status", headers=harness.headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"state": "not_ready", "purchase_intent_id": None}
    assert application(harness).status(harness.user_id, UUID(old_id)) == old
    assert (
        harness.client.get(
            f"/api/purchases/{old_id}", headers={"Authorization": "Bearer " + harness.other_token}
        ).status_code
        == 404
    )
    new = harness.post(harness.payload(), key="after-release")
    assert new.status_code == 202, new.text
    new_id = new.json()["purchase_intent_id"]
    assert new_id != old_id
    response = harness.client.get("/api/billing/products/proposal_ai/status", headers=harness.headers)
    assert response.json() == {"state": "preparing", "purchase_intent_id": new_id}
    assert application(harness).status(harness.user_id, UUID(old_id)) == old
    assert traffic.posts == {}


@pytest.mark.parametrize("ended", [False, True])
def test_without_hold_only_nonterminal_subscription_offers_manage(
    harness: PurchaseHarness, traffic: Traffic, ended: bool
) -> None:
    intent_id = admitted(harness)
    assert resume(harness, intent_id).json()["state"] == "linked"
    if ended:
        with harness.factory.begin() as db:
            db.scalars(select(ExternalSubscription)).one().lifecycle_status = ExternalSubscriptionLifecycleStatus.ENDED
    audited_release(harness)
    before = list(traffic.requests)
    response = harness.client.get("/api/billing/products/proposal_ai/status", headers=harness.headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"state": "not_ready" if ended else "manage", "purchase_intent_id": None}
    assert traffic.requests == before


def test_lost_bind_commit_acknowledgement_never_sends_again(
    harness: PurchaseHarness, traffic: Traffic, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent_id = admitted(harness)
    original_bind = PurchasePreparation._bind
    raised = False

    def lost_ack(
        self: PurchasePreparation, user_id: UUID, purchase_id: UUID, step: PreparationStep, object_id: int
    ) -> bool:
        nonlocal raised
        bound = original_bind(self, user_id, purchase_id, step, object_id)
        if not raised:
            raised = True
            raise OperationalError("SIMULATED commit acknowledgement lost", None, Exception("SIMULATED"))
        return bound

    monkeypatch.setattr(PurchasePreparation, "_bind", lost_ack)
    assert resume(harness, intent_id).status_code == 503
    assert resume(harness, intent_id).status_code == 202
    assert traffic.posts == {"/users": 1, "/agreements": 1, "/subscriptions": 1}


def test_midnight_after_source_proof_before_claim_cannot_send(
    harness: PurchaseHarness, traffic: Traffic, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent_id = admitted(harness)
    original = LbxPurchasePreparation.before_send

    async def midnight(
        self: LbxPurchasePreparation, kind: ExternalCreateOperationKind, budget: PreflightBudget
    ) -> None:
        await original(self, kind, budget)
        harness.now += timedelta(days=1)

    monkeypatch.setattr(LbxPurchasePreparation, "before_send", midnight)
    response = resume(harness, intent_id)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "purchase_effective_date_changed"
    assert traffic.posts == {}
    with harness.factory() as db:
        operation = db.scalars(select(ExternalCreateOperation)).one()
        assert operation.operation_state == ExternalCreateOperationState.UNSENT
        assert operation.unknown_since is None


def test_lost_claim_commit_acknowledgement_does_not_authorize_post(
    harness: PurchaseHarness, traffic: Traffic, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent_id = admitted(harness)
    original = PurchasePreparation._claim

    def lost_ack(
        self: PurchasePreparation,
        user_id: UUID,
        purchase_id: UUID,
        step: PreparationStep,
        proof: PurchaseAdmissionProof,
    ) -> ExternalCreateClaim | None:
        original(self, user_id, purchase_id, step, proof)
        raise OperationalError("SIMULATED claim acknowledgement lost", None, Exception("SIMULATED"))

    monkeypatch.setattr(PurchasePreparation, "_claim", lost_ack)
    assert resume(harness, intent_id).status_code == 503
    assert traffic.posts == {}
    edit_recording(harness, "users", lambda rows: rows.clear())
    assert resume(harness, intent_id).json()["state"] == "awaiting_external_result"
    assert traffic.posts == {}
    with harness.factory() as db:
        assert db.scalars(select(BillingWorkItem)).one().work_state == "pending"


def test_late_proof_cannot_bind_after_audited_release_and_new_owner(harness: PurchaseHarness, traffic: Traffic) -> None:
    intent_id = admitted(harness)
    use_case = preparation(harness)
    step = use_case._next(harness.user_id, UUID(intent_id), read_only=False)
    assert step is not None
    proof = harness.client.portal.call(use_case.fresh_compare, step.accepted.review)
    claim = use_case._claim(harness.user_id, UUID(intent_id), step, proof)
    assert claim is not None
    audited_release(harness)
    response = harness.post(harness.payload(), key="replacement-owner")
    assert response.status_code == 202, response.text
    new_id = UUID(response.json()["purchase_intent_id"])
    assert not use_case._bind(harness.user_id, UUID(intent_id), replace(step, claim=claim), 1501)
    with harness.factory() as db:
        customer = db.scalars(select(ExternalBillingCustomer)).one()
        assert customer.provider_customer_id is None
        assert customer.binding_state == ExternalBillingCustomerBindingState.UNBOUND
        assert db.scalars(select(ManualReviewCase)).one().reason_code == "late_create_fence_conflict"
        assert db.scalars(select(BillingPurchaseScopeHold)).one().purchase_intent_id == new_id
        assert db.get(PurchaseIntent, new_id).state == PurchaseIntentState.CREATED
    assert traffic.posts == {}


def test_recovery_uses_separate_capacity_from_saturated_new_sale_preflight(
    harness: PurchaseHarness, traffic: Traffic
) -> None:
    intent_id = admitted(harness)
    traffic.faults["/users"] = "timeout"
    assert resume(harness, intent_id).status_code == 202
    use_case = preparation(harness)
    owner = harness.client.app.state.sources.preflight
    before = len(harness.source_calls)

    async def recover_while_full() -> None:
        async with AsyncExitStack() as stack:
            for _ in range(owner.policy.max_active):
                await stack.enter_async_context(owner.operation())
            await use_case.advance(harness.user_id, UUID(intent_id), read_only=True)

    harness.client.portal.call(recover_while_full)
    assert traffic.posts == {"/users": 1}
    assert len(harness.source_calls) == before
    with harness.factory() as db:
        assert db.scalars(select(ExternalCreateOperation)).one().operation_state == ExternalCreateOperationState.BOUND


def test_authentication_refusal_before_claim_has_no_send_clock(harness: PurchaseHarness, traffic: Traffic) -> None:
    intent_id = admitted(harness)
    edit_recording(harness, "auth", lambda row: row.update(expires_in=0))
    response = resume(harness, intent_id)
    assert response.status_code == 503, response.text
    assert traffic.posts == {}
    with harness.factory() as db:
        operation = db.scalars(select(ExternalCreateOperation)).one()
        assert operation.operation_state == ExternalCreateOperationState.UNSENT
        assert operation.unknown_since is None
