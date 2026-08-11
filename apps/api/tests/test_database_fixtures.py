from sqlalchemy import text
from sqlalchemy.orm import Session


def test_database_is_created_and_migrated(
    db_session: Session,
    database_test_name: str,
) -> None:
    database_name = db_session.execute(text("SELECT current_database()"))
    current_revision = db_session.execute(
        text("SELECT version_num FROM alembic_version")
    )
    users_table = db_session.execute(text("SELECT to_regclass('public.users')"))
    import pdb;pdb.set_trace()

    assert database_name.scalar_one() == database_test_name
    assert current_revision.scalar_one() == "20260729_0004"
    assert users_table.scalar_one() == "users"
