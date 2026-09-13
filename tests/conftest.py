import os
from dotenv import load_dotenv
from sqlalchemy.engine import make_url

# Redirects every test in this session onto a dedicated "<name>_test"
# database instead of whatever DATABASE_URL points the real app at —
# tests/integration/conftest.py recreates and migrates it from scratch
# every run. This has to happen HERE, as the very first thing executed in
# the whole test session, before anything imports app.config.settings:
# that module reads DATABASE_URL once, at its own first import, and caches
# the resulting Settings object for the rest of the process — the
# patch(...) call a few lines down already triggers exactly that (it
# imports app.cache.redis_client, which imports app.config.settings), so
# this can't be deferred into a subdirectory conftest.py.
#
# load_dotenv() first because app.config.settings.Settings reads DATABASE_URL
# via pydantic-settings' env_file=".env" — which pulls straight from the
# .env FILE, not os.environ — so outside Docker (no docker-compose env_file
# injection) os.environ["DATABASE_URL"] alone would KeyError even though
# Settings() itself would resolve fine. load_dotenv() never overrides an
# already-set env var, so this is a no-op inside the container, where
# docker-compose already injected it directly.
#
# Deliberately just a string rewrite past that — no connection is attempted
# here, so `pytest tests/unit` (which never touches a real database) keeps
# working with no live Postgres reachable at all, matching this project's
# standing verification fallback (docs/project_status.md §3). The original
# URL is stashed in _ORIGINAL_DATABASE_URL for tests/integration/conftest.py's
# own fixture, which is the one that actually needs to connect (to create
# the test database from an admin connection, then migrate it).
load_dotenv()
_original_url = make_url(os.environ["DATABASE_URL"])
# str(URL) renders with the password hidden (hide_password=True is the
# default, specifically to keep it out of logs/tracebacks) — need the real
# thing here since these are live connection strings, not something printed.
os.environ["_ORIGINAL_DATABASE_URL"] = _original_url.render_as_string(hide_password=False)
_test_url = _original_url.set(database=f"{_original_url.database}_test")
os.environ["DATABASE_URL"] = _test_url.render_as_string(hide_password=False)

import fakeredis
from unittest.mock import patch

# Every test file in here imports individual services/schemas lazily, inside
# each test function, rather than the app's full router tree (main.py) — so
# unlike the real app, nothing guarantees every model has been imported
# before the first ORM class gets instantiated. SQLAlchemy resolves
# string-based relationship() targets (e.g. Users.cart = relationship("Cart", ...))
# against whatever's been imported by the time mapper configuration is
# triggered, so whichever test runs first can fail with "failed to locate a
# name" purely based on import order — see app/db/base.py's own comment for
# the same failure mode. Importing it here (for its side effects) once, before
# any test runs, makes every model resolvable regardless of test order.
import app.db.base  # noqa: F401

fake_redis = fakeredis.FakeRedis(decode_responses=False)
patch("app.cache.redis_client.redis_client", fake_redis).start()