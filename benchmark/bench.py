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
    "cached_reads": [
        # TODO: {"method": "GET", "path": "/products/all"},
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
class Results:
    latencies_ms: list[float] = field(default_factory=list)
    status_counts: dict[int, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def record(self, status: int, elapsed_ms: float) -> None:
        self.latencies_ms.append(elapsed_ms)
        self.status_counts[status] = self.status_counts.get(status, 0) + 1

    def summary(self) -> dict:
        # TODO: handle the empty-latencies case (no requests completed)
        sorted_lat = sorted(self.latencies_ms)
        return {
            "count": len(sorted_lat),
            "p50": statistics.quantiles(sorted_lat, n=100)[49] if sorted_lat else None,
            "p90": statistics.quantiles(sorted_lat, n=100)[89] if sorted_lat else None,
            "p99": statistics.quantiles(sorted_lat, n=100)[98] if sorted_lat else None,
            "max": sorted_lat[-1] if sorted_lat else None,
            "status_counts": self.status_counts,
            "errors": len(self.errors),
        }


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
    # TODO:
    #   while time.monotonic() < stop_at:
    #       for step in scenario:
    #           async with semaphore:
    #               start = time.perf_counter()
    #               resp = await client.request(step["method"], step["path"], ...)
    #               elapsed_ms = (time.perf_counter() - start) * 1000
    #               results.record(resp.status_code, elapsed_ms)
    raise NotImplementedError


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
    # TODO: dump per-request rows (timestamp, status, latency_ms) instead of
    # just latencies, if you want to plot latency-over-time later.
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["latency_ms"])
        for lat in results.latencies_ms:
            writer.writerow([lat])


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
    print(f"p50/p90/p99:  {summary['p50']:.1f} / {summary['p90']:.1f} / {summary['p99']:.1f} ms")
    print(f"max:          {summary['max']:.1f} ms")
    print(f"status codes: {summary['status_counts']}")
    print(f"errors:       {summary['errors']}")

    if args.csv_out:
        write_csv(results, args.csv_out)
        print(f"raw latencies written to {args.csv_out}")


if __name__ == "__main__":
    main()
