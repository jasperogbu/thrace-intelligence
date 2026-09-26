"""
Shared fast intelligence layer.

One execution strategy for Venture Intelligence, Company X-Ray and Discovery:

    single streaming model call  ->  optional lightweight sources  ->  done

Everything here is deliberately dependency-light. There is no queue, no
orchestrator, no agent graph — just a streaming helper, a bounded source
collector, and the formatting that turns real search results into a
`## Sources` block.

Two rules govern the whole module:

1. The model never writes a URL. Links come only from `SourceCollector`, which
   reads them off real search results. That is what makes it safe to loosen the
   old "never print a list of links" rule on the instant path: the analyst is
   still forbidden from inventing a source, we just supply the real ones.

2. Sources never gate the response. The report streams first; sources are
   appended afterwards if they happen to have arrived. Any failure in here is
   swallowed — a dead search backend costs the user their sources, never their
   report.
"""
from __future__ import annotations

import os
import re
import threading
import time
from textwrap import dedent
from typing import Callable, Iterator

# ---------------------------------------------------------------------------
# Transient-error policy (shared by every fast path)
# ---------------------------------------------------------------------------
# Reused by agents.py for its quota/rotation logic, so the retry rules stay in
# one place.
# Moved here from agents.py so the fast paths and the quota/rotation logic
# share one definition. The marker list is unchanged — it already covers the
# Gemini quota phrasings ("resource_exhausted", "high demand", "quota
# exceeded") as well as the generic 429/503 cases.
_TRANSIENT_MARKERS = (
    "429",
    "503",
    "resource_exhausted",
    "unavailable",
    "rate limit",
    "rate_limit",
    "high demand",
    "overloaded",
    "quota exceeded",
    "please try again",
    "temporarily unavailable",
)

STAGE_MAX_ATTEMPTS = int(os.getenv("STAGE_MAX_ATTEMPTS", "3"))
STAGE_RETRY_DELAY = int(os.getenv("STAGE_RETRY_DELAY", "4"))


def is_transient_error(exc: Exception) -> bool:
    """True when a provider failure is worth retrying rather than surfacing."""
    return any(marker in str(exc).lower() for marker in _TRANSIENT_MARKERS)


# ---------------------------------------------------------------------------
# Shared analyst rules
# ---------------------------------------------------------------------------
# Used as the agent `description` (i.e. the system prompt) for every fast path.
# It states what the model may do with numbers and sources, so the three
# features differ only in their user prompt, never in their honesty rules.
FAST_ANALYST_RULES = dedent("""
    You are Thrace's fast intelligence analyst. You write complete,
    decision-ready business intelligence from your own knowledge, immediately,
    in a single pass. You have no research tools and no live data.

    Hard rules:
    - Never fabricate sources, URLs or citations. Another process attaches real
      links to the report for you; your job is the analysis, not the sourcing.
      Do not print a "Sources" section and do not mention that sources were or
      were not checked.
    - Never invent precise statistics. When a figure is an estimate, label it
      "estimate" and state the assumption behind it.
    - Never invent companies, people, funding rounds or product names. If you
      are not reasonably confident a named organisation exists, describe the
      category instead.
    - Separate what you know from what you are inferring. Use hedged language
      ("typically", "in this segment", "would need validating") for anything
      that is a judgement rather than established fact.
    - Be specific, quantitative where you can, and decisive. This is an
      analyst's brief, not a hedge.
    - Markdown. Tables where they help, concise bullets elsewhere, no long
      paragraphs.
""")


# ---------------------------------------------------------------------------
# Shared streaming
# ---------------------------------------------------------------------------
# Agno emits several event classes per run; we only care about content deltas
# and the terminal error. Imported lazily so this module stays importable
# without Agno present (used by scripts and tests).
def _agno_events():
    from agno.run.agent import RunContentEvent, RunErrorEvent

    return RunContentEvent, RunErrorEvent


