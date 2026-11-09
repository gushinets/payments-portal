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


VALID = load("fixtures/valid.json")
INVALID = load("fixtures/invalid.json")
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
    """Specify acknowledgement identity; PostgreSQL durability belongs to Step 9."""
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
    assert operations["/internal/v1/kernel-sessions/introspect"]["permission"] == "kernel-session:introspect"
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
