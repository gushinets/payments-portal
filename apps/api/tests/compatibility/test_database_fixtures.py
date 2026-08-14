from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session


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
