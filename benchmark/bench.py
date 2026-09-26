"""Load-test / benchmark tool for the i-dolly API.

Usage (once implemented):
    python benchmark/bench.py --scenario cached_reads --concurrency 50 --duration 30

Design: see the conversation plan — three scenario tiers (cached reads,
auth+lock-contention writes, rate-limit burst), asyncio.Semaphore-gated
worker pool sharing one httpx.AsyncClient, percentiles computed at the end.
Everything below is scaffolding — fill in the TODOs yourself.
"""

import argparse
import asyncio
import csv
import statistics
import time
from dataclasses import dataclass, field

import httpx

BASE_URL = "http://localhost:8000"  # TODO: make overridable via --base-url


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------
# TODO: replace this stub with real scenarios. Each scenario is a list of
# requests a single virtual user performs in a loop. Keep weights/payloads
# here for now; split into YAML files under benchmark/scenarios/ later if
# this grows unwieldy.
#
# Suggested tiers (see plan):
#   - cached_reads:   GET /products/all, GET /concerts/{id}/detail, etc.
#   - auth_writes:    POST /account/login once, then POST /tickets/checkout
#                      against a low-stock seeded ticket_type (lock-contention
#                      proof — successful checkouts must not exceed stock).
#   - rate_limit:     hammer one route past its known limit/window, count 429s.
SCENARIOS: dict[str, list[dict]] = {
    # Worked example: GET /products/store-page is Redis-cached (5 min TTL)
    # but also rate_limit(5, 60, ip_key)-gated — 5 requests/60s per IP. Run
    # this with --concurrency 1 --duration <10s so you stay under that
    # budget and measure cache-hit latency, not the limiter. See the
    # "rate_limit" scenario below for deliberately exceeding it instead.
    "product_store": [
        {"method": "GET", "path": "/products/store-page"},
    ],
    "cached_reads": [
        
    ],
    "auth_writes": [
        # TODO
    ],
    "rate_limit": [
        # TODO
    ],
}


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------
@dataclass
class RequestRecord:
    timestamp: float  # time.time(), for the CSV / "when did the slow one happen" question
    status: int
    latency_ms: float


def _percentiles(sorted_data: list[float]) -> dict:
    return {
        "count": len(sorted_data),
        "p50": _percentile(sorted_data, 50),
        "p90": _percentile(sorted_data, 90),
        "p99": _percentile(sorted_data, 99),
        "max": sorted_data[-1] if sorted_data else None,
    }


@dataclass
class Results:
    records: list[RequestRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def record(self, status: int, elapsed_ms: float) -> None:
        self.records.append(RequestRecord(time.time(), status, elapsed_ms))

    def summary(self) -> dict:
        # Blended (all statuses together) — kept for a quick glance, but see
        # per_status below: a run mixing 200s and 429s makes this number mostly
        # meaningless (see docs/project_status.md item 40 for why this split
        # exists — a blended p99 couldn't tell a slow rejection from a slow
        # cache-miss apart).
        overall = sorted(r.latency_ms for r in self.records)

        by_status: dict[int, list[float]] = {}
        for r in self.records:
            by_status.setdefault(r.status, []).append(r.latency_ms)

        return {
            **_percentiles(overall),
            "status_counts": {status: len(lats) for status, lats in by_status.items()},
            "per_status": {
                status: _percentiles(sorted(lats)) for status, lats in by_status.items()
            },
            "errors": len(self.errors),
        }


def _percentile(sorted_data: list[float], pct: float) -> float | None:
    """Nearest-rank percentile. statistics.quantiles(n=100) misbehaves with
    small samples (e.g. 5 requests against a 5/60s rate-limited route) —
    this stays correct at any sample size, which matters more here than
    interpolation precision."""
    if not sorted_data:
        return None
    index = max(0, int(round(pct / 100 * len(sorted_data))) - 1)
    return sorted_data[min(index, len(sorted_data) - 1)]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
async def login(client: httpx.AsyncClient, email: str, password: str) -> str:
    """Log in once per virtual user, return the access token."""
    # TODO: POST /account/login, extract and return the access token.
    # Reuse this token for every subsequent request from the same worker —
    # do not log in per-request (you'll trip the login route's rate limit).
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
async def worker(
    worker_id: int,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    scenario: list[dict],
    stop_at: float,
    results: Results,
    token: str | None = None,
) -> None:
    """Loop through the scenario's requests until stop_at, gated by semaphore."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    while time.monotonic() < stop_at:
        for step in scenario:
            async with semaphore:
                start = time.perf_counter()
                try:
                    resp = await client.request(
                        step["method"], step["path"], headers=headers
                    )
                    elapsed_ms = (time.perf_counter() - start) * 1000
                    results.record(resp.status_code, elapsed_ms)
                except httpx.HTTPError as exc:
                    # Network-level failure (timeout, connection reset) —
                    # distinct from a 4xx/5xx response, which still counts
                    # via results.record above.
                    results.errors.append(str(exc))


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
async def run_scenario(
    scenario_name: str,
    concurrency: int,
    duration: float,
    base_url: str,
) -> Results:
    scenario = SCENARIOS[scenario_name]
    results = Results()
    semaphore = asyncio.Semaphore(concurrency)
    stop_at = time.monotonic() + duration

    # TODO: size max_connections >= concurrency so the pool itself isn't
    # the bottleneck you end up measuring.
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)

    async with httpx.AsyncClient(base_url=base_url, limits=limits, timeout=10.0) as client:
        # TODO: if this scenario needs auth, call login() once per worker
        # (or once total, if all workers can share a token) before spawning.
        tasks = [
            worker(i, client, semaphore, scenario, stop_at, results)
            for i in range(concurrency)
        ]
        await asyncio.gather(*tasks)

    return results


def write_csv(results: Results, path: str) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "status", "latency_ms"])
        for r in results.records:
            writer.writerow([r.timestamp, r.status, r.latency_ms])


def main() -> None:
    parser = argparse.ArgumentParser(description="i-dolly API benchmark tool")
    parser.add_argument("--scenario", required=True, choices=list(SCENARIOS))
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--duration", type=float, default=30.0, help="seconds")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--csv-out", default=None)
    args = parser.parse_args()

    # TODO: seed data first (scripts/seed.py) so the ids this scenario hits
    # are deterministic across runs.

    results = asyncio.run(
        run_scenario(args.scenario, args.concurrency, args.duration, args.base_url)
    )

    summary = results.summary()
    print(f"\n=== {args.scenario} ===")
    print(f"requests:     {summary['count']}")
    if summary["count"]:
        print(f"blended p50/p90/p99: {summary['p50']:.1f} / {summary['p90']:.1f} / {summary['p99']:.1f} ms  (max {summary['max']:.1f} ms)")
    print(f"status codes: {summary['status_counts']}")
    print("per-status latency:")
    for status, stats in sorted(summary["per_status"].items()):
        if stats["count"]:
            print(
                f"  {status}: n={stats['count']:<5} "
                f"p50/p90/p99 = {stats['p50']:.1f} / {stats['p90']:.1f} / {stats['p99']:.1f} ms  "
                f"(max {stats['max']:.1f} ms)"
            )
    print(f"errors:       {summary['errors']}")

    if args.csv_out:
        write_csv(results, args.csv_out)
        print(f"raw latencies written to {args.csv_out}")


if __name__ == "__main__":
    main()
