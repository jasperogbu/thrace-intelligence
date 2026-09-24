#!/usr/bin/env python3
"""Offline regression guard for the Company X-Ray report and follow-up bugs.

Covers two failures seen in the UI:

1. A Company X-Ray whose researched report came back empty left a blank screen,
   because the provisional read was dropped before the researched text arrived
   and nothing replaced it.
2. The follow-up to a company chat was re-classified as a venture, so a message
   like "hi" was validated as a business idea instead of being asked about the
   company.

Runs entirely against stubbed agents — no provider calls and no API quota.
Exits non-zero if any check fails.
"""
import asyncio
import json
import os
import sys

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
sys.path.insert(0, os.path.normpath(BACKEND))

import agents  # noqa: E402
import main  # noqa: E402

FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {label}{('  — ' + detail) if detail else ''}")
    if not cond:
        FAILURES.append(label)


def install_stubs(provisional: list[dict], report: list[dict]) -> None:
    agents.team_status = lambda: {"ready": True, "error": None, "model": "stub"}
    agents.xray_provisional = lambda analysis_type, company: iter(provisional)
    agents.run_bullets = lambda analysis_type, company: "stub bullets"
    agents.stream_report = lambda analysis_type, company, bullets: iter(report)


def drive_analyze() -> list[dict]:
    """Run /api/analyze end to end and return the events the client would see."""
    async def collect():
        resp = main.analyze(main.AnalyzeRequest(company="Moniepoint", analysis_type="competitor"))
        events = []
        async for chunk in resp.body_iterator:
            text = chunk if isinstance(chunk, str) else chunk.decode()
            for line in text.split("\n"):
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        return events

    return asyncio.run(collect())


def replay_client(events: list[dict]) -> str:
    """Mirror the client's text buffer: `reset` clears it, `delta` appends."""
    acc = ""
    for event in events:
        if event["type"] == "reset":
            acc = ""
        elif event["type"] == "delta":
            acc += event["data"]
    return acc


# --- 1. an empty researched report must never blank the screen -------------
install_stubs(provisional=[{"type": "delta", "data": "PRELIMINARY READ"}], report=[])
events = drive_analyze()
types = [e["type"] for e in events]
check("empty researched report emits no reset", "reset" not in types, f"events={types}")
check(
    "empty researched report keeps the preliminary read",
    replay_client(events).strip() == "PRELIMINARY READ",
    repr(replay_client(events)),
)
check(
    "empty researched report tells the user research was incomplete",
    any(e["type"] == "status" and e.get("label") == "Research incomplete" for e in events),
)
check("stream still closes with done", types[-1] == "done")

# --- 2. a normal researched report replaces the provisional text -----------
install_stubs(
    provisional=[{"type": "delta", "data": "PRELIMINARY READ"}],
    report=[{"type": "delta", "data": "REAL "}, {"type": "delta", "data": "REPORT"}],
)
events = drive_analyze()
resets = [i for i, e in enumerate(events) if e["type"] == "reset"]
research_start = max(i for i, e in enumerate(events) if e["type"] == "stage_start")
researched = [i for i, e in enumerate(events) if e["type"] == "delta" and i > research_start]
check("exactly one reset", len(resets) == 1)
check(
    "reset precedes the first researched delta",
    bool(resets) and bool(researched) and resets[0] < researched[0],
    f"reset={resets} researched={researched}",
)
check("screen ends with the researched report", replay_client(events) == "REAL REPORT")

# --- 3. Q&A stays anchored to the chat and never closes blank --------------
captured: dict[str, str] = {}


class BlankAgent:
    def run(self, prompt, stream=True):
        captured["prompt"] = prompt
        return iter([])


agents._qa_agent = lambda: BlankAgent()
try:
    list(agents.answer_question("REPORT BODY", "what changed?", "Moniepoint"))
    check("blank answer raises instead of closing empty", False, "no error raised")
except RuntimeError:
    check("blank answer raises instead of closing empty", True)
check("Q&A prompt is anchored to the chat subject", "Moniepoint" in captured.get("prompt", ""))
check("Q&A prompt forbids starting a new analysis", "do not" in captured.get("prompt", ""))

print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("all checks passed")
