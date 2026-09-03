from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


def test_expiration_cli_runs_one_batch_with_configured_size(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    class FakeSession:
        committed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            return None

        def commit(self) -> None:
            self.committed = True

    def fake_expire(db, command):
        captured["db"] = db
        captured["command"] = command
        return [object(), object()]

    monkeypatch.setattr(cli, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(cli, "expire_due_subscriptions", fake_expire)

    assert cli.main(["--batch-size", "37"]) == 0

    command = captured["command"]
    assert isinstance(command, cli.ExpireDueSubscriptionsCommand)
    assert command.batch_size == 37
    assert getattr(captured["db"], "committed") is True
    assert capsys.readouterr().out == "expired_subscriptions=2\n"


def test_expiration_cli_does_not_commit_on_failure(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeSession:
        committed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            return None

        def commit(self) -> None:
            self.committed = True

    def fake_expire(db, command):
        captured["db"] = db
        raise RuntimeError("forced expiration failure")

    monkeypatch.setattr(cli, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(cli, "expire_due_subscriptions", fake_expire)

    with pytest.raises(RuntimeError, match="forced expiration failure"):
        cli.main(["--batch-size", "37"])

    assert getattr(captured["db"], "committed") is False


@pytest.mark.postgres
def test_expiration_cli_commits_due_subscription_changes(
    monkeypatch,
    capsys,
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

    assert cli.main(["--batch-size", "1"]) == 0

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
