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

# Retries exist for capacity blips, not for bad requests. One retry on a fresh
# model absorbs the common "503 high demand" spike; more than that is a slow
# failure the user is better served by seeing immediately. The previous default
# of 3 attempts with a 4s multiplier meant the worst case waited 4s + 8s before
# surfacing, on top of whatever the model layer had already spent.
STAGE_MAX_ATTEMPTS = int(os.getenv("STAGE_MAX_ATTEMPTS", "2"))
STAGE_RETRY_DELAY = int(os.getenv("STAGE_RETRY_DELAY", "2"))

# Errors that will never resolve on a retry. Retrying these just delays the
# error message the user needs to see: a bad key, a bad model id, a malformed
# request or a refused one. Matched case-insensitively against the exception
# text.
_PERMANENT_MARKERS = (
    "401",
    "403",
    "invalid_api_key",
    "incorrect api key",
    "unauthenticated",
    "permission denied",
    "model_not_found",
    "not_found_error",
    "invalid model",
    "unsupported model",
    "400",
    "invalid_request_error",
    "invalid argument",
)


def is_permanent_error(exc: Exception) -> bool:
    """True when retrying cannot possibly help."""
    text = str(exc).lower()
    return any(marker in text for marker in _PERMANENT_MARKERS)


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


def _error_text(failure: Exception) -> str:
    """A readable message from an error event.

    Agno sometimes puts a non-string object in `RunErrorEvent.content` (an
    SDK response wrapper, for instance) rather than a message, and stringifying
    that blindly leaks `<google.genai._api_client.HttpResponse object at
    0x7f...>` to the user. Fall back to the type name so the message is at
    least diagnostic.
    """
    content = getattr(failure, "content", None)
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, BaseException):
        return f"{type(content).__name__}: {content}"
    kind = getattr(failure, "error_type", None)
    if kind:
        return str(kind)
    return type(failure).__name__


# A response that stops mid-sentence was cut off by the output cap. The
# distinction matters: a report that ends on a complete thought is concise,
# one that ends on "the software will be" looks broken. These are the
# characters a finished answer may legitimately end on.
_SENTENCE_END = frozenset(".!?:;*`)]}\"'|")
# A list item or label longer than this is prose, not a fragment, so it has to
# end on real sentence punctuation like any other sentence.
_LABEL_MAX_CHARS = 90
_LAST_CHARS = 240


