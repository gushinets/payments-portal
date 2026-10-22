"""Isolated Portal/PG + real Kernel HTTP + explicitly recorded LBX harness."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Thread
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.purchases import purchase_application
from app.core.database import get_db
from app.domains.catalog.contracts import CapabilityManifest
from app.domains.catalog.publication import StoredMapping, publish_mapping
from app.domains.legal.service import create_registration_legal_evidence, get_registration_required_documents
from app.domains.purchases import router as purchase_http
from app.domains.purchases.service import PurchaseApplication
from app.infrastructure.preflight import PreflightBudget
from app.legal_seed import seed_legal_documents
from app.main import create_app
from app.models import (
    AuthSession,
    User,
    UserStatus,
    PurchaseIntent,
    BillingPurchaseScopeHold,
    ExternalBillingCustomer,
    ExternalCreateOperation,
    LegalAcceptanceEvent,
)
from apps.api.tests.support.commercial_mappings import fresh_fixture, operator_settings, reviewed_fixture
from apps.api.tests.support.kernel import TOKEN
from tools.kernel_manifest_mock.server import ManifestMockServer, MockConfig


ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)


@dataclass
class PurchaseHarness:
    client: TestClient
    factory: sessionmaker[Session]
    server: ManifestMockServer
    profile_path: Path
    stored: StoredMapping
    user_id: UUID
    token: str
    other_token: str
    now: datetime = NOW
    source_calls: list[str] = field(default_factory=list)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self.token}

    def review(self) -> dict:
        response = self.client.get("/api/purchases/review/proposal_ai", headers=self.headers)
        assert response.status_code == 200, response.text
        return response.json()

    def payload(self) -> dict:
        review = self.review()
        return {
            "product_id": review["product_id"],
            "revision_id": review["offer"]["revision_id"],
            "expected_fingerprint": review["fingerprint"],
            "commercial_confirmation": True,
            "recurring_confirmation": review["recurring_required"],
            "documents": [
                {"document_version_id": doc["document_version_id"], "acceptance_text_hash": doc["acceptance_text_hash"]}
                for doc in review["documents"]
            ],
        }

    def post(self, payload: dict, key: str = "one-purchase") -> httpx.Response:
        return self.client.post("/api/purchases", headers={**self.headers, "Idempotency-Key": key}, json=payload)


def _seed_user(db: Session, token: str, *, verified: bool = True) -> UUID:
    user = User(
        id=uuid4(),
        tenant_id="anytoolai",
        region="ru",
        email=token + "@example.invalid",
        email_normalized=token + "@example.invalid",
        status=UserStatus.ACTIVE,
        email_verified_at=NOW if verified else None,
    )
    db.add(user)
    db.flush()
    db.add(
        AuthSession(
            user_id=user.id,
            tenant_id="anytoolai",
            region="ru",
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    create_registration_legal_evidence(
        db,
        user=user,
        documents=get_registration_required_documents(db, tenant_id="anytoolai", region="ru", now=NOW),
        accepted_at=NOW,
        ip=None,
        user_agent=None,
    )
    return user.id


@contextmanager
def purchase_harness(
    factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[PurchaseHarness]:
    async def published() -> StoredMapping:
        evaluated = await fresh_fixture(await reviewed_fixture())
        return publish_mapping(
            factory,
            evaluation=evaluated.document,
            expected_previous_revision=0,
            deadline=evaluated.deadline,
            evidence_valid_until=evaluated.evidence_valid_until,
            lock_timeout_seconds=0.2,
            allow_simulated=True,
        ).stored

    stored = asyncio.run(published())
    with factory() as db:
        seed_legal_documents(db)
    with factory.begin() as db:
        user_id = _seed_user(db, "purchase-session")
        _seed_user(db, "other-purchase-session")
    profile_dir = tmp_path / "purchase_mock"
    shutil.copytree(ROOT / "tools/purchase_mock", profile_dir)
    server = ManifestMockServer(("127.0.0.1", 0), MockConfig(app_env="test", token=TOKEN))
    worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    with server:
        worker.start()
        try:
            configuration = operator_settings(
                kernel_base_url=f"http://127.0.0.1:{server.server_port}",
                purchase_simulated_profile_file=profile_dir / "profile.json",
            )
            import app.main as main

            monkeypatch.setattr(main, "settings", configuration)
            monkeypatch.setenv("SKIP_LEGAL_SEED", "true")
            app = create_app()

            def database() -> Iterator[Session]:
                with factory() as db:
                    yield db

            app.dependency_overrides[get_db] = database
            # The production auth dependency is retained; only its PG factory
            # and the Application's server-controlled configuration are supplied.
            with TestClient(app, raise_server_exceptions=False) as client:
                harness = PurchaseHarness(
                    client,
                    factory,
                    server,
                    profile_dir / "profile.json",
                    stored,
                    user_id,
                    "purchase-session",
                    "other-purchase-session",
                )

                def application() -> PurchaseApplication:
                    return purchase_application(configuration, factory, app.state.sources, clock=lambda: harness.now)

                app.dependency_overrides[purchase_http.application] = application
                original_fetch = app.state.sources.require_kernel().fetch_manifest

                async def fetch_manifest(*, budget: PreflightBudget) -> CapabilityManifest:
                    harness.source_calls.append("kernel")
                    return await original_fetch(budget=budget)

                monkeypatch.setattr(app.state.sources.kernel, "fetch_manifest", fetch_manifest)
                yield harness
        finally:
            server.shutdown()
            worker.join(timeout=3)


def edit_profile(harness: PurchaseHarness, edit: Callable[[dict], None]) -> None:
    profile = json.loads(harness.profile_path.read_text())
    edit(profile)
    harness.profile_path.write_text(json.dumps(profile))


@pytest.fixture
def harness(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[PurchaseHarness]:
    with purchase_harness(postgres_session_factory, tmp_path, monkeypatch) as value:
        yield value


def assert_no_purchase(harness: PurchaseHarness) -> None:
    with harness.factory() as db:
        for model in (PurchaseIntent, BillingPurchaseScopeHold, ExternalBillingCustomer, ExternalCreateOperation):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(LegalAcceptanceEvent)
                .where(LegalAcceptanceEvent.external_billing_account_id.is_not(None))
            )
            == 0
        )
