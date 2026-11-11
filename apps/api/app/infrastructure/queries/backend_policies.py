"""Persistence of the configured monotonic consumer policy guard."""

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.backend_consumers import BackendConsumer
from app.models import BackendConsumerPolicy


class BackendPolicyConflict(Exception):
    pass


def _policy_query(consumer: BackendConsumer) -> Select[tuple[BackendConsumerPolicy]]:
    return (
        select(BackendConsumerPolicy)
        .where(
            BackendConsumerPolicy.consumer_id == consumer.consumer_id,
            BackendConsumerPolicy.tenant_id == consumer.tenant_id,
            BackendConsumerPolicy.region == consumer.region,
        )
        .execution_options(populate_existing=True)
    )


def install_policy(db: Session, consumer: BackendConsumer) -> None:
    insert = sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert
    db.execute(
        insert(BackendConsumerPolicy)
        .values(
            consumer_id=consumer.consumer_id,
            tenant_id=consumer.tenant_id,
            region=consumer.region,
            consumer_policy_revision=consumer.consumer_policy_revision,
            policy_digest=consumer.policy_digest,
        )
        .on_conflict_do_nothing()
    )
    row = db.scalar(_policy_query(consumer).with_for_update())
    if row.consumer_policy_revision > consumer.consumer_policy_revision or (
        row.consumer_policy_revision == consumer.consumer_policy_revision
        and row.policy_digest != consumer.policy_digest
    ):
        raise BackendPolicyConflict("Backend policy version rollback or conflicting digest")
    row.consumer_policy_revision = consumer.consumer_policy_revision
    row.policy_digest = consumer.policy_digest


def require_current_policy(db: Session, consumer: BackendConsumer) -> None:
    row = db.scalar(_policy_query(consumer))
    if row is None or (row.consumer_policy_revision, row.policy_digest) != (
        consumer.consumer_policy_revision,
        consumer.policy_digest,
    ):
        raise BackendPolicyConflict("Backend policy installation is not current")