def looks_truncated(text: str) -> bool:
    """True when `text` appears to have been cut off mid-sentence.

    Only a heuristic, and deliberately biased towards not firing. Markdown
    reports legitimately end without sentence punctuation — on a bolded
    fragment, a heading, a table pipe, a list dash, a blockquote or a code
    fence — and treating those as truncation would cry wolf on almost every
    report. So: a last line that is structural is never truncation, and only a
    plain prose line has to end on real sentence punctuation.

    Empty text is not truncation; that is the empty-report case, handled
    separately by the caller.
    """
    tail = (text or "").rstrip()
    if not tail:
        return False

    last_line = tail.rsplit("\n", 1)[-1].strip()
    if not last_line:
        return False

    # Headings, table rows, quotes and fences genuinely end without sentence
    # punctuation, so they are never truncation.
    if last_line.startswith(("#", ">", "|", "```", "---", "***", "___")):
        return False

    # A list item or bolded label is only exempt when it is short. A short one
    # ("- **Metric:** cost-per-ton") is a deliberate fragment; a long one that
    # ends on a bare word ("* **For competitors:** do not compete on API docs,
    # instead compete on superior enterprise-level") is a sentence the output
    # cap cut in half, and calling that complete is the exact bug this guard
    # exists to catch.
    if last_line.startswith(("-", "*", "+")) or last_line.endswith(("**", "`")):
        if len(last_line) <= _LABEL_MAX_CHARS:
            return False

    return last_line[-1] not in _SENTENCE_END


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
                failure = RuntimeError(f"Report generation failed: {_error_text(event)}")
                break
        if failure is None:
            return
        if attempt < STAGE_MAX_ATTEMPTS and is_transient_error(failure) and not is_permanent_error(failure):
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
# real sources is worth more than a long one nobody reads. The brief asks for
# 3-5, so the curated floor is set to 4 and live search is capped to match.
MAX_SOURCES = int(os.getenv("MAX_SOURCES", "5"))
MIN_SOURCES = int(os.getenv("MIN_SOURCES", "3"))
# How many sources we aim for when the query actually matches that many real
# bodies. Above the floor so a well-matched query gets 4 useful links rather
# than 3, below the cap so we never pad a list out to 5 with filler.
TARGET_SOURCES = int(os.getenv("TARGET_SOURCES", "4"))

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
#
# Scored rather than first-match, so a "fintech in Nigeria" query surfaces the
# Nigerian central bank and the securities regulator alongside the IMF instead
# of whichever entry happens to be listed first.
_OFFICIAL_SOURCES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("World Bank", "https://www.worldbank.org",
     ("market", "economy", "gdp", "development", "poverty", "business",
      "nigeria", "africa", "emerging", "smb", "sme", "startup", "funding",
      "infrastructure", "sme", "enterprise", "informal")),
    ("World Bank Open Data", "https://data.worldbank.org",
     ("data", "statistic", "indicator", "population", "inflation", "rate",
      "measure", "benchmark")),
    ("FAO (UN Food & Agriculture)", "https://www.fao.org",
     ("agricultur", "farm", "food", "produce", "livestock", "crop", "rural",
      "supply chain", "restaurant", "harvest", "irrigation", "cold chain")),
    ("UNIDO", "https://www.unido.org",
     ("manufactur", "factory", "industrial", "production", "value chain")),
    ("International Trade Centre", "https://www.intracen.org",
     ("export", "import", "trade", "tariff", "customs", "logistics")),
    ("WHO", "https://www.who.int",
     ("health", "clinic", "medical", "hospital", "patient", "disease",
      "pharmac", "diagnos")),
    ("ITU", "https://www.itu.int",
     ("digital", "internet", "broadband", "telecom", "connectivity", "mobile")),
    ("IMF", "https://www.imf.org",
     ("finance", "fintech", "bank", "lending", "credit", "monetary", "currency",
      "inflation", "savings", "insurance")),
    # Nigerian and regional regulators — the sources a local founder is
    # actually obliged to deal with, and the ones a global list always misses.
    ("Central Bank of Nigeria", "https://www.cbn.gov.ng",
     ("fintech", "bank", "payment", "lending", "credit", "mobile money",
      "monetary", "currency", "deposit", "naira", "pos", "transfer",
      "financial", "insurance", "savings", "microfinance")),
    ("Securities and Exchange Commission (Nigeria)", "https://www.sec.gov.ng",
     ("securit", "invest", "capital market", "stock", "exchange", "fund",
      "asset management", "fintech", "listing")),
    ("CAC Nigeria (Corporate Affairs Commission)", "https://www.cac.gov.ng",
     ("register", "registration", "company", "incorporat", "business name",
      "entity", "licen", "startup", "entrepreneur")),
    ("SMEDAN (Nigerian SME agency)", "https://www.smedan.gov.ng",
     ("sme", "small business", "entrepreneur", "enterprise", "msme",
      "incubator", "startup", "founder", "youth", "cooperative", "artisan")),
    ("NITDA (Nigerian IT Development Agency)", "https://www.nitda.gov.ng",
     ("software", "tech", "digital", "developer", "it ", "startup",
      "innovation", "ict", "ai", "data")),
    ("CBN Exchange", "https://www.cbn.gov.ng/finmarkets/exch",
     ("forex", "exchange rate", "foreign", "remittance")),
    ("African Development Bank", "https://www.afdb.org",
     ("africa", "nigeria", "development", "finance", "infrastructure",
      "project", "investment", "grant")),
    ("WIPO (World Intellectual Property Organization)", "https://www.wipo.int",
     ("patent", "trademark", "brand", "ip", "infring", "copyright")),
    # General-purpose bodies that are relevant to almost any venture question.
    # They exist so the relevance top-up can reach MIN_SOURCES without padding
    # the list with something unrelated to the sector.
    ("World Economic Forum", "https://www.weforum.org",
     ("emerging", "trend", "future", "global", "disrupt", "opportunity",
      "innovation", "market", "business")),
    ("UNCTAD (UN Trade & Development)", "https://unctad.org",
     ("trade", "developing", "sme", "investment", "market", "business",
      "economy", "entrepreneur", "value chain")),
    ("ILO (International Labour Organization)", "https://www.ilo.org",
     ("job", "employment", "labour", "labor", "worker", "skill", "training",
      "apprentice", "wage", "informal")),
    ("UNEP", "https://www.unep.org",
     ("climate", "environment", "sustainab", "solar", "energy", "green",
      "carbon", "recycl", "waste", "emission")),
    ("IEA (International Energy Agency)", "https://www.iea.org",
     ("energy", "power", "electric", "solar", "fuel", "grid", "generator")),
)

