from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, make_transient_to_detached

from app.commands import expire_subscriptions as cli
from app.infrastructure import sentry as sentry_reporting
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
    monkeypatch.setattr(cli, "configure_sentry", lambda _settings: None)


def test_expiration_cli_runs_one_batch_with_configured_size(monkeypatch, capsys, caplog) -> None:
    captured: dict[str, object] = {}
    timeline: list[str] = []
    report_exception = Mock()
    expired_subscriptions = [Subscription(id=uuid4()), Subscription(id=uuid4())]
    for subscription in expired_subscriptions:
        make_transient_to_detached(subscription)
    expected_subscription_ids = [str(inspect(subscription).identity[0]) for subscription in expired_subscriptions]

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

    def fake_configure_sentry(app_settings) -> None:
        assert app_settings is cli.settings
        timeline.append("sentry_configured")

    monkeypatch.setattr(cli, "configure_logging", lambda: timeline.append("logging_configured"))
    monkeypatch.setattr(cli, "configure_sentry", fake_configure_sentry)
    monkeypatch.setattr(cli, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(cli, "expire_due_subscriptions", fake_expire)
    monkeypatch.setattr(cli, "report_exception", report_exception)
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
        "logging_configured",
        "sentry_configured",
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
        {"run_id": run_id, "subscription_id": subscription_id} for subscription_id in expected_subscription_ids
    ]
    assert events[3].structured == {
        "run_id": run_id,
        "batch_size": 37,
        "expired_count": 2,
    }
    assert capsys.readouterr().out == "expired_subscriptions=2\n"
    report_exception.assert_not_called()


