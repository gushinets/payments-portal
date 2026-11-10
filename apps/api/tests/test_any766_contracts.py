"""Offline target conformance, not evidence of implemented paid HTTP behavior."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from .support.paid_contracts import MODELS, UsageQuery, UsageResponse, correlate_usage, validate_contract

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "docs/contracts/portal-kernel-paid"


def load(name: str) -> Any:
    return json.loads((CONTRACT / name).read_text(encoding="utf-8"))


VALID = load("fixtures/valid.json") + load("fixtures/backend-valid.json")
INVALID = load("fixtures/invalid.json") + load("fixtures/backend-invalid.json")
CONTEXTUAL = load("fixtures/contextual-invalid.json")


def test_retained_bytes_and_complete_contract_inventory() -> None:
    entries = [line.split("  ") for line in (CONTRACT / "SHA256SUMS").read_text().splitlines()]
    paths = [path for _, path in entries]
    actual = {
        path.relative_to(CONTRACT).as_posix()
        for folder in ("schemas", "fixtures")
        for path in (CONTRACT / folder).glob("*.json")
    } | {"contract-index.json"}
    assert len(paths) == len(set(paths))
    assert set(paths) == actual
    for digest, path in entries:
        assert hashlib.sha256((CONTRACT / path).read_bytes()).hexdigest() == digest, path
    assert set(MODELS) == set(load("contract-index.json")["schema_owners"])
    assert {row["contract"] for row in VALID} == set(MODELS)
    assert {row["contract"] for row in INVALID} == set(MODELS)


def resolved_shape(value: Any, root: dict[str, Any]) -> Any:
    """Compare independently authored shapes, ignoring annotations and semantic rules.

    Timestamp patterns remain compared; strict integers and uniqueness also have negative vectors.
    oneOf/anyOf coincide here because each object variant has an exclusive status.
    """
    if isinstance(value, list):
        return sorted((resolved_shape(item, root) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        target = root
        for part in value["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        return resolved_shape(target, root)
    ignored = {"$schema", "$defs", "title", "description", "uniqueItems"}
    return {
        "anyOf" if key == "oneOf" else key: resolved_shape(item, root)
        for key, item in value.items()
        if key not in ignored
    }


@pytest.mark.parametrize("name", MODELS)
def test_independent_oracle_matches_target_schema_shape(name: str) -> None:
    schema = load(f"schemas/{name}.schema.json")
    independent = MODELS[name].model_json_schema()
    assert resolved_shape(schema, schema) == resolved_shape(independent, independent)


@pytest.mark.parametrize("case", VALID, ids=lambda row: row["name"])
def test_positive_target_fixtures(case: dict[str, Any]) -> None:
    parsed = validate_contract(case["contract"], json.dumps(case["payload"]))
    assert parsed.model_dump(mode="json") == case["payload"]


@pytest.mark.parametrize("case", INVALID, ids=lambda row: row["name"])
def test_negative_target_fixtures(case: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        validate_contract(case["contract"], json.dumps(case["payload"]))


@pytest.mark.parametrize("case", CONTEXTUAL, ids=lambda row: row["name"])
def test_valid_usage_shape_cannot_override_requested_owner_or_ids(case: dict[str, Any]) -> None:
    response = UsageResponse.model_validate_json(json.dumps(case["response"]))
    query = UsageQuery.model_validate_json(json.dumps(case["query"]))
    with pytest.raises(ValueError):
        correlate_usage(response, query)


def test_unknown_and_foreign_usage_are_indistinguishable_and_busy_is_not_exhausted() -> None:
    fixtures = {row["name"]: row["payload"] for row in VALID}
    assert fixtures["usage-unknown"] == fixtures["usage-foreign"]
    busy = fixtures["usage-busy"]["items"][0]
    exhausted = fixtures["usage-exhausted"]["items"][0]
    assert busy["available"] == exhausted["available"] == 0
    assert busy["remaining"] == 1 and exhausted["remaining"] == 0
    correlate_usage(
        UsageResponse.model_validate_json(json.dumps(fixtures["usage-mixed"])),
        UsageQuery.model_validate_json(json.dumps(fixtures["usage-query"])),
    )


def test_five_second_clock_budget_vectors() -> None:
    for case in load("fixtures/protocol-vectors.json")["clock"]:
        now = datetime.fromisoformat(case["now"])
        deadlines = [datetime.fromisoformat(value) for value in case["deadlines"]]
        expires = min([now + timedelta(seconds=300), *deadlines]) - timedelta(seconds=5)
        assert expires == datetime.fromisoformat(case["expires_at"])
        assert min(now + timedelta(seconds=60), expires) == datetime.fromisoformat(case["refresh_after"])


def test_exact_sent_revision_acknowledgement_vectors() -> None:
    for case in load("fixtures/protocol-vectors.json")["invalidation_ack"]:
        delivered = max(case["delivered_before"], case["sent"])
        assert delivered == case["delivered_after"]
        assert (case["pending"] if case["pending"] > delivered else None) == case["pending_after"]


def test_exhaustion_duplicate_and_historical_delivery_vectors() -> None:
    """Specify acknowledgement identity; PostgreSQL durability belongs to Step 14."""
    identity_fields = ("tenant_id", "region", "user_id", "allowance_id", "event_type")
    vectors = load("fixtures/protocol-vectors.json")["exhaustion_delivery"]
    first_key = tuple(vectors[0]["event"][field] for field in identity_fields)
    for case in vectors:
        event = validate_contract("exhaustion-v1", json.dumps(case["event"]))
        payload = event.model_dump(mode="json")
        matches = all(payload[field] == value for field, value in case["issued"].items())
        assert case["status"] == (204 if matches else 409)
        assert case["new_hint"] == (matches and not case["already_committed"])
        if case["name"] in {"duplicate", "historical"}:
            assert tuple(payload[field] for field in identity_fields) == first_key


def test_target_operations_keep_directional_permissions_and_safe_custody() -> None:
    index = load("contract-index.json")
    assert index["status"] == "TARGET_ONLY"
    operations = {row["path"]: row for row in index["operations"]}
    assert len(operations) == len(index["operations"]) == 10
    assert all(row["cache_control"] == "no-store" for row in operations.values())
    assert operations["/internal/v1/backend-sessions/introspect"]["permission"] == "backend-session:introspect"
    assert operations["/internal/v1/allowance-exhaustions"]["statuses"] == [204, 401, 403, 409, 422, 503]
    assert operations["/api/paid-usage"]["permission"] == "verified-email-billing-session"
    assert index["schema_owners"]["exchange-request-v1"] == "Portal"
    assert operations["/v1/portal-session/exchange"]["host"] == "Kernel"


def test_identity_fixture_flow_has_matching_pkce_and_bounded_lifetimes() -> None:
    fixtures = {row["name"]: row["payload"] for row in VALID}
    verifier = fixtures["exchange-request"]["code_verifier"]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
    assert challenge.decode("ascii").rstrip("=") == fixtures["code-request"]["code_challenge"]
    assert fixtures["exchange-request"]["code"] == fixtures["code-response"]["code"]
    issued_at = datetime.fromisoformat("2026-11-09T04:00:00Z")
    assert datetime.fromisoformat(fixtures["code-response"]["expires_at"]) - issued_at == timedelta(seconds=60)
    token_expiry = datetime.fromisoformat(fixtures["exchange-response"]["expires_at"])
    assert token_expiry - issued_at == timedelta(minutes=30)
    assert token_expiry - datetime.fromisoformat(fixtures["introspection-response"]["valid_until"]) == timedelta(
        seconds=5
    )


def test_usage_tuple_mismatch_is_unavailable_instead_of_an_invented_zero() -> None:
    fixtures = {row["name"]: row["payload"] for row in VALID}
    for case in load("fixtures/protocol-vectors.json")["usage_tuple"]:
        response = {**fixtures["usage-busy"], "items": [case["item"]]}
        validate_contract("usage-response-v1", json.dumps(response))
        matches = all(case["item"][field] == value for field, value in case["local"].items())
        assert case["cabinet_status"] == ("observed" if matches else "unavailable")


@pytest.mark.parametrize("case", load("fixtures/backend-contextual.json"), ids=lambda row: row["name"])
def test_consumer_snapshot_context_is_not_proven_by_valid_wire_shape(case: dict[str, Any]) -> None:
    """Offline acceptance oracle; actual locks/install and HTTP arrive in Step 12."""
    snapshot = validate_contract("snapshot-v3", json.dumps(case["snapshot"])).model_dump(mode="json")
    principal = case["principal"]
    accepted = case["accepted"]
    identity = ("consumer_id", "tenant_id", "region", "consumer_policy_revision")
    matches = all(snapshot[field] == principal[field] for field in identity)
    matches &= snapshot["user_id"] == case["requested_user_id"]
    matches &= "access-snapshot:read" in principal["permissions"]
    matches &= snapshot["consumer_policy_revision"] >= case["policy_floor"]
    matches &= snapshot["access_revision"] >= case["access_floor"]
    matches &= all(row["product_id"] in principal["allowed_products"] for row in snapshot["grants"])
    if accepted is not None and all(
        snapshot[field] == accepted[field] for field in (*identity, "user_id", "access_revision")
    ):
        matches &= sorted(snapshot["grants"], key=lambda row: row["product_id"]) == sorted(
            accepted["grants"], key=lambda row: row["product_id"]
        )
        matches &= sorted(snapshot["allowances"], key=lambda row: row["allowance_id"]) == sorted(
            accepted["allowances"], key=lambda row: row["allowance_id"]
        )
    assert ("ACCEPT" if matches else "REFUSE") == case["result"]


def test_target_consumer_policy_audience_deadline_and_recipient_vectors() -> None:
    vectors = load("fixtures/backend-protocol.json")
    for case in vectors["identity"]:
        principal = case["principal"]
        permitted = (
            principal["consumer_id"] == case["audience"]
            and principal["tenant_id"] == case["tenant_id"]
            and principal["region"] == case["region"]
            and f"backend-session:{case['operation']}" in principal["permissions"]
        )
        assert ("ACCEPT" if permitted else "REFUSE") == case["result"]
    for case in vectors["policies"]:
        for prefix in ("stored", "configured"):
            document = {field: vectors["principals"][0][field] for field in ("consumer_id", "tenant_id", "region")}
            document["allowed_products"] = sorted(set(case[f"{prefix}_products"]))
            digest = hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            assert f"sha256:{digest}" == case[f"{prefix}_digest"]
        allowed = (
            type(case["configured_revision"]) is int
            and case["configured_revision"] >= 1
            and (
                case["configured_revision"] > case["stored_revision"]
                or (
                    case["configured_revision"] == case["stored_revision"]
                    and case["configured_digest"] == case["stored_digest"]
                )
            )
        )
        assert ("ACCEPT" if allowed else "REFUSE") == case["result"]
        assert case["access_revision_before"] == case["access_revision_after"]
    now = datetime.fromisoformat(vectors["now"])
    for case in vectors["filtered_deadlines"]:
        deadlines = [
            datetime.fromisoformat(value)
            for product, value in case["deadlines"].items()
            if product in case["allowed_products"]
        ]
        expiry = min([now + timedelta(seconds=300), *deadlines]) - timedelta(seconds=5)
        assert (200 if expiry > now else 503) == case["status"]
        if case["expires_at"] is not None:
            assert expiry == datetime.fromisoformat(case["expires_at"])
    case = vectors["recipient_ack"]
    before = case["before"]
    recipient = case["recipient"]
    settled = {
        **before,
        recipient: {**before[recipient], "delivered": max(before[recipient]["delivered"], case["sent"])},
    }
    assert settled == case["after"]
    for case in vectors["source_ownership"]:
        matches = (
            case["consumer_id"] == "synthetic-summary"
            and case["product_id"] == "synthetic_summary"
            and case["metric_key"] == "synthetic_summary.results"
            and case["unit"] == "result"
        )
        assert ("ACCEPT" if matches else "REFUSE") == case["result"]


@pytest.mark.parametrize("case", load("fixtures/backend-history.json"), ids=lambda row: row["name"])
def test_current_history_readers_preserve_pre_amendment_serialization(case: dict[str, Any]) -> None:
    from app.domains.catalog.commercial_offer import canonical_document
    from app.domains.catalog.product_link import ProductLinkDocument
    from app.domains.purchases.contracts import AcceptedPurchase
    from app.domains.purchases.technical_terms import AcceptedTechnicalTerms

    encoded = case["serialized"]
    assert hashlib.sha256(encoded.encode()).hexdigest() == case["sha256"]
    models = {"link": ProductLinkDocument, "purchase": AcceptedPurchase, "terms": AcceptedTechnicalTerms}
    parsed = models[case["kind"]].model_validate_json(encoded)
    before = json.loads(encoded)
    assert parsed.model_dump(mode="json") == before
    assert canonical_document(parsed.model_dump(mode="json")) == encoded
    # Legacy ownership is a read-view rule, never a new default in stored evidence.
    assert "technical_source_id" not in before and "backend_consumer_id" not in before
    assert case["resolved_technical_source_id"] == case["resolved_backend_consumer_id"] == "platform-kernel"
    if case["name"] == "legacy-purchase-v1-no-quantity":
        assert parsed.technical_terms is None
    if case["kind"] == "purchase" and parsed.technical_terms is not None:
        assert parsed.meaning.expected_technical_terms_digest == before["meaning"]["expected_technical_terms_digest"]


def test_common_guide_examples_match_reviewed_target_fixtures() -> None:
    import re

    guide = (ROOT / "docs/contracts/product-backend-api/README.md").read_text()
    examples = [json.loads(value) for value in re.findall(r"```json\n(.*?)\n```", guide, flags=re.DOTALL)]
    contracts = ["code-response-v1", "exchange-response-v2", "introspection-response-v2", "snapshot-v3"]
    fixtures = {row["name"]: row["payload"] for row in VALID}
    for contract, example in zip(contracts, examples[1:], strict=True):
        validate_contract(contract, json.dumps(example))
        expected = fixtures["code-response" if contract == "code-response-v1" else f"platform-kernel-{contract}"]
        assert example == expected
    bodies = [json.loads(value) for value in re.findall(r"\n\n(\{[^\n]+\})\n```", guide)]
    for contract, body in zip(
        ("code-request-v2", "exchange-request-v1", "introspection-request-v1"), bodies, strict=True
    ):
        validate_contract(contract, json.dumps(body))
    assert bodies[0] == fixtures["platform-kernel-code-request-v2"]
    assert bodies[1] == fixtures["exchange-request"]
    assert bodies[2] == fixtures["introspection-request"]
