"""Fresh purchase source and transaction race scenarios; all external evidence is SIMULATED."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.domains.catalog.contracts import CapabilityManifest
from app.domains.purchases.contracts import PurchaseAdmissionProof, PurchaseRequest, PurchaseReview
from app.domains.purchases.service import PurchaseApplication
from app.infrastructure.preflight import PreflightBudget
from app.models import LegalAcceptanceEvent, PurchaseIntent
from apps.api.tests.support.purchases import PurchaseHarness, assert_no_purchase, edit_profile
from apps.api.tests.support.purchases import harness as harness
from tools.kernel_manifest_mock.server import MockConfig, Scenario


pytestmark = [pytest.mark.postgres, pytest.mark.usefixtures("mapping_clock")]


@pytest.mark.parametrize("fault", ["outage", "price", "extra_default", "currency", "quantity", "metric"])
def test_fresh_source_refusals_allocate_no_key_customer_or_hold(harness: PurchaseHarness, fault: str) -> None:
    payload = harness.payload()
    if fault == "outage":
        harness.server.config = MockConfig(app_env="test", token="offline", scenario=Scenario.UNAVAILABLE)
    elif fault == "metric":
        from apps.api.tests.support.kernel import TOKEN

        harness.server.config = MockConfig(app_env="test", token=TOKEN, scenario=Scenario.DISABLED_METRIC)
    elif fault == "price":
        for name in ("prices", "services"):
            path = harness.profile_path.parent / "recordings" / (name + ".json")
            path.write_text(path.read_text().replace("100.01", "100.02"))
    elif fault == "extra_default":
        path = harness.profile_path.parent / "recordings/services.json"
        recording = json.loads(path.read_text())
        extra = {**recording["response"][0], "tariff_service_id": 1002}
        recording["response"].append(extra)
        path.write_text(json.dumps(recording))
    elif fault == "currency":
        edit_profile(harness, lambda profile: profile["inputs"].update(currency=None))
    elif fault == "quantity":
        edit_profile(harness, lambda profile: profile["selection"].update(commercial_quantity="1.5"))
    response = harness.post(payload)
    assert response.status_code in {409, 503}, response.text
    assert_no_purchase(harness)


@pytest.mark.parametrize("same_key", [False, True])
def test_racing_http_admissions_commit_one_intent_and_event(
    harness: PurchaseHarness,
    monkeypatch: pytest.MonkeyPatch,
    same_key: bool,
) -> None:
    payload = harness.payload()
    barrier = Barrier(2)
    original = PurchaseApplication._commit

    def commit(
        self: PurchaseApplication,
        user_id: UUID,
        key: str,
        payload: PurchaseRequest,
        review: PurchaseReview,
        proof: PurchaseAdmissionProof,
    ) -> UUID:
        barrier.wait(timeout=10)
        return original(self, user_id, key, payload, review, proof)

    monkeypatch.setattr(PurchaseApplication, "_commit", commit)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(lambda index: harness.post(payload, "race" if same_key else f"race-{index}"), range(2))
        )
    assert sorted(response.status_code for response in responses) == ([202, 202] if same_key else [202, 409])
    with harness.factory() as db:
        assert db.scalar(select(func.count()).select_from(PurchaseIntent)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(LegalAcceptanceEvent)
                .where(LegalAcceptanceEvent.external_billing_account_id.is_not(None))
            )
            == 1
        )


@pytest.mark.parametrize("during_reads", [False, True])
def test_account_midnight_during_reads_or_before_commit_refuses_without_repricing(
    harness: PurchaseHarness,
    monkeypatch: pytest.MonkeyPatch,
    during_reads: bool,
) -> None:
    harness.now = datetime(2026, 10, 16, 20, 59, tzinfo=UTC)  # Moscow 23:59
    payload = harness.payload()
    after = datetime(2026, 10, 16, 21, 1, tzinfo=UTC)
    if during_reads:
        kernel = harness.client.app.state.sources.require_kernel()
        original_fetch = kernel.fetch_manifest

        async def fetch_manifest(*, budget: PreflightBudget) -> CapabilityManifest:
            result = await original_fetch(budget=budget)
            harness.now = after
            return result

        monkeypatch.setattr(kernel, "fetch_manifest", fetch_manifest)
    else:
        original = PurchaseApplication._commit

        def commit(
            self: PurchaseApplication,
            user_id: UUID,
            key: str,
            payload: PurchaseRequest,
            review: PurchaseReview,
            proof: PurchaseAdmissionProof,
        ) -> UUID:
            harness.now = after
            return original(self, user_id, key, payload, review, proof)

        monkeypatch.setattr(PurchaseApplication, "_commit", commit)
    response = harness.post(payload)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "purchase_effective_date_changed"
    assert_no_purchase(harness)


def test_current_date_is_account_local_instead_of_utc(harness: PurchaseHarness) -> None:
    harness.now = datetime(2026, 10, 15, 22, tzinfo=UTC)  # already Oct 16 in Moscow
    response = harness.post(harness.payload())
    assert response.status_code == 202, response.text
    with harness.factory() as db:
        intent = db.scalar(select(PurchaseIntent))
        assert intent is not None
        assert intent.accepted_snapshot["admission"]["effective_on"] == "2026-10-16"


def test_a_new_approved_revision_between_preflight_and_commit_requires_new_acceptance(
    harness: PurchaseHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from apps.api.tests.support.commercial_mappings import fresh_fixture, reviewed_fixture
    from app.domains.catalog.publication import publish_mapping

    original = PurchaseApplication._commit

    def commit(
        self: PurchaseApplication,
        user_id: UUID,
        key: str,
        payload: PurchaseRequest,
        review: PurchaseReview,
        proof: PurchaseAdmissionProof,
    ) -> UUID:
        async def replacement() -> None:
            evaluation = await fresh_fixture(await reviewed_fixture(allowance=26, revision="review-v2"))
            publish_mapping(
                harness.factory,
                evaluation=evaluation.document,
                expected_previous_revision=1,
                deadline=evaluation.deadline,
                lock_timeout_seconds=0.2,
                allow_simulated=True,
            )

        asyncio.run(replacement())
        return original(self, user_id, key, payload, review, proof)

    monkeypatch.setattr(PurchaseApplication, "_commit", commit)
    response = harness.post(harness.payload())
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "commercial_terms_conflict"
    assert_no_purchase(harness)
