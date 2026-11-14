"""Install validated deployment policies before serving any requests."""

from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.infrastructure.queries.backend_policies import install_policy
from app.models import BackendConsumerPolicy


def initialize_backend_consumers(configuration: Settings, factory: sessionmaker[Session]) -> None:
    with factory.begin() as db:
        # Install the complete configured recipient set during the quiesced cutover.
        # Retired recipients retain their outbox history, but receive no new work.
        db.execute(
            update(BackendConsumerPolicy)
            .where(
                BackendConsumerPolicy.tenant_id == configuration.instance_tenant_id,
                BackendConsumerPolicy.region == configuration.instance_region,
            )
            .values(snapshot_delivery_enabled=False)
        )
        for consumer in sorted(configuration.backend_consumers, key=lambda item: item.consumer_id):
            install_policy(db, consumer)