def test_expiration_cli_does_not_commit_on_failure(monkeypatch, caplog) -> None:
    original_error = RuntimeError("forced expiration failure")
    report_exception = Mock()

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            return None

        def commit(self) -> None:
            raise AssertionError("the CLI must not commit outside the lifecycle operation")

    def fake_expire(db, command):
        raise original_error

    monkeypatch.setattr(cli, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(cli, "expire_due_subscriptions", fake_expire)
    monkeypatch.setattr(cli, "report_exception", report_exception)

    with (
        caplog.at_level(logging.INFO, logger=cli.logger.name),
        pytest.raises(RuntimeError, match="forced expiration failure") as raised,
    ):
        cli.main(["--batch-size", "37"])

    assert raised.value is original_error
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
    report_exception.assert_called_once_with(
        original_error,
        operation=cli.Operation.EXPIRE_SUBSCRIPTIONS,
        run_id=events[0].structured["run_id"],
        batch_size=37,
    )


def test_expiration_cli_reports_missing_identity_as_diagnostic_invariant(monkeypatch, caplog) -> None:
    report_exception = Mock()
    valid_subscription = Subscription(id=uuid4())
    make_transient_to_detached(valid_subscription)
    invalid_subscription = Subscription()

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            return None

        def commit(self) -> None:
            raise AssertionError("the CLI must not commit outside the lifecycle operation")

    def fake_expire(db, command):
        return [valid_subscription, invalid_subscription]

    monkeypatch.setattr(cli, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(cli, "expire_due_subscriptions", fake_expire)
    monkeypatch.setattr(cli, "report_exception", report_exception)

    failure_text = "subscription returned without a persisted identity"
    with (
        caplog.at_level(logging.INFO, logger=cli.logger.name),
        pytest.raises(RuntimeError, match=failure_text) as raised,
    ):
        cli.main(["--batch-size", "37"])

    traceback = raised.value.__traceback__
    assert traceback is not None
    traceback_frames = []
    while traceback is not None:
        traceback_frames.append(traceback.tb_frame)
        traceback = traceback.tb_next
    assert any(
        frame.f_code.co_filename == cli.__file__ and frame.f_code.co_name == "main" for frame in traceback_frames
    )

    events = [record for record in caplog.records if record.getMessage().startswith("subscription_expiry_")]
    assert [record.getMessage() for record in events] == [
        "subscription_expiry_run_started",
        "subscription_expiry_diagnostic_invariant_violated",
    ]
    assert events[1].structured == {
        "run_id": events[0].structured["run_id"],
        "batch_size": 37,
        "invariant": "missing_persisted_identity",
    }
    assert "subscription_expiry_run_failed" not in caplog.text
    assert "subscription_expiry_transition_committed" not in caplog.text
    assert "subscription_expiry_run_succeeded" not in caplog.text
    assert failure_text not in caplog.text
    report_exception.assert_called_once_with(
        raised.value,
        operation=cli.Operation.EXPIRE_SUBSCRIPTIONS,
        failure_category=cli.FailureCategory.CONSISTENCY_INVARIANT_VIOLATION,
        run_id=events[0].structured["run_id"],
        batch_size=37,
        invariant=cli.MISSING_PERSISTED_IDENTITY_INVARIANT,
    )


def test_sentry_reporting_failure_does_not_replace_expiration_failure(monkeypatch, caplog) -> None:
    original_error = RuntimeError("forced expiration failure")

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            return None

    def fake_expire(db, command):
        raise original_error

    def fail_capture_exception(*args, **kwargs):
        raise RuntimeError("forced Sentry failure")

    monkeypatch.setattr(cli, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(cli, "expire_due_subscriptions", fake_expire)
    monkeypatch.setattr(sentry_reporting.sentry_sdk, "capture_exception", fail_capture_exception)

    with (
        caplog.at_level(logging.INFO, logger=cli.logger.name),
        pytest.raises(RuntimeError, match="forced expiration failure") as raised,
    ):
        cli.main(["--batch-size", "37"])

    assert raised.value is original_error
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


@pytest.mark.postgres
def test_expiration_cli_commits_due_subscription_changes(
    monkeypatch,
    capsys,
    caplog,
    db_session,
    postgres_engine,
    postgres_session_factory,
) -> None:
    now = datetime.now(timezone.utc)
    plan = db_session.query(Plan).filter(Plan.tenant_id == "anytoolai", Plan.region == "ru").first()
    assert plan is not None
    users = [
        User(
            tenant_id="anytoolai",
            region="ru",
            email=f"expiration-cli-{index}@example.com",
            email_normalized=f"expiration-cli-{index}@example.com",
            status=UserStatus.ACTIVE,
        )
        for index in range(2)
    ]
    db_session.add_all(users)
    db_session.flush()
    subscriptions = [
        Subscription(
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
        for user in users
    ]
    db_session.add_all(subscriptions)
    db_session.flush()
    entitlements = [
        Entitlement(
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
        for user, subscription in zip(users, subscriptions, strict=True)
    ]
    db_session.add_all(entitlements)
    db_session.flush()
    subscription_ids = [subscription.id for subscription in subscriptions]
    entitlement_ids = [entitlement.id for entitlement in entitlements]
    db_session.commit()

    monkeypatch.setattr(cli, "SessionLocal", postgres_session_factory)

    lifecycle = cli.expire_due_subscriptions
    post_return_sql: list[str] = []
    listener_installed = False

    def observe_post_return_sql(conn, cursor, statement, parameters, context, executemany) -> None:
        post_return_sql.append(statement)

    def fake_expire(db: Session, command: cli.ExpireDueSubscriptionsCommand) -> list[Subscription]:
        nonlocal listener_installed
        expired = lifecycle(db, command)
        assert len(expired) == 2
        assert all(inspect(subscription).expired for subscription in expired)
        event.listen(postgres_engine, "before_cursor_execute", observe_post_return_sql)
        listener_installed = True
        return expired

    monkeypatch.setattr(cli, "expire_due_subscriptions", fake_expire)
    try:
        with caplog.at_level(logging.INFO, logger=cli.logger.name):
            assert cli.main(["--batch-size", "2"]) == 0
    finally:
        if listener_installed:
            event.remove(postgres_engine, "before_cursor_execute", observe_post_return_sql)

    assert post_return_sql == []

    diagnostics = [
        record for record in caplog.records if record.getMessage() == "subscription_expiry_transition_committed"
    ]
    assert len(diagnostics) == 2
    assert {record.structured["subscription_id"] for record in diagnostics} == {
        str(subscription_id) for subscription_id in subscription_ids
    }
    run_started = next(record for record in caplog.records if record.getMessage() == "subscription_expiry_run_started")
    run_succeeded = next(
        record for record in caplog.records if record.getMessage() == "subscription_expiry_run_succeeded"
    )
    assert diagnostics[0].structured["run_id"] == run_started.structured["run_id"] == run_succeeded.structured["run_id"]
    assert run_succeeded.structured["expired_count"] == 2

    with postgres_session_factory() as db:
        for subscription_id, entitlement_id in zip(subscription_ids, entitlement_ids, strict=True):
            persisted_subscription = db.get(Subscription, subscription_id)
            persisted_entitlement = db.get(Entitlement, entitlement_id)
            persisted_event = (
                db.query(SubscriptionEvent).filter(SubscriptionEvent.subscription_id == subscription_id).one()
            )
            assert persisted_subscription is not None
            assert persisted_entitlement is not None
            assert persisted_subscription.status is SubscriptionStatus.EXPIRED
            assert persisted_entitlement.status is EntitlementStatus.EXPIRED
            assert persisted_event.event_type is SubscriptionEventType.SUBSCRIPTION_EXPIRED
    assert capsys.readouterr().out == "expired_subscriptions=2\n"
