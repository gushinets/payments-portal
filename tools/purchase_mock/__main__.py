"""Explicit removable development harness; never imported by Portal runtime.

Uses a human-selected, already-migrated worktree PostgreSQL database, real
Kernel HTTP, recorded LBX transport and the Portal's actual HTTP application.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from uuid import uuid4

import httpx
import uvicorn
from sqlalchemy import select

from app.composition.purchases import load_profile
from app.core.database import SessionLocal
from app.core.settings import settings
from app.domains.legal.service import (
    create_registration_legal_evidence,
    get_registration_required_documents,
)
from app.integrations.lbx.client import API_PATH
from app.integrations.lbx.recorded_preparation import RecordedPreparationTransport
from app.legal_seed import seed_legal_documents
from app.models import AuthSession, User, UserStatus
from apps.api.tests.support.kernel_walkthrough import require_development_operator


def seed_user() -> None:
    token = os.environ.get("PURCHASE_TEST_SESSION_TOKEN", "")
    if len(token) < 32 or not token.isascii() or not token.isalnum():
        raise ValueError(
            "explicit alphanumeric test session token of at least 32 characters required"
        )
    now = datetime.now(UTC)
    with SessionLocal() as db:
        seed_legal_documents(
            db, tenant_id=settings.instance_tenant_id, region=settings.instance_region
        )
    with SessionLocal.begin() as db:
        email = "purchase-walkthrough@example.invalid"
        user = db.scalar(select(User).where(User.email_normalized == email))
        if user is None:
            user = User(
                id=uuid4(),
                tenant_id=settings.instance_tenant_id,
                region=settings.instance_region,
                email=email,
                email_normalized=email,
                status=UserStatus.ACTIVE,
                email_verified_at=now,
            )
            db.add(user)
            db.flush()
            create_registration_legal_evidence(
                db,
                user=user,
                documents=get_registration_required_documents(
                    db, tenant_id=user.tenant_id, region=user.region, now=now
                ),
                accepted_at=now,
                ip=None,
                user_agent=None,
            )
        digest = hashlib.sha256(token.encode()).hexdigest()
        if (
            db.scalar(select(AuthSession.id).where(AuthSession.token_hash == digest))
            is None
        ):
            db.add(
                AuthSession(
                    user_id=user.id,
                    tenant_id=user.tenant_id,
                    region=user.region,
                    token_hash=digest,
                    expires_at=now + timedelta(hours=8),
                )
            )


def serve(port: int, traffic_file: Path) -> None:
    import app.composition.purchases as composition
    from app.main import create_app

    root = Path(__file__).resolve().parents[2]
    traffic_file = traffic_file.resolve()
    if not traffic_file.is_relative_to(root / ".harness"):
        raise ValueError("traffic file must be private worktree .harness output")
    traffic_file.parent.mkdir(parents=True, exist_ok=True)
    lock = Lock()

    class AuditedRecording(RecordedPreparationTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            # Only method + fixed recording path; no headers, query, body,
            # credential, customer correlation, or remote error is captured.
            suffix = request.url.path.removeprefix(API_PATH)
            if suffix != "/auth":
                with lock, traffic_file.open("a", encoding="utf-8") as stream:
                    stream.write(
                        json.dumps({"method": request.method, "path": suffix}) + "\n"
                    )
            return await super().handle_async_request(request)

    composition.RecordedPreparationTransport = AuditedRecording
    uvicorn.run(create_app(), host="127.0.0.1", port=port, access_log=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Isolated ANY-709 simulated purchase harness"
    )
    parser.add_argument("command", choices=("seed-user", "serve"))
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--traffic-file",
        type=Path,
        default=Path(".harness/purchase-walkthrough/traffic.jsonl"),
    )
    arguments = parser.parse_args()
    # Existing UID/scope/development and worktree DB guard. No migration/reset
    # or implicit publication, user seed or startup from the production app.
    require_development_operator(settings)
    load_profile(settings)
    if arguments.command == "seed-user":
        seed_user()
        print(
            "SIMULATED verified test session provisioned; no purchase or provider mutation"
        )
    else:
        serve(arguments.port, arguments.traffic_file)


if __name__ == "__main__":
    main()
