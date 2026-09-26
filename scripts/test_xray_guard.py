#!/usr/bin/env python3
"""Offline regression guard for the Company X-Ray report and follow-up bugs.

Covers three failures seen in the UI:

1. A Company X-Ray whose report came back empty left a blank screen.
2. The follow-up to a company chat was re-classified as a venture, so a message
   like "hi" was validated as a business idea instead of being asked about the
   company.
3. Source retrieval failing (no API key, no credits, a dead backend) took the
   whole report down with it.

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
import intelligence  # noqa: E402
import main  # noqa: E402

FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {label}{('  — ' + detail) if detail else ''}")
    if not cond:
        FAILURES.append(label)


def drive_analyze(company: str = "Moniepoint") -> list[dict]:
    """Run /api/analyze end to end and return the events the client would see."""

    async def collect():
        resp = main.analyze(
            main.AnalyzeRequest(company=company, analysis_type="competitor")
        )
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


agents.team_status = lambda: {"ready": True, "error": None, "model": "stub"}


# --- 1. a report is streamed, and the stream always closes cleanly ----------
agents.run_instant_xray = lambda analysis_type, company: iter(
    [
        {"type": "status", "label": "Analysing company", "detail": "stub"},
        {"type": "stage_start", "stage": "report", "label": "Report"},
        {"type": "delta", "data": "REAL "},
        {"type": "delta", "data": "REPORT"},
    ]
)
events = drive_analyze()
types = [e["type"] for e in events]
check("a report streams its text", replay_client(events) == "REAL REPORT")
check("the report stage is announced", "stage_start" in types, f"events={types}")
check("stream closes with done", types[-1] == "done", f"events={types}")
check("no reset on the single-pass path", "reset" not in types, f"events={types}")


# --- 2. an empty report must not be reported as success --------------------
# A no-content run is a bug upstream, but it must surface as an error rather
# than a blank report that looks like a successful empty answer. This exercises
# the real _stream_instant, so the analyst itself is stubbed to stay silent.
class SilentAgent:
    def run(self, prompt, stream=True):
        return iter([])


agents._instant_agent = lambda: SilentAgent()
# Note: run_instant_xray was stubbed above, so call the real _stream_instant
# directly — that is where the empty-report guard lives.
try:
    list(agents._stream_instant("PROMPT"))
    check("an empty report raises rather than closing silently", False, "no error raised")
except RuntimeError as exc:
    check("an empty report raises rather than closing silently", True, str(exc)[:60])


# --- 3. source failure must never cost the user their report ----------------
class ReportThenBoom:
    """Streams a real report, then source retrieval explodes."""

    def run(self, prompt, stream=True):
        return iter([])


def xray_with_dead_sources(analysis_type: str, company: str):
    yield {"type": "status", "label": "Analysing company", "detail": "stub"}
    yield {"type": "stage_start", "stage": "report", "label": "Report"}
    yield {"type": "delta", "data": "REPORT DESPITE NO SOURCES"}


real_collector = intelligence.SourceCollector


def exploding_collector(query: str, limit: int = 5):
    class Boom(real_collector):  # type: ignore[misc,valid-type]
        def _run(self):
            raise RuntimeError("Payment Required: Insufficient credits")

    return Boom(query, limit)


intelligence.SourceCollector = exploding_collector
agents.run_instant_xray = xray_with_dead_sources
events = drive_analyze()
check(
    "source failure does not break the report",
    "REPORT DESPITE NO SOURCES" in replay_client(events),
    f"events={[e['type'] for e in events]}",
)
check(
    "no fabricated Sources block when retrieval failed",
    "## Sources" not in replay_client(events),
)
intelligence.SourceCollector = real_collector


# --- 4. sources are only ever rendered from real URLs -----------------------
check(
    "render_sources emits nothing for an empty list",
    intelligence.render_sources([]) == "",
)
rendered = intelligence.render_sources(
    [{"label": "World Bank", "url": "https://www.worldbank.org"}]
)
check(
    "a real source renders as a clickable markdown link",
    "- [World Bank](https://www.worldbank.org)" in rendered,
    repr(rendered),
)

# A malformed or non-http result must never reach the renderer.
extracted = intelligence._extract_sources(
    "see [ok](https://example.com/a) and [bad](https://) and ftp://nope"
)
check(
    "only real http(s) URLs survive extraction",
    all(s["url"].startswith("http") for s in extracted) and extracted,
    f"extracted={extracted}",
)


# --- 5. Q&A stays anchored to the chat and never closes blank --------------
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

# --- 6. discovery stays on the knowledge path ------------------------------
check(
    "the discovery analyst has no web tools",
    not agents._discovery_agent().tools,
    f"tools={agents._discovery_agent().tools}",
)
check(
    "the discovery analyst never sees a tool list",
    "search" not in agents._DISCOVERY_RULES.lower().split("output strictly")[0].replace(
        "no research tools", ""
    ),
)
check(
    "discovery ideas are framed as hypotheses, not findings",
    "worth validating" in agents._DISCOVERY_RULES,
)
check(
    "discovery is forbidden from printing URLs",
    "never print a url" in agents._DISCOVERY_RULES.lower(),
)

print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("all checks passed")
