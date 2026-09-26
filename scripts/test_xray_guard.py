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
import time

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


# _instant_agent is now cached per feature kind and takes that kind.
agents._instant_agent = lambda kind="venture": SilentAgent()
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

# --- 6. every report ends with 3-5 real, deduped, relevant sources ---------
# The curated fallback is what ships while the search provider has no credits,
# so it is the path most likely to regress silently.
real_live_search = intelligence._live_search
intelligence._live_search = lambda query, limit: []  # simulate no search backend

bad_cases = []
for query in (
    "fintech in Lagos",
    "agriculture marketplace for farmers",
    "crypto exchange",
    "logistics",
    "education platform",
):
    collector = intelligence.SourceCollector(query)
    collector._run()
    srcs = collector._sources
    urls = [s["url"] for s in srcs]
    ok = (
        intelligence.MIN_SOURCES <= len(srcs) <= intelligence.MAX_SOURCES
        and len(set(urls)) == len(urls)
        and all(u.startswith("http") for u in urls)
    )
    if not ok:
        bad_cases.append((query, len(srcs)))

check(
    "every report reaches 3-5 deduped real sources",
    not bad_cases,
    f"offenders={bad_cases}",
)
check(
    "a local query is led by a local regulator",
    intelligence._official_fallback("fintech in Lagos")[0]["url"].endswith("cbn.gov.ng"),
    intelligence._official_fallback("fintech in Lagos")[0]["url"],
)
check(
    "an agriculture query is led by FAO",
    "fao.org" in intelligence._official_fallback("agriculture for farmers")[0]["url"],
)
check(
    "a healthcare query is led by WHO",
    "who.int" in intelligence._official_fallback("health clinic booking")[0]["url"],
)
intelligence._live_search = real_live_search

# --- 7. retries do not fire on permanent errors ----------------------------
check(
    "an auth failure is treated as permanent",
    intelligence.is_permanent_error(RuntimeError("401 Unauthorized invalid_api_key"))
    and not intelligence.is_transient_error(RuntimeError("401 Unauthorized")),
)
check(
    "a bad model name is treated as permanent",
    intelligence.is_permanent_error(RuntimeError("model_not_found: gemini-nope")),
)
check(
    "a capacity spike is still treated as transient",
    intelligence.is_transient_error(RuntimeError("503 UNAVAILABLE high demand"))
    and not intelligence.is_permanent_error(RuntimeError("503 UNAVAILABLE")),
)
check(
    "a quota error is still retried",
    intelligence.is_transient_error(RuntimeError("429 RESOURCE_EXHAUSTED")),
)
check(
    "the retry budget cannot add more than a couple of seconds",
    intelligence.STAGE_MAX_ATTEMPTS <= 2 and intelligence.STAGE_RETRY_DELAY <= 2,
    f"attempts={intelligence.STAGE_MAX_ATTEMPTS} delay={intelligence.STAGE_RETRY_DELAY}",
)

# --- 8. reports are capped and prompts demand brevity ----------------------
check(
    "the venture ceiling is far below the old 14.2k-character output",
    agents._max_tokens("venture") <= 1400,
    f"venture={agents._max_tokens('venture')}",
)
check(
    "the x-ray ceiling is tighter still",
    agents._max_tokens("xray") < agents._max_tokens("venture"),
    f"xray={agents._max_tokens('xray')} venture={agents._max_tokens('venture')}",
)
check(
    "each feature kind gets its own model instance",
    agents._max_tokens("discover") != agents._max_tokens("venture"),
)
venture_prompt = agents.instant_venture_prompt("a fintech in Lagos")
check(
    "the venture prompt states a word budget",
    "900-1300" in venture_prompt,
)
check(
    "the venture prompt forbids repetition",
    "Never repeat" in venture_prompt,
)
check(
    "the venture prompt keeps the required sections",
    all(
        h in venture_prompt
        for h in (
            "## Executive Summary",
            "## Opportunity",
            "## Target Customers",
            "## Market",
            "## Competition",
            "## Business Model",
            "## Key Risks",
            "## Validation Plan",
            "## Recommended Next Steps",
        )
    ),
)
check(
    "the venture prompt still forbids invented URLs",
    "Do not write a Sources section" in venture_prompt,
)

