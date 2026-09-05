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