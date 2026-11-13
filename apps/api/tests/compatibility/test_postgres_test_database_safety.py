from collections.abc import Callable
from unittest.mock import MagicMock, Mock

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


def test_creation_does_not_pre_drop_a_colliding_database(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.dialect.identifier_preparer.quote.side_effect = lambda name: name
    monkeypatch.setattr(postgres_support, "create_engine", lambda *args, **kwargs: engine)
    database_url = make_url("postgresql+psycopg://owner@localhost/collision_tests")

    postgres_support.create_test_database(database_url, database_url.set(database="postgres"))

    assert [str(call.args[0]) for call in connection.execute.call_args_list] == ["CREATE DATABASE collision_tests"]
    engine.dispose.assert_called_once()


def test_drop_never_forces_other_connections_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.dialect.identifier_preparer.quote.side_effect = lambda name: name
    monkeypatch.setattr(postgres_support, "create_engine", lambda *args, **kwargs: engine)
    database_url = make_url("postgresql+psycopg://owner@localhost/owned_tests")

    postgres_support.drop_test_database(database_url, database_url.set(database="postgres"))

    assert [str(call.args[0]) for call in connection.execute.call_args_list] == ["DROP DATABASE owned_tests"]


@pytest.mark.parametrize("database_name", ["a" * 58 + "_tests", "я" * 29 + "_tests"])
def test_rejects_names_postgres_would_truncate(database_name: str) -> None:
    with pytest.raises(ValueError, match="63 bytes"):
        postgres_support.validate_test_database_url(make_url("postgresql://localhost").set(database=database_name))


def test_session_names_are_unique_and_preserve_explicit_routing() -> None:
    configured = make_url("postgresql+psycopg://owner:synthetic@localhost:15432/configured_tests?connect_timeout=2")
    first = postgres_support.session_test_database_url(configured)
    second = postgres_support.session_test_database_url(configured)
    assert len({first.database, second.database, configured.database}) == 3
    assert first.set(database=configured.database) == second.set(database=configured.database) == configured
    assert postgres_support.validate_test_database_url(first) == first


@pytest.mark.parametrize(
    "changes", [{"database": "production"}, {"host": "other-server"}, {"port": 15432}, {"username": "other-owner"}]
)
@pytest.mark.parametrize("operation", [postgres_support.create_test_database, postgres_support.drop_test_database])
def test_admin_mismatch_is_rejected_before_connecting(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, str | int], operation: Callable[[URL, URL], None]
) -> None:
    create_engine = Mock()
    monkeypatch.setattr(postgres_support, "create_engine", create_engine)
    database_url = make_url("postgresql+psycopg://owner@localhost/owned_tests")
    with pytest.raises(ValueError, match="admin URL"):
        operation(database_url, database_url.set(database="postgres").set(**changes))
    create_engine.assert_not_called()


@pytest.mark.parametrize("template_name", ["production", "owned_tests"])
def test_unsafe_or_self_template_is_rejected_before_connecting(
    monkeypatch: pytest.MonkeyPatch, template_name: str
) -> None:
    create_engine = Mock()
    monkeypatch.setattr(postgres_support, "create_engine", create_engine)
    database_url = make_url("postgresql+psycopg://owner@localhost/owned_tests")
    with pytest.raises(ValueError):
        postgres_support.create_test_database(
            database_url, database_url.set(database="postgres"), template_url=database_url.set(database=template_name)
        )
    create_engine.assert_not_called()


def test_query_database_override_cannot_redirect_owned_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    create_engine = Mock()
    monkeypatch.setattr(postgres_support, "create_engine", create_engine)
    url = make_url("postgresql+psycopg://owner@localhost/owned_tests?dbname=production")
    admin_url = url.set(database="postgres")
    for operation in (
        lambda: postgres_support.session_test_database_url(url),
        lambda: postgres_support.create_test_database(url, admin_url),
        lambda: postgres_support.drop_test_database(url, admin_url),
        lambda: postgres_support.PostgresTestDatabase(url, admin_url),
    ):
        with pytest.raises(ValueError, match="query.*dbname"):
            operation()
    create_engine.assert_not_called()