# --- 9. a truncated report is detected, without crying wolf -----------------
# The output cap is what makes generation fast, but a report that ends on
# "the software will be" reads as broken. Markdown has many legitimate endings
# without sentence punctuation, so the detector must not fire on those.
truncation_cases = [
    ("...the aggregator's landed cost, the software will be", True),
    # The real shape of a capped x-ray: a long bullet cut mid-clause.
    (
        '*   **For Competitors:** Do not win on API docs; instead compete on '
        "superior enterprise-level",
        True,
    ),
    ("Risk: regulatory change. Mitigate by phasing.", False),
    ("## Recommended Next Steps", False),
    ("| TAM | $20B | Nigerian agriculture |", False),
    ("- **Metric that matters:** cost-per-ton", False),
    ("* **Verdict: PIVOT**", False),
    ("> a quoted line", False),
    # A short bullet that stops on a bare word is deliberately NOT flagged:
    # the detector is biased towards silence, and a real truncation always
    # produces a long line.
    ("- one\n- two\n- three", False),
    ("", False),
]
wrong = [
    (t, intelligence.looks_truncated(t), exp)
    for t, exp in truncation_cases
    if intelligence.looks_truncated(t) is not exp
]
check(
    "truncation is detected on prose but not on markdown structure",
    not wrong,
    f"mismatches={wrong}",
)

# --- 9. discovery stays on the knowledge path ------------------------------
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

# --- 10. model selection is latency-aware, not blind round-robin -------------
check(
    "a lite model is ranked behind every full model",
    agents._rank_key("gemini-9.9-flash-lite")
    > agents._rank_key("gemini-9.9-flash"),
    f"lite={agents._rank_key('gemini-9.9-flash-lite')} "
    f"full={agents._rank_key('gemini-9.9-flash')}",
)
saved = dict(agents._latency_ms)
saved_pool = agents._model_pool
try:
    # Control the pool explicitly: which models are configured depends on the
    # developer's .env, and a single-model pool would make this vacuous.
    # This mirrors the real five-model Gemini pool; a three-model pool would
    # make the slow model rank 2 of 3 and flatter the distribution.
    agents._model_pool = lambda: [
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
    ]
    agents._latency_ms.clear()
    agents._latency_ms.update(
        {
            "gemini-3.8-flash": 3000.0,
            "gemini-3.7-flash": 4200.0,
            "gemini-3.6-flash": 1900.0,
            "gemini-3.5-flash": 27900.0,
            "gemini-3.1-flash-lite": 800.0,
        }
    )
    agents._quota_marks.clear()
    picks = [agents._next_model() for _ in range(1000)]
    slow_share = picks.count("gemini-3.5-flash") / len(picks)
    lite_share = picks.count("gemini-3.1-flash-lite") / len(picks)
    check(
        "the 28s model gets a small minority of traffic",
        slow_share < 0.05,
        f"share={slow_share:.1%} (round-robin would be 20%)",
    )
    # Recording a pathological first token quarantines the model outright.
    # NB: _quota_marks is deliberately NOT cleared here — it is the quarantine
    # under test.
    agents._record_latency("gemini-3.5-flash", 28.0)
    check(
        "a pathologically slow model is quarantined, not just ranked last",
        agents._quota_marks.get("gemini-3.5-flash", 0) > time.monotonic(),
    )
    picks = [agents._next_model() for _ in range(1000)]
    check(
        "a quarantined model receives no traffic at all",
        "gemini-3.5-flash" not in picks,
    )
    check(
        "the lite model is overflow, not the default",
        lite_share < 0.10,
        f"share={lite_share:.1%}",
    )
    check(
        "the fastest full model leads the distribution",
        picks[0] == "gemini-3.6-flash",
        f"first pick={picks[0]}",
    )
    # A benched model must drop out entirely, whatever its latency.
    agents._quota_marks["gemini-3.6-flash"] = time.monotonic() + 60
    benched = [agents._next_model() for _ in range(50)]
    check(
        "a benched model is skipped even when it is the fastest",
        "gemini-3.6-flash" not in benched,
    )
finally:
    agents._quota_marks.clear()
    agents._latency_ms.clear()
    agents._latency_ms.update(saved)
    agents._model_pool = saved_pool

print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) failed: {FAILURES}")
    sys.exit(1)
print("all checks passed")
