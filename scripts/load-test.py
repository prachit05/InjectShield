#!/usr/bin/env python3
"""Flood the scan queue through the API to show the workers scaling out and back in.

    BASE_URL=https://<cloudfront-domain> TOKEN=$(scripts/token.sh you@example.com) \
        python3 scripts/load-test.py --count 500

    python3 scripts/load-test.py --count 50          # local docker compose (AUTH_DISABLED)

Submits --count prompts drawn from tests/sample_prompts with --concurrency threads,
then (unless --no-wait) polls every job until it is done or failed and prints the
submit rate, end-to-end latency percentiles and the label mix. Watch the dashboard's
"Scan queue depth" and "Running tasks" widgets while it runs. Standard library only.

The ID token lasts an hour; for a longer test fetch a new one between runs.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "tests" / "sample_prompts"


def load_prompts() -> list[dict]:
    prompts = []
    for path in sorted(SAMPLES.glob("*.txt")):
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            prompt, _, context = line.partition("|||")
            body = {"prompt": prompt.strip()}
            if context.strip():
                body["context"] = context.strip()
            prompts.append(body)
    if not prompts:
        sys.exit(f"no prompts found in {SAMPLES}")
    return prompts


class Client:
    def __init__(self, base_url: str, token: str | None, timeout: float = 15):
        if not base_url.startswith(("http://", "https://")):
            sys.exit(f"--base-url must start with http:// or https:// (got {base_url!r})")
        self.base_url = base_url.rstrip("/")
        self.headers = {"Content-Type": "application/json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        self.timeout = timeout

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        # Scheme checked in __init__, so only http(s) URLs reach urlopen.
        request = urllib.request.Request(self.base_url + path, data=data, method=method, headers=self.headers)  # noqa: S310
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as err:
            return err.code, {}
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            return 0, {}


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://localhost:8000"))
    parser.add_argument("--token", default=os.environ.get("TOKEN"), help="Cognito ID token (or TOKEN env var)")
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--no-wait", action="store_true", help="submit only; do not wait for verdicts")
    parser.add_argument("--timeout", type=int, default=900, help="seconds to wait for all verdicts")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    client = Client(args.base_url, args.token)
    status, _ = client.call("GET", "/health")
    if status != 200:
        sys.exit(f"health check failed at {args.base_url} (status {status})")

    prompts = load_prompts()
    rng = random.Random(args.seed)  # noqa: S311 (sampling test prompts, not security)
    bodies = [rng.choice(prompts) for _ in range(args.count)]

    print(f"submitting {args.count} scans to {args.base_url} with {args.concurrency} threads")
    started = time.perf_counter()
    with ThreadPoolExecutor(args.concurrency) as pool:
        submitted = list(pool.map(lambda body: client.call("POST", "/scan", body), bodies))
    submit_seconds = time.perf_counter() - started

    statuses = Counter(code for code, _ in submitted)
    job_ids = [body["job_id"] for code, body in submitted if code == 202]
    print(f"submitted {len(job_ids)}/{args.count} in {submit_seconds:.1f}s ({len(job_ids) / submit_seconds:.1f}/s)")
    if statuses.keys() - {202}:
        print(f"  non-202 responses: {dict((k, v) for k, v in statuses.items() if k != 202)}")
        if 401 in statuses:
            print("  401: token missing or expired (scripts/token.sh gives a fresh one)")
    if args.no_wait or not job_ids:
        return 0 if job_ids else 1

    pending = set(job_ids)
    finished: dict[str, dict] = {}
    deadline = time.monotonic() + args.timeout
    last_report = 0.0
    while pending and time.monotonic() < deadline:
        batch = list(pending)
        with ThreadPoolExecutor(args.concurrency) as pool:
            results = list(pool.map(lambda job_id: (job_id, client.call("GET", f"/result/{job_id}")), batch))
        for job_id, (code, body) in results:
            if code == 200 and body.get("status") in ("done", "failed"):
                finished[job_id] = body
                pending.discard(job_id)
        if time.monotonic() - last_report > 10:
            print(f"  {len(finished)}/{len(job_ids)} finished, {len(pending)} waiting")
            last_report = time.monotonic()
        if pending:
            time.sleep(2)

    done = [r for r in finished.values() if r["status"] == "done"]
    failed = [r for r in finished.values() if r["status"] == "failed"]
    latencies = [
        (parse_time(r["updated_at"]) - parse_time(r["created_at"])).total_seconds()
        for r in done
        if r.get("created_at") and r.get("updated_at")
    ]
    labels = Counter(r["verdict"]["label"] for r in done if r.get("verdict"))
    total_seconds = time.perf_counter() - started

    print()
    print(f"finished {len(finished)}/{len(job_ids)} in {total_seconds:.0f}s: {len(done)} done, {len(failed)} failed")
    if pending:
        print(f"  {len(pending)} still waiting after {args.timeout}s")
    if latencies:
        print(
            "submit to verdict: "
            f"p50 {percentile(latencies, 50):.1f}s  p95 {percentile(latencies, 95):.1f}s  "
            f"max {max(latencies):.1f}s  mean {statistics.fmean(latencies):.1f}s"
        )
        print(f"throughput: {len(done) / total_seconds:.1f} verdicts/s")
    if labels:
        print("labels: " + ", ".join(f"{label} {count}" for label, count in labels.most_common()))
    return 0 if not pending and not failed else 1


if __name__ == "__main__":
    sys.exit(main())
