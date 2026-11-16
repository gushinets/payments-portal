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
    database_url = make_url(f"postgresql+psycopg://test@localhost/{database_name}")

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


def test_session_database_names_are_unique_and_never_reuse_configured_database() -> None:
    configured = make_url("postgresql+psycopg://owner@localhost/existing_tests")
    first = postgres_support.unique_test_database_url(configured)
    second = postgres_support.unique_test_database_url(configured)
    assert first.database != second.database != configured.database
    assert first.set(database=configured.database) == configured
    assert postgres_support.validate_test_database_url(first) == first


def test_template_copy_rejects_unsafe_source_before_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    connect = Mock()
    monkeypatch.setattr(postgres_support, "create_engine", connect)
    target = make_url("postgresql+psycopg://owner@localhost/new_tests")
    with pytest.raises(ValueError, match="Refusing destructive"):
        postgres_support.create_test_database(
            target, target.set(database="postgres"), template_url=target.set(database="production")
        )
    connect.assert_not_called()


def test_template_restore_rejects_checked_out_connections() -> None:
    engine = Mock()
    engine.url = make_url("postgresql+psycopg://owner@localhost/owned_tests")
    engine.pool.checkedout.return_value = 1
    with pytest.raises(RuntimeError, match="checked-out"):
        postgres_support.restore_test_database(engine, engine.url.set(database="template_tests"))
    engine.dispose.assert_not_called()
