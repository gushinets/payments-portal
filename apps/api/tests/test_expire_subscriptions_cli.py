from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.commands import expire_subscriptions as cli
from app.models import (
    Entitlement,
    EntitlementSource,
    EntitlementStatus,
    Plan,
    Subscription,
    SubscriptionEvent,
    SubscriptionEventType,
    SubscriptionRenewalMode,
    SubscriptionStatus,
    User,
    UserStatus,
)


@pytest.fixture(autouse=True)
def _keep_pytest_logging_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "configure_logging", lambda: None)


def test_expiration_cli_runs_one_batch_with_configured_size(monkeypatch, capsys, caplog) -> None:
    captured: dict[str, object] = {}
    timeline: list[str] = []
    expired_subscriptions = [SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())]

    class TimelineHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            timeline.append(record.getMessage())

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            return None

        def commit(self) -> None:
            raise AssertionError("the CLI must not commit outside the lifecycle operation")

    def fake_expire(db, command):
        captured["command"] = command
        timeline.append("lifecycle_called")
        timeline.append("lifecycle_returned")
        return expired_subscriptions

    monkeypatch.setattr(cli, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(cli, "expire_due_subscriptions", fake_expire)
    handler = TimelineHandler()
    cli.logger.addHandler(handler)

    try:
        with caplog.at_level(logging.INFO, logger=cli.logger.name):
            assert cli.main(["--batch-size", "37"]) == 0
    finally:
        cli.logger.removeHandler(handler)

    command = captured["command"]
    assert isinstance(command, cli.ExpireDueSubscriptionsCommand)
    assert command.batch_size == 37
    assert timeline == [
        "subscription_expiry_run_started",
        "lifecycle_called",
        "lifecycle_returned",
        "subscription_expiry_transition_committed",
        "subscription_expiry_transition_committed",
        "subscription_expiry_run_succeeded",
    ]
    assert not [record for record in caplog.records if record.getMessage() == "subscription_expiry_run_failed"]
    events = [record for record in caplog.records if record.getMessage().startswith("subscription_expiry_")]
    assert [record.getMessage() for record in events] == [
        "subscription_expiry_run_started",
        "subscription_expiry_transition_committed",
        "subscription_expiry_transition_committed",
        "subscription_expiry_run_succeeded",
    ]
    run_ids = {record.structured["run_id"] for record in events}
    assert len(run_ids) == 1
    run_id = next(iter(run_ids))
    assert events[0].structured == {"run_id": run_id, "batch_size": 37}
    assert [record.structured for record in events[1:3]] == [
        {"run_id": run_id, "subscription_id": str(subscription.id)} for subscription in expired_subscriptions
    ]
    assert events[3].structured == {
        "run_id": run_id,
        "batch_size": 37,
        "expired_count": 2,
    }
    assert capsys.readouterr().out == "expired_subscriptions=2\n"


def test_expiration_cli_does_not_commit_on_failure(monkeypatch, caplog) -> None:
    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            return None

        def commit(self) -> None:
            raise AssertionError("the CLI must not commit outside the lifecycle operation")

    def fake_expire(db, command):
        raise RuntimeError("forced expiration failure")

    monkeypatch.setattr(cli, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(cli, "expire_due_subscriptions", fake_expire)

    with caplog.at_level(logging.INFO, logger=cli.logger.name):
        with pytest.raises(RuntimeError, match="forced expiration failure"):
            cli.main(["--batch-size", "37"])

    events = [record for record in caplog.records if record.getMessage().startswith("subscription_expiry_")]
    assert [record.getMessage() for record in events] == [
        "subscription_expiry_run_started",
        "subscription_expiry_run_failed",
    ]
    assert events[1].structured == {
        "run_id": events[0].structured["run_id"],
        "batch_size": 37,
        "error_type": "RuntimeError",
    }
    assert "forced expiration failure" not in caplog.text


@pytest.mark.postgres
def test_expiration_cli_commits_due_subscription_changes(
    monkeypatch,
    capsys,
    caplog,
    db_session,
    postgres_session_factory,
) -> None:
    now = datetime.now(timezone.utc)
    plan = db_session.query(Plan).filter(Plan.tenant_id == "anytoolai", Plan.region == "ru").first()
    assert plan is not None
    user = User(
        tenant_id="anytoolai",
        region="ru",
        email="expiration-cli@example.com",
        email_normalized="expiration-cli@example.com",
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    db_session.flush()
    subscription = Subscription(
        tenant_id="anytoolai",
        region="ru",
        user_id=user.id,
        plan_id=plan.id,
        scope_type=plan.scope_type,
        product_id=plan.product_id,
        bundle_id=plan.bundle_id,
        status=SubscriptionStatus.ACTIVE,
        renewal_mode=SubscriptionRenewalMode.MANUAL,
        current_period_start=now - timedelta(days=31),
        current_period_end=now - timedelta(days=1),
    )
    db_session.add(subscription)
    db_session.flush()
    entitlement = Entitlement(
        tenant_id="anytoolai",
        region="ru",
        user_id=user.id,
        subscription_id=subscription.id,
        plan_id=plan.id,
        scope_type=plan.scope_type,
        product_id=plan.product_id,
        bundle_id=plan.bundle_id,
        status=EntitlementStatus.ACTIVE,
        valid_from=subscription.current_period_start,
        valid_until=subscription.current_period_end,
        source=EntitlementSource.TRIAL,
    )
    db_session.add(entitlement)
    db_session.flush()
    subscription_id = subscription.id
    entitlement_id = entitlement.id
    db_session.commit()

    monkeypatch.setattr(cli, "SessionLocal", postgres_session_factory)

    with caplog.at_level(logging.INFO, logger=cli.logger.name):
        assert cli.main(["--batch-size", "1"]) == 0

    diagnostics = [
        record for record in caplog.records if record.getMessage() == "subscription_expiry_transition_committed"
    ]
    assert len(diagnostics) == 1
    assert diagnostics[0].structured["subscription_id"] == str(subscription_id)
    run_started = next(record for record in caplog.records if record.getMessage() == "subscription_expiry_run_started")
    run_succeeded = next(
        record for record in caplog.records if record.getMessage() == "subscription_expiry_run_succeeded"
    )
    assert diagnostics[0].structured["run_id"] == run_started.structured["run_id"] == run_succeeded.structured["run_id"]
    assert run_succeeded.structured["expired_count"] == 1

    with postgres_session_factory() as db:
        persisted_subscription = db.get(Subscription, subscription_id)
        persisted_entitlement = db.get(Entitlement, entitlement_id)
        persisted_event = db.query(SubscriptionEvent).filter(SubscriptionEvent.subscription_id == subscription_id).one()
        assert persisted_subscription is not None
        assert persisted_entitlement is not None
        assert persisted_subscription.status is SubscriptionStatus.EXPIRED
        assert persisted_entitlement.status is EntitlementStatus.EXPIRED
        assert persisted_event.event_type is SubscriptionEventType.SUBSCRIPTION_EXPIRED
    assert capsys.readouterr().out == "expired_subscriptions=1\n"