def stream_agent(agent_factory: Callable[[], object], prompt: str) -> Iterator[dict]:
    """Stream one report from a no-tools agent, retrying transient failures.

    `agent_factory` is called on every attempt so a retry rebuilds the agent
    against a fresh (possibly rotated) model. On a retry that already emitted
    text we emit a `reset` first, so the client discards the partial report
    instead of showing two stitched attempts.
    """
    run_content, run_error = _agno_events()

    emitted = False
    attempt = 0
    while True:
        attempt += 1
        failure: Exception | None = None
        for event in agent_factory().run(prompt, stream=True):  # type: ignore[attr-defined]
            if isinstance(event, run_content):
                if event.content:
                    emitted = True
                    yield {"type": "delta", "data": event.content}
            elif isinstance(event, run_error):
                failure = RuntimeError(
                    f"Report generation failed: "
                    f"{event.content or event.error_type or 'unknown'}"
                )
                break
        if failure is None:
            return
        if attempt < STAGE_MAX_ATTEMPTS and is_transient_error(failure):
            if emitted:
                yield {"type": "reset"}
                emitted = False
            wait = STAGE_RETRY_DELAY * attempt
            print(
                f"[thrace] transient provider error in report "
                f"(attempt {attempt}/{STAGE_MAX_ATTEMPTS}); restarting in {wait}s — "
                f"{str(failure)[:200]}",
                flush=True,
            )
            time.sleep(wait)
            continue
        raise failure


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
# How many links we are willing to show. Kept small on purpose: a short list of
# real sources is worth more than a long one nobody reads.
MAX_SOURCES = int(os.getenv("MAX_SOURCES", "5"))

# Wall-clock budget for source retrieval. The report is already streaming by
# the time this matters, so the only cost of a slow backend is a short pause
# before the Sources block is appended.
SOURCE_BUDGET_SECONDS = float(os.getenv("SOURCE_BUDGET_SECONDS", "6"))

# Firecrawl is optional infrastructure. With no key (or no credits left on the
# key) we skip live search entirely and fall back to the curated set.
MAX_LIVE_QUERIES = int(os.getenv("MAX_SOURCE_QUERIES", "2"))

# Official bodies whose root domains are stable and well known. These are a
# *floor*, not a substitute for live search: they are only offered when live
# retrieval produced nothing, and only when the query actually touches their
# subject. Every URL here is a real, long-standing organisation homepage.
_OFFICIAL_SOURCES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("World Bank", "https://www.worldbank.org",
     ("market", "economy", "gdp", "development", "poverty", "business",
      "nigeria", "africa", "emerging", "smb", "sme", "startup", "funding")),
    ("FAO (UN Food & Agriculture)", "https://www.fao.org",
     ("agricultur", "farm", "food", "produce", "livestock", "crop", "rural",
      "supply chain", "restaurant")),
    ("World Bank Open Data", "https://data.worldbank.org",
     ("data", "statistic", "indicator", "population", "inflation", "rate")),
    ("UNIDO", "https://www.unido.org",
     ("manufactur", "factory", "industrial", "production", "value chain")),
    ("International Trade Centre", "https://www.intracen.org",
     ("export", "import", "trade", "tariff", "customs", "logistics")),
    ("WHO", "https://www.who.int",
     ("health", "clinic", "medical", "hospital", "patient", "disease")),
    ("ITU", "https://www.itu.int",
     ("digital", "internet", "broadband", "telecom", "connectivity", "mobile")),
    ("IMF", "https://www.imf.org",
     ("finance", "fintech", "bank", "lending", "credit", "monetary", "currency")),
)

_URL_RE = re.compile(r"https?://[^\s\)\]\"'<>]+")
_MD_LINK_RE = re.compile(r"\[([^\]]{1,120})\]\((https?://[^)\s]+)\)")


def _clean_url(raw: str) -> str | None:
    """Normalise a scraped URL, dropping anything that is not a real link."""
    url = raw.strip().rstrip(".,;")
    if not url.startswith(("http://", "https://")):
        return None
    # Trailing markdown punctuation that survives the split.
    url = url.rstrip(").,;:")
    host = re.sub(r"^https?://", "", url).split("/")[0].lower()
    if not host or "." not in host:
        return None
    return url


