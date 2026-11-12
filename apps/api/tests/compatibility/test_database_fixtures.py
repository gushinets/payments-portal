from sqlalchemy import text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session

import pytest

pytestmark = pytest.mark.postgres


def test_database_is_created_and_migrated(
    db_session: Session,
    database_test_url: URL,
) -> None:
    """Verify that tests use the dedicated database with the migrated schema."""
    current_database = db_session.execute(text("SELECT current_database()"))
    users_table = db_session.execute(text("SELECT to_regclass('public.users')"))
    migration_revision = db_session.execute(text("SELECT version_num FROM alembic_version"))

    assert database_test_url.database is not None
    assert current_database.scalar_one() == database_test_url.database
    assert users_table.scalar_one() == "users"
    assert migration_revision.scalar_one()


@pytest.mark.parametrize("iteration", [0, 1])
def test_template_restores_committed_data_seed_and_schema(migrated_database: Engine, iteration: int) -> None:
    """Each case must start clean even after the previous case committed DDL/data."""
    with migrated_database.begin() as connection:
        assert connection.scalar(text("SELECT to_regclass('public.isolation_probe')")) is None
        assert connection.scalar(text("SELECT count(*) FROM country_region_rules WHERE country_code = 'RU'")) == 1
        connection.execute(text("CREATE TABLE isolation_probe (id bigint GENERATED ALWAYS AS IDENTITY, value int)"))
        assert (
            connection.scalar(
                text("INSERT INTO isolation_probe (value) VALUES (:value) RETURNING id"), {"value": iteration}
            )
            == 1
        )
        connection.execute(text("DELETE FROM country_region_rules"))
