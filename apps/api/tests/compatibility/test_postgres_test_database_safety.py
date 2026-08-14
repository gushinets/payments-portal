from collections.abc import Callable
from unittest.mock import Mock

import pytest
from sqlalchemy.engine import URL, make_url

from apps.api.tests.support import postgres as postgres_support


@pytest.mark.parametrize(
    "database_name",
    ["anytoolai_test", "payment_portal_test_tests"],
)
def test_validate_test_database_url_accepts_dedicated_names(
    database_name: str,
) -> None:
    database_url = make_url(
        f"postgresql+psycopg://test@localhost/{database_name}"
    )

    assert postgres_support.validate_test_database_url(database_url) == database_url


@pytest.mark.parametrize(
    ("database_url", "error_message"),
    [
        ("postgresql+psycopg://test@localhost/postgres", "must end"),
        ("postgresql+psycopg://test@localhost/anytoolai", "must end"),
        ("postgresql+psycopg://test@localhost", "database name"),
        ("sqlite+pysqlite:///:memory:", "PostgreSQL URL"),
    ],
)
def test_validate_test_database_url_rejects_unsafe_targets(
    database_url: str,
    error_message: str,
) -> None:
    with pytest.raises(ValueError, match=error_message):
        postgres_support.validate_test_database_url(make_url(database_url))


@pytest.mark.parametrize(
    "operation",
    [postgres_support.create_test_database, postgres_support.drop_test_database],
)
def test_destructive_database_operations_validate_before_connecting(
    operation: Callable[[URL, URL], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_engine = Mock()
    monkeypatch.setattr(postgres_support, "create_engine", create_engine)
    database_url = make_url("postgresql+psycopg://owner@localhost/production")

    with pytest.raises(ValueError, match="Refusing destructive test operations"):
        operation(database_url, database_url.set(database="postgres"))

    create_engine.assert_not_called()


def test_schema_reset_validates_before_connecting() -> None:
    engine = Mock()
    engine.url = make_url("postgresql+psycopg://owner@localhost/production")

    with pytest.raises(ValueError, match="Refusing destructive test operations"):
        postgres_support.reset_public_schema(engine)

    engine.begin.assert_not_called()