def _extract_sources(markdown: str) -> list[dict]:
    """Pull (label, url) pairs out of a Firecrawl search result block.

    Prefers markdown links (which carry a real title) and falls back to bare
    URLs, in which case the hostname becomes the label.
    """
    seen: set[str] = set()
    out: list[dict] = []

    for title, raw in _MD_LINK_RE.findall(markdown or ""):
        url = _clean_url(raw)
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({"label": title.strip()[:100] or _label_from(url), "url": url})

    for raw in _URL_RE.findall(markdown or ""):
        url = _clean_url(raw)
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({"label": _label_from(url), "url": url})

    return out


def _label_from(url: str) -> str:
    """Derive a readable label from a URL's host and first path segment."""
    try:
        trimmed = re.sub(r"^https?://(www\.)?", "", url)
        parts = [p for p in trimmed.split("/") if p]
        if not parts:
            return url
        host = parts[0].split(":")[0].replace("-", " ").replace(".com", "")
        if len(parts) > 1 and parts[1] not in ("index.html", "index.htm"):
            return f"{host} — {parts[1][:48]}"
        return host
    except Exception:  # noqa: BLE001
        return url


def _official_fallback(query: str) -> list[dict]:
    """Curated official sources whose subject the query actually touches."""
    low = (query or "").lower()
    return [
        {"label": label, "url": url}
        for label, url, keywords in _OFFICIAL_SOURCES
        if any(k in low for k in keywords)
    ][:3]


def _live_search(query: str, limit: int) -> list[dict]:
    """Run one real web search and return whatever URLs it yielded.

    Imported lazily so that a missing or broken Firecrawl configuration cannot
    prevent this module from being imported at all.
    """
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    if not os.getenv("FIRECRAWL_API_KEY"):
        return []

    import agents  # local import: agents imports this module

    tools = agents.TOOLS()
    raw = tools.search_web(query, limit=limit)
    return _extract_sources(raw if isinstance(raw, str) else "")


class SourceCollector:
    """Fetch sources on a background thread so the report never waits for them.

    Usage:

        collector = SourceCollector(query)
        collector.start()
        yield from stream_report(...)      # report streams immediately
        for src in collector.results():   # bounded wait, may be empty
            ...
    """

    def __init__(self, query: str, limit: int = MAX_SOURCES) -> None:
        self.query = query
        self.limit = limit
        self._thread: threading.Thread | None = None
        self._sources: list[dict] = []

    def start(self) -> "SourceCollector":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        found: list[dict] = []
        seen: set[str] = set()
        # A couple of narrow queries beat one broad one: the first asks about
        # the subject, the second about the market around it.
        queries = [self.query.strip()][:1]
        if len(self.query.strip()) > 8:
            queries.append(f"{self.query.strip()} market size report")

        for query in queries[:MAX_LIVE_QUERIES]:
            try:
                for src in _live_search(query, limit=3):
                    if src["url"] in seen:
                        continue
                    seen.add(src["url"])
                    found.append(src)
            except Exception as exc:  # noqa: BLE001
                # A dead search backend is expected and survivable.
                print(f"[thrace] source retrieval failed: {str(exc)[:160]}", flush=True)
                break

        if not found:
            found = _official_fallback(self.query)
        self._sources = found[: self.limit]

    def results(self, budget: float = SOURCE_BUDGET_SECONDS) -> list[dict]:
        """Wait up to `budget` seconds for the thread, then take what we have."""
        if self._thread is not None:
            self._thread.join(timeout=budget)
        return list(self._sources)


def render_sources(sources: list[dict]) -> str:
    """Render the `## Sources` block, or '' when there is nothing real to show."""
    if not sources:
        return ""
    lines = ["", "## Sources", ""]
    for src in sources:
        lines.append(f"- [{src['label']}]({src['url']})")
    lines.append("")
    return "\n".join(lines)
