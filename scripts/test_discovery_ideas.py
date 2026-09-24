#!/usr/bin/env python3
"""Offline checks for the discovery scan.

Covers the two behaviours that matter for the Discover page:

1. Ideas are emitted as soon as each one is written, not once the whole scan
   finishes — so cards (and their validate buttons) appear while the agent is
   still searching.
2. A scan never yields more than DISCOVERY_MAX_IDEAS ideas.

The discovery agent is stubbed, so this makes no provider calls and spends no
API quota. Exits non-zero if any check fails.
"""
import os
import sys

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
sys.path.insert(0, os.path.normpath(BACKEND))

from agno.run.agent import RunContentEvent  # noqa: E402

import agents  # noqa: E402

FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {label}{('  — ' + detail) if detail else ''}")
    if not cond:
        FAILURES.append(label)


class FakeDiscoveryAgent:
    """Streams pre-written chunks, one per simulated model turn."""

    def __init__(self, chunks: list[str]):
        self._chunks = chunks

    def run(self, prompt, stream=True):
        return iter([RunContentEvent(content=c) for c in self._chunks])


def install(chunks: list[str]) -> None:
    agents._discovery_agent = lambda: FakeDiscoveryAgent(chunks)


def scan() -> list[dict]:
    return list(agents.run_discovery(""))


def idea_text(n: int) -> str:
    return (
        f"### Idea {n}\n"
        f"idea: Start venture number {n} in Lagos\n"
        f"why: Demand for number {n} rose sharply this year.\n\n"
    )


# Split into small pieces so blocks complete part-way through the stream.
def chunked(text: str, size: int = 30) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


# --- helpers ---------------------------------------------------------------
finished, tail = agents._split_idea_blocks("### A\nidea: x\n### B\nidea: y\n")
check("helper: trailing block stays open", len(finished) == 1 and tail.strip().startswith("B"))
check(
    "helper: a block without an 'idea:' line is rejected",
    agents._parse_idea_block("just some prose\nno marker") is None,
)

# --- a six-idea scan yields four, progressively ----------------------------
install(chunked("".join(idea_text(n) for n in range(1, 7))))
events = scan()
types = [e["type"] for e in events]
ideas = [e for e in events if e["type"] == "idea"]

check("scan is capped at DISCOVERY_MAX_IDEAS", agents.DISCOVERY_MAX_IDEAS == 4, str(agents.DISCOVERY_MAX_IDEAS))
check("six-idea scan emits exactly four", len(ideas) == 4, f"got {len(ideas)}")
check("stream closes with done", types[-1] == "done")

first_idea = types.index("idea")
last_delta = len(types) - 1 - types[::-1].index("delta")
check(
    "ideas arrive before the stream ends (progressive, not batched)",
    first_idea < last_delta,
    f"first idea at {first_idea}, last delta at {last_delta}",
)

check(
    "ideas are parsed in order",
    [i["title"] for i in ideas] == ["Idea 1", "Idea 2", "Idea 3", "Idea 4"],
    str([i["title"] for i in ideas]),
)
check(
    "each idea carries prompt + rationale",
    all(i["prompt"].strip() and i["rationale"].strip() for i in ideas),
    str(ideas[0]),
)
check(
    "prompts are the runnable one-liners",
    ideas[0]["prompt"] == "Start venture number 1 in Lagos",
    ideas[0]["prompt"],
)
check("no duplicate ideas", len({i["prompt"] for i in ideas}) == len(ideas))

# --- a short scan still flushes its final block ----------------------------
install(chunked(idea_text(1) + idea_text(2)))
short = [e for e in scan() if e["type"] == "idea"]
check(
    "final block is flushed even with no closing header",
    [i["title"] for i in short] == ["Idea 1", "Idea 2"],
    str([i["title"] for i in short]),
)

# --- a scan that drifts from the format still yields usable ideas ----------
install(["### Off-format\n", "idea: Something valid in Abuja\nwhy: Signals found.\n"])
fallback = [e for e in scan() if e["type"] == "idea"]
check(
    "off-format single block still parses",
    len(fallback) == 1 and fallback[0]["prompt"] == "Something valid in Abuja",
    str(fallback),
)

print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("all checks passed")