# Ordered last-resort tier for the top-up: broad, cross-sector bodies that are
# defensible for any venture question. Used only when sector scoring left the
# list below MIN_SOURCES, and only after every keyword-matched source has been
# used — so relevance always wins over completeness.
_GENERAL_FILLERS: tuple[tuple[str, str], ...] = (
    ("World Bank", "https://www.worldbank.org"),
    ("UNCTAD (UN Trade & Development)", "https://unctad.org"),
    ("World Economic Forum", "https://www.weforum.org"),
    ("ILO (International Labour Organization)", "https://www.ilo.org"),
    ("ITU", "https://www.itu.int"),
    ("UNIDO", "https://www.unido.org"),
    ("WIPO (World Intellectual Property Organization)", "https://www.wipo.int"),
)

# Sector terms that are strong enough to rank a source above a generic match.
_STRONG_TERMS = frozenset(
    ("fintech", "bank", "payment", "lending", "credit", "insurance", "savings",
     "agricultur", "farm", "food", "health", "clinic", "medical", "energy",
     "solar", "climate", "logistics", "manufactur", "export", "import",
     "telecom", "software", "developer", "patent", "trademark", "crypto")
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


# When the query names the country, the local regulator is more useful than the
# global institution. "fintech in Nigeria" should point at the CBN, not lead
# with the IMF.
_LOCALE_BOOST = 4
_LOCALE_TERMS = ("nigeria", "nigerian", "lagos", "abuja", "kano", "ibadan",
                 "port harcourt", "aba", "benin city", "kaduna", "enugu",
                 "africa", "african", "west africa", "naira")
# Local bodies, used to pick the top-up when a query has too few matches.
_LOCAL_LABELS = ("cbn.gov.ng", "sec.gov.ng", "cac.gov.ng", "smedan.gov.ng",
                 "nitda.gov.ng")


def _official_fallback(query: str, limit: int = 4) -> list[dict]:
    """Curated official sources ranked by how well they match the query.

    Relevance is scored, not first-matched: a body whose keywords include a
    term the query uses *strongly* (a sector word like "fintech") outranks one
    that only matches a broad word like "market". A local regulator is boosted
    when the query names its country, so "fintech in Nigeria" leads with the
    Central Bank of Nigeria instead of the IMF.
    """
    low = f" {(query or '').lower()} "
    local = any(term in low for term in _LOCALE_TERMS)
    scored: list[tuple[int, int, str, str]] = []
    for order, (label, url, keywords) in enumerate(_OFFICIAL_SOURCES):
        score = 0
        for kw in keywords:
            if kw in low:
                # Sector terms are worth more than catch-alls.
                score += 3 if kw in _STRONG_TERMS else 1
        if not score:
            continue
        if local and any(d in url for d in _LOCAL_LABELS):
            score += _LOCALE_BOOST
        scored.append((-score, order, label, url))

    scored.sort()
    return [{"label": label, "url": url} for _, _, label, url in scored[:limit]]


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
        """Assemble the Sources list, guaranteeing MIN..MAX real links.

        Three tiers, in descending relevance, each filling only what the tier
        above left short:

        1. live search results (most specific, so they always come first)
        2. curated official bodies scored against the query
        3. broad cross-sector bodies

        The top-up is unconditional, not just a fallback for a dead search
        backend. Live search routinely returns one or two usable links, and
        shipping a one-line Sources section reads as a bug rather than as
        restraint. Dedup is by URL, and the result is capped at `limit`.
        """
        found: list[dict] = []
        seen: set[str] = set()

        def add(label: str, url: str) -> bool:
            if url in seen or len(found) >= self.limit:
                return False
            seen.add(url)
            found.append({"label": label, "url": url})
            return True

        # 1. Live search. A couple of narrow queries beat one broad one: the
        #    first asks about the subject, the second about the market around
        #    it.
        base = self.query.strip()
        queries = [base] if base else []
        if len(base) > 8:
            queries.append(f"{base} market size report")

        for query in queries[:MAX_LIVE_QUERIES]:
            try:
                for src in _live_search(query, limit=3):
                    add(src["label"], src["url"])
            except Exception as exc:  # noqa: BLE001
                # A dead search backend is expected and survivable.
                print(f"[thrace] source retrieval failed: {str(exc)[:160]}", flush=True)
                break

        # 2. Curated official bodies, most relevant first. Fills up to
        #    TARGET_SOURCES so a well-matched query gets more than the bare
        #    floor, but only with bodies that actually scored. `limit` is the
        #    full list so ranking, not truncation, decides the order.
        if len(found) < TARGET_SOURCES:
            for src in _official_fallback(base, limit=len(_OFFICIAL_SOURCES)):
                if len(found) >= TARGET_SOURCES:
                    break
                add(src["label"], src["url"])

        # 3. Broad cross-sector bodies, for queries too narrow to score
        #    anything (e.g. "crypto exchange" matches a single regulator).
        if len(found) < MIN_SOURCES:
            for label, url in _GENERAL_FILLERS:
                if len(found) >= MIN_SOURCES:
                    break
                add(label, url)

        self._sources = found[: self.limit]

    def has_sources(self) -> bool:
        """True once the collector has produced a full, renderable list."""
        return MIN_SOURCES <= len(self._sources) <= MAX_SOURCES

    def results(self, budget: float = SOURCE_BUDGET_SECONDS) -> list[dict]:
        """Wait up to `budget` seconds for the thread, then take what we have."""
        if self._thread is not None:
            self._thread.join(timeout=budget)
        return list(self._sources)


def render_sources(sources: list[dict]) -> str:
    """Render the `## Sources` block, or '' when there is nothing real to show.

    Deliberately a plain markdown list, not an inline citation scheme: the
    report never cites [1]/[2], and every link is a real URL that was either
    returned by search or is a known official body. `markdown.tsx` already
    renders these as clickable external links.

    The 3-5 rule is enforced here as well as in the collector, so no caller can
    emit a stub Sources section by passing a short list. Short lists are topped
    up from the broad tier; long ones are capped; duplicates are dropped.
    """
    if not sources:
        return ""

    picked: list[dict] = []
    seen: set[str] = set()
    for src in sources:
        url = src.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        picked.append(src)

    # A caller that skipped the collector still gets a usable list. Filler is
    # only added up to the floor, never to pad a list out to the target.
    for label, url in _GENERAL_FILLERS:
        if len(picked) >= MIN_SOURCES:
            break
        if url not in seen:
            seen.add(url)
            picked.append({"label": label, "url": url})

    picked = picked[:MAX_SOURCES]
    lines = ["", "## Sources", ""]
    for src in picked:
        lines.append(f"- [{src['label']}]({src['url']})")
    lines.append("")
    return "\n".join(lines)
