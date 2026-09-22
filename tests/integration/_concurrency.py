"""Shared harness for tests that need two or more DB transactions to race
against each other on purpose (order checkout stock, lottery draw locking,
...). Not a test module itself — no test_*/​*_test name, so pytest won't
collect it, only import it from the actual test files under
tests/integration/marketplace and tests/integration/events.

Threads, not asyncio: the app's DB layer (app/db/session.py) and the
TestClient used across the integration suite are both synchronous, so real
OS threads blocking on real Postgres locks are what actually reproduces a
race here. Each thread gets its own SQLAlchemy Session (either via
FastAPI's per-request Depends(get_db) when going through TestClient, or via
db_session() below when calling a service function directly) and therefore
its own pooled connection — see session.py's pool_pre_ping engine, default
pool_size=5 / max_overflow=10, comfortable for the small thread counts these
tests use (stay in single digits unless that pool config changes too).
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable

from app.db.session import session as SessionLocal


@contextmanager
def db_session():
    """A raw Session for seeding fixtures / asserting on final DB state —
    same sessionmaker the app itself uses, not a mock. Commits are the
    caller's responsibility; this only guarantees the session is closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@dataclass
class ThreadOutcome:
    """One racer's result. Exactly one of result/exception is set once the
    thread finishes — never both, never neither."""
    result: object = None
    exception: BaseException | None = None

    @property
    def succeeded(self) -> bool:
        return self.exception is None


def run_concurrently(fns: list[Callable[[], object]]) -> list[ThreadOutcome]:
    """Run every callable in `fns` in its own thread, all released from a
    shared threading.Barrier at (as close to) the same instant as the
    scheduler allows — so they actually contend for the same locked rows
    instead of running serially by accident, which is the failure mode that
    would let a broken implementation pass a concurrency test for free.

    Each fn's exception is captured on its own ThreadOutcome instead of
    propagating — a losing racer is EXPECTED to raise (InsufficientStockError,
    BadRequestError, a 4xx response, ...), and letting that exception kill
    the thread pool would stop you from inspecting what the winning racer(s)
    did. Assert on the returned outcomes yourself:

        outcomes = run_concurrently([lambda: checkout_as(u1), lambda: checkout_as(u2)])
        successes = [o for o in outcomes if o.succeeded]
        failures = [o for o in outcomes if not o.succeeded]
        assert len(successes) == 1
        assert isinstance(failures[0].exception, SomeExpectedError)  # or check a response status

    fn itself decides what "result" means — return a requests/httpx Response
    from a TestClient call, or a Model instance from a direct service call,
    whatever the test needs to assert on afterwards.
    """
    if len(fns) < 2:
        raise ValueError("run_concurrently needs at least 2 callables to produce a race")

    barrier = threading.Barrier(len(fns))
    outcomes = [ThreadOutcome() for _ in fns]

    def _run(index: int, fn: Callable[[], object]) -> None:
        barrier.wait()  # every thread blocks here until all of them have arrived
        try:
            outcomes[index].result = fn()
        except BaseException as e:  # noqa: BLE001 — deliberately broad, see docstring
            outcomes[index].exception = e

    with ThreadPoolExecutor(max_workers=len(fns)) as pool:
        futures = [pool.submit(_run, i, fn) for i, fn in enumerate(fns)]
        for future in futures:
            future.result()  # re-raises only if _run's own plumbing (not fn) blew up

    return outcomes
