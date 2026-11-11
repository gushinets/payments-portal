"""Install validated deployment policies before serving any requests."""

from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.infrastructure.queries.backend_policies import install_policy


def initialize_backend_consumers(configuration: Settings, factory: sessionmaker[Session]) -> None:
    if not configuration.backend_consumers:
        return
    with factory.begin() as db:
        for consumer in sorted(configuration.backend_consumers, key=lambda item: item.consumer_id):
            install_policy(db, consumer)
