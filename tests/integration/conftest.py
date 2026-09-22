import os

import pytest
import sqlalchemy

from alembic import command
from alembic.config import Config
from tests.conftest import fake_redis


def _recreate_test_database() -> None:
    """Drop and recreate the dedicated integration-test database, then
    migrate it to head, so every integration-test run starts from an
    empty, fully-current schema — never the shared dev database
    tests/conftest.py's DATABASE_URL redirect already points away from.

    Runs once, as plain module-level code, the moment pytest loads this
    conftest.py — guaranteed to happen before any test module under
    tests/integration/ is imported (and so before any of them can open a
    real connection), since conftest.py files are always loaded before the
    test modules in their own directory.
    """
    admin_url = os.environ["_ORIGINAL_DATABASE_URL"]
    test_url = sqlalchemy.engine.make_url(os.environ["DATABASE_URL"])
    test_db_name = test_url.database

    # Guard against ever pointing this at the real dev database — the
    # redirect in tests/conftest.py always appends "_test", so this should
    # be unreachable, but DROP DATABASE is irreversible enough to check
    # rather than assume.
    assert test_db_name and test_db_name.endswith("_test"), (
        f"refusing to recreate {test_db_name!r} — doesn't look like a test database"
    )

    admin_engine = sqlalchemy.create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            # WITH (FORCE) (PG13+) disconnects any lingering session from a
            # previous run instead of DROP DATABASE failing on it.
            conn.execute(sqlalchemy.text(f'DROP DATABASE IF EXISTS "{test_db_name}" WITH (FORCE)'))
            conn.execute(sqlalchemy.text(f'CREATE DATABASE "{test_db_name}"'))
    finally:
        admin_engine.dispose()

    # alembic/env.py reads app.config.settings.settings.DATABASE_URL, which
    # already resolves to test_url by now (tests/conftest.py's redirect ran
    # before app.config.settings was ever imported in this process) — no
    # override needed here, just point Config at the repo's real alembic.ini.
    command.upgrade(Config("alembic.ini"), "head")


def _assert_app_session_targets_test_database() -> None:
    """Guard the redirect above actually took effect on the engine the tests
    write through.

    tests/conftest.py rewrites DATABASE_URL, but that only lands if it runs
    before app.config.settings is first imported — and app/db/session.py binds
    its engine once, at ITS first import, from whatever settings resolved to
    then. The concurrency harness (tests/integration/_concurrency.py) seeds
    fixtures straight through that engine, so if the ordering ever breaks,
    the suite silently seeds, races against and mutates the REAL database
    instead of this one. That is not hypothetical: it is how a batch of
    `cat-<uuid>`/`product-<uuid>` rows, racer users and their orders ended up
    in the dev database. Cheap assert, loud failure, right after the point
    where the test database is known to exist.
    """
    from app.db.session import engine

    bound = engine.url.database
    if not (bound and bound.endswith("_test")):
        raise RuntimeError(
            f"app.db.session is bound to {bound!r}, which is not a _test database — "
            "the integration suite would read and write real data. Check that "
            "tests/conftest.py's DATABASE_URL redirect runs before anything imports "
            "app.config.settings."
        )


_recreate_test_database()
_assert_app_session_targets_test_database()


@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Every integration test file needs this identically (rate_limit()'s
    Redis counters would otherwise leak between tests and randomly 429 an
    unrelated later test) — shared here instead of copy-pasted per file."""
    for key in fake_redis.scan_iter("rate:ip:*"):
        fake_redis.delete(key)
    for key in fake_redis.scan_iter("rate:user:*"):
        fake_redis.delete(key)
    yield
