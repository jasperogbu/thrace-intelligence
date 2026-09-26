#!/usr/bin/env python3
"""Latency benchmark for the three intelligence features.

Measures the phases the fast path actually has, separately, so optimisation
targets the real bottleneck instead of a guess:

    request -> model start -> first token -> last token
            -> sources attached -> done

Usage:
    python scripts/bench_intelligence.py                 # all three, 1 run each
    python scripts/bench_intelligence.py venture xray     # a subset
    python scripts/bench_intelligence.py --repeat 3

Each phase is timed from a single monotonic clock, so source-retrieval time is
reported separately from model time rather than being folded into the total.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
sys.path.insert(0, os.path.normpath(BACKEND))
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(".env")

import agents  # noqa: E402

# Representative real inputs, not lorem ipsum.
CASES = {
    "venture": (
        "I want to build an AI-powered marketplace for Nigerian farmers.",
        lambda: agents.run_instant_venture(
            "I want to build an AI-powered marketplace for Nigerian farmers."
        ),
    ),
    "xray": ("Paystack", lambda: agents.run_instant_xray("competitor", "Paystack")),
    "discover": (
        "business opportunities in Nigeria for young people",
        lambda: agents.run_discovery(
            "business opportunities in Nigeria for young people"
        ),
    ),
}


def run_case(name: str) -> dict:
    """Stream one feature end to end, timing every phase."""
    label, factory = CASES[name]
    t0 = time.monotonic()
    model_start = first_token = last_token = sources_at = None
    chars = 0
    sources = 0
    ideas = 0
    error = None

    try:
        for event in factory():
            kind = event.get("type")
            now = time.monotonic()
            if kind == "delta":
                data = event.get("data") or ""
                chars += len(data)
                if model_start is None:
                    model_start = now
                if first_token is None:
                    first_token = now
                last_token = now
                if "## Sources" in data:
                    sources_at = now
            elif kind == "idea":
                ideas += 1
            elif kind == "error":
                error = event.get("message")
    except Exception as exc:  # noqa: BLE001
        # A provider quota failure is a benchmark result, not a crash: record
        # it and keep going so one bad run does not void the whole table.
        error = error or f"{type(exc).__name__}: {exc}"

    end = time.monotonic()
    end = end or t0
    return {
        "feature": name,
        "label": label,
        "ttft": (first_token - t0) if first_token else None,
        "first_to_last": (last_token - first_token) if (last_token and first_token) else None,
        "model_time": (last_token - t0) if last_token else None,
        "source_wait": (end - last_token) if last_token else None,
        "total": end - t0,
        "chars": chars,
        "ideas": ideas,
        "sources": bool(sources_at),
        "error": error,
    }


def fmt(v: float | None) -> str:
    return f"{v:6.2f}s" if isinstance(v, (int, float)) else "     —"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("features", nargs="*", default=[], type=str,
                    help="subset of: " + ", ".join(CASES))
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    names = args.features or list(CASES)
    names = [n for n in names if n in CASES] or list(CASES)

    results: list[dict] = []
    for name in names:
        for _ in range(args.repeat):
            r = run_case(name)
            results.append(r)
            if r["error"]:
                print(f"  {name}: ERROR {r['error'][:80]}", file=sys.stderr)

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    print()
    print(
        f"{'feature':<10} {'TTFT':>8} {'gen':>8} {'model':>8} "
        f"{'src wait':>9} {'total':>8} {'chars':>7} {'src':>4}"
    )
    print("-" * 70)
    for r in results:
        print(
            f"{r['feature']:<10} {fmt(r['ttft'])} {fmt(r['first_to_last'])} "
            f"{fmt(r['model_time'])} {fmt(r['source_wait'])} {fmt(r['total'])} "
            f"{r['chars']:>7} {'yes' if r['sources'] else 'no':>4}"
            f"  {('ERR ' + r['error'][:38]) if r['error'] else ''}"
        )
    print()

    if len(results) > len(names):
        print("means across repeats:")
        for name in names:
            rs = [r for r in results if r["feature"] == name]
            print(
                f"  {name:<10} ttft={statistics.mean(r['ttft'] or 0 for r in rs):.2f}s  "
                f"total={statistics.mean(r['total'] for r in rs):.2f}s  "
                f"chars={statistics.mean(r['chars'] for r in rs):.0f}"
            )
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
