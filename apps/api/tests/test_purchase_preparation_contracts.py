from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domains.purchases.preparation_contracts import CreateUncertain, PreparationEvidence
from app.integrations.lbx.purchase_preparation import LbxPurchasePreparation, PreparationRecord
from app.models import ExternalCreateOperationKind
from apps.api.tests.support.lbx_preparation import (
    PreparationRecording,
    agreement_command,
    preparation_profile,
    preparation_source,
    selected_offer,
    subscription_command,
    user_command,
)


def test_persisted_commands_round_trip_without_credentials_or_money_coercion() -> None:
    record = PreparationRecord(
        profile=preparation_profile(),
        customer=user_command(),
        agreement=agreement_command(),
        subscription=subscription_command(),
    )
    body = record.model_dump_json()
    assert "server_username" not in body
    assert "server_password" not in body
    assert json.loads(body)["agreement"]["debt_threshold"] == 0
    assert PreparationRecord.model_validate_json(body) == record
    for field in ("unknown_provider_state", "payment_token"):
        invalid = {**json.loads(body), field: "untrusted"}
        with pytest.raises(ValidationError):
            PreparationRecord.model_validate_json(json.dumps(invalid))


def test_recorded_b12_completeness_is_explicit_and_cannot_be_assumed() -> None:
    record = PreparationRecord(profile=preparation_profile(), customer=user_command())
    body = json.loads(record.model_dump_json())
    body["profile"].pop("subscription_list_complete")
    with pytest.raises(ValidationError):
        PreparationRecord.model_validate_json(json.dumps(body))


def test_application_evidence_contract_preserves_private_record_and_point_proof() -> None:
    evidence: PreparationEvidence = PreparationRecord(
        profile=preparation_profile(),
        customer=user_command(),
        agreement=agreement_command(),
        subscription=subscription_command(),
    )
    document = evidence.storage_document()
    observed_at = datetime(2026, 10, 16, 12, tzinfo=UTC)
    proven = evidence.point_proven_document(observed_at)
    assert evidence.external_agreement_id == "1601"
    assert document["point_proven_at"] is None
    assert proven == {**document, "point_proven_at": observed_at.isoformat()}
    assert evidence.storage_document() == document
    assert PreparationRecord.model_validate_json(json.dumps(proven)).point_proven_at == observed_at


def test_gateway_normalizes_ambiguous_create_to_application_failure_without_retry() -> None:
    async def scenario() -> None:
        recording = PreparationRecording()
        recording.post_fault = "timeout"
        async with preparation_source(recording) as (client, owner):
            offer = await selected_offer(client, owner, recording.profile)
            record = PreparationRecord(profile=recording.profile, customer=user_command())
            gateway = LbxPurchasePreparation(client, record, offer)
            async with owner.operation() as budget:
                await gateway.before_send(ExternalCreateOperationKind.CUSTOMER, budget)
                with pytest.raises(CreateUncertain):
                    await gateway.create(ExternalCreateOperationKind.CUSTOMER, budget)
        posts = [request for request in recording.requests if request.method == "POST"]
        assert len(posts) == 1
        assert posts[0].url.path.endswith("/users")

    asyncio.run(scenario())
