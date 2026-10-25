"""The additive migration retains legacy identity and nullable names on PG."""

from alembic import command
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine, URL

from apps.api.tests.support.postgres import alembic_test_config, reset_public_schema
from apps.api.tests.test_target_persistence_postgres import USER_ID, _seed_purchase_graph


pytestmark = pytest.mark.postgres


def test_optional_names_upgrade_preserves_existing_users(postgres_engine: Engine, database_test_url: URL) -> None:
    reset_public_schema(postgres_engine)
    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "20261021_0003")
        with postgres_engine.begin() as connection:
            _seed_purchase_graph(connection)
        command.upgrade(config, "head")
    columns = {column["name"]: column for column in inspect(postgres_engine).get_columns("users")}
    for field in ("user_surname", "user_name", "user_patronymic"):
        assert columns[field]["nullable"] is True
        assert columns[field]["default"] is None
    with postgres_engine.begin() as connection:
        row = connection.execute(
            text("SELECT user_surname, user_name, user_patronymic FROM users WHERE id=:id"), {"id": USER_ID}
        ).one()
        assert tuple(row) == (None, None, None)
        connection.execute(text("UPDATE users SET user_name=:name WHERE id=:id"), {"id": USER_ID, "name": "Анна-Мария"})
        assert connection.scalar(text("SELECT user_name FROM users WHERE id=:id"), {"id": USER_ID}) == "Анна-Мария"
