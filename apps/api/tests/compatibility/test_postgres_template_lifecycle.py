from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError, ProgrammingError

from apps.api.tests.support import postgres as support

pytestmark = pytest.mark.postgres


def _existing_databases(admin_url: URL, names: list[str]) -> list[str]:
    engine = create_engine(admin_url)
    try:
        with engine.connect() as connection:
            return list(
                connection.execute(
                    text("SELECT datname FROM pg_database WHERE datname = ANY(:names)"), {"names": names}
                ).scalars()
            )
    finally:
        engine.dispose()


def test_fresh_clones_survive_mixed_migration_order_in_separate_processes(
    tmp_path: Path, database_admin_url: URL
) -> None:
    """Exercise the real fixtures, one migration build per process and function scope."""
    module = tmp_path / "test_mixed.py"
    report = tmp_path / "names.json"
    module.write_text(
        """
import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch
import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import Engine, URL
from apps.api.tests.support import postgres as support

@pytest.fixture(scope="session", autouse=True)
def count_template_migrations() -> Iterator[None]:
    with patch.object(support, "run_migrations", wraps=support.run_migrations) as migrate:
        yield
        assert migrate.call_count == 1

def assert_seed(engine: Engine) -> None:
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT code FROM regions")) == "ru"
        assert connection.scalar(text("SELECT country_code FROM country_region_rules")) == "RU"
        assert connection.scalar(text("SELECT count(*) FROM document_versions")) > 0
        assert connection.scalar(text("SELECT count(*) FROM users")) == 0
        assert connection.scalar(text("SELECT to_regclass('public.pollution')")) is None
        assert connection.scalar(text("SELECT version_num FROM alembic_version"))

def test_first(
    migrated_database: Engine, database_test_url: URL, postgres_database: support.PostgresTestDatabase
) -> None:
    assert_seed(migrated_database)
    Path(REPORT).write_text(json.dumps([database_test_url.database, postgres_database.template_url.database]))
    with migrated_database.begin() as connection:
        connection.execute(text("CREATE TABLE pollution (value text)"))
        connection.execute(text("INSERT INTO pollution VALUES ('committed')"))

def test_second(migrated_database: Engine) -> None:
    assert_seed(migrated_database)

def test_schema(postgres_engine: Engine, database_test_url: URL) -> None:
    support.reset_public_schema(postgres_engine)
    with support.alembic_test_config(database_test_url) as config:
        command.upgrade(config, "head")
        command.downgrade(config, "base")
    with postgres_engine.connect() as connection:
        assert connection.scalar(text("SELECT to_regclass('public.users')")) is None

def test_final(migrated_database: Engine) -> None:
    assert_seed(migrated_database)
""".replace("REPORT", repr(str(report))),
        encoding="utf-8",
    )
    names: list[str] = []
    for _ in range(2):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-p",
                "apps.api.tests.conftest",
                "-c",
                str(support.REPOSITORY_ROOT / "pytest.ini"),
                "-q",
                str(module),
            ],
            env=dict(os.environ),
            cwd=support.REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        names.extend(json.loads(report.read_text(encoding="utf-8")))
    assert len(set(names)) == 4
    assert _existing_databases(database_admin_url, names) == []


@pytest.mark.parametrize("collide_template", [False, True])
def test_initial_collisions_preserve_existing_resources(
    postgres_database: support.PostgresTestDatabase, collide_template: bool
) -> None:
    url = (
        support.session_test_database_url(postgres_database.database_url)
        if collide_template
        else postgres_database.database_url
    )
    candidate = support.PostgresTestDatabase(url, postgres_database.admin_url)
    if collide_template:
        candidate.template_url = postgres_database.template_url
    try:
        with pytest.raises(ProgrammingError, match="already exists"):
            candidate.create()
    finally:
        candidate.close()
    expected = [postgres_database.database_url.database, postgres_database.template_url.database]
    assert sorted(_existing_databases(postgres_database.admin_url, expected)) == sorted(expected)
    if collide_template:
        assert _existing_databases(postgres_database.admin_url, [url.database]) == []


@pytest.mark.parametrize("fail_migration", [False, True])
def test_owned_resources_are_cleaned_after_setup_or_test_failure(
    database_test_url: URL, database_admin_url: URL, monkeypatch: pytest.MonkeyPatch, fail_migration: bool
) -> None:
    url = support.session_test_database_url(database_test_url)
    names = [url.database]
    migrate = support.run_migrations

    def record_migration(template_url: URL) -> None:
        names.append(template_url.database)
        migrate(template_url)
        if fail_migration:
            raise RuntimeError("injected failure")

    monkeypatch.setattr(support, "run_migrations", record_migration)
    with pytest.raises(RuntimeError, match="injected failure"):
        with support.postgres_test_database(url, database_admin_url) as owned:
            owned.restore()
            raise RuntimeError("injected failure")
    assert len(names) == 2
    assert _existing_databases(database_admin_url, names) == []


def test_checked_out_connection_blocks_replacement_and_teardown(
    database_test_url: URL, database_admin_url: URL
) -> None:
    url = support.session_test_database_url(database_test_url)
    with support.postgres_test_database(url, database_admin_url) as owned:
        owned.restore()
        with owned.engine.connect() as connection:
            for operation in (owned.restore, owned.close):
                with pytest.raises(RuntimeError, match="1 checked-out connections"):
                    operation()
                assert connection.scalar(text("SELECT current_database()")) == url.database
    assert _existing_databases(database_admin_url, [url.database]) == []


def test_independent_connection_is_not_force_closed(database_test_url: URL, database_admin_url: URL) -> None:
    url = support.session_test_database_url(database_test_url)
    with support.postgres_test_database(url, database_admin_url) as owned:
        external = create_engine(url)
        try:
            with external.connect() as connection:
                with pytest.raises(OperationalError, match="being accessed by other users"):
                    owned.restore()
                assert connection.scalar(text("SELECT current_database()")) == url.database
        finally:
            external.dispose()
        owned.restore()


def test_collision_during_clone_is_never_adopted_or_removed(
    database_test_url: URL, database_admin_url: URL, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = support.session_test_database_url(database_test_url)
    create = support.create_test_database
    collision_created = False

    def race_create(target_url: URL, admin_url: URL, *, template_url: URL | None = None) -> None:
        nonlocal collision_created
        if template_url is not None:
            create(target_url, admin_url)
            collision_created = True
        create(target_url, admin_url, template_url=template_url)

    try:
        with support.postgres_test_database(url, database_admin_url) as owned:
            monkeypatch.setattr(support, "create_test_database", race_create)
            with pytest.raises(ProgrammingError, match="already exists"):
                owned.restore()
            with pytest.raises(RuntimeError, match="not owned"):
                owned.restore()
        assert _existing_databases(database_admin_url, [url.database]) == [url.database]
    finally:
        if collision_created:
            support.drop_test_database(url, database_admin_url)
