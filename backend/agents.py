"""
Thrace agent engine.

Two coordinated intelligence pipelines:

1. Venture Intelligence (primary) — a 5-stage agent pipeline that validates a
   business idea, sizes the market, maps competitors, scores probability of
   success, and produces an execution-ready venture plan.

2. Company X-Ray (secondary) — the original multi-agent team (Agno) producing
   competitor / sentiment / metrics reports for an existing company.
"""
import os
import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from textwrap import dedent
from typing import Callable, Iterator

from agno.agent import Agent
from agno.team import Team
from agno.models.openai import OpenAIChat
from agno.models.google import Gemini
from agno.tools.firecrawl import FirecrawlTools
from agno.run.agent import RunContentEvent as AgentRunContentEvent
from agno.run.agent import RunErrorEvent as AgentRunErrorEvent
from agno.run.base import RunStatus
from agno.run.team import (
    RunContentCompletedEvent,
    RunContentEvent,
    RunErrorEvent,
)

# Hard cap on tool result size (chars). Groq's free tier rejects any single
# request over ~8k tokens; uncapped scrape/crawl results (full page markdown)
# blow past that inside the agentic loop.
_MAX_TOOL_CHARS = int(os.getenv("TOOL_RESULT_MAX_CHARS", "3000"))


def _clip(text: str, label: str) -> str:
    """Truncate oversized tool output so requests stay under provider TPM limits."""
    if not isinstance(text, str) or len(text) <= _MAX_TOOL_CHARS:
        return text
    dropped = len(text) - _MAX_TOOL_CHARS
    return (
        f"{text[:_MAX_TOOL_CHARS]}\n"
        f"...[{label} truncated {dropped} chars to stay within model token limits]"
    )


def _make_tools() -> FirecrawlTools:
    """Firecrawl tools with a tolerant search wrapper and result-size clipping.

    gpt-oss models call `search_web` with extra kwargs (source, top_n,
    recency_days...) that Agno's signature rejects, crashing the run.
    The wrapper declares the common extras as optional params and ignores
    unknown ones at runtime; the JSON schema sent to the model is overridden
    to only advertise `query` + `limit`.

    All tool results are clipped to _MAX_TOOL_CHARS: scrape/crawl return full
    page markdown, which otherwise accumulates in the conversation and exceeds
    Groq's per-request TPM ceiling.
    """
    tk = FirecrawlTools(
        enable_search=True,
        enable_crawl=True,
        limit=3,
        poll_interval=10,
    )

    orig = tk.search_web

    def search_web_tolerant(
        query: str,
        limit: int | None = None,
        source: str | None = None,
        top_n: int | None = None,
        recency_days: int | None = None,
        **_ignored,
    ):
        params: dict = {}
        if limit is None and top_n is not None:
            limit = top_n
        if limit is not None:
            try:
                params["limit"] = max(1, min(int(limit), 10))
            except (TypeError, ValueError):
                pass
        if source:
            params["sources"] = [source] if isinstance(source, str) else list(source)
        if recency_days and int(recency_days) > 0:
            params["tbs"] = f"qdr:{max(1, min(int(recency_days), 365))}d"
        try:
            return _clip(orig(query, **params), "search results")
        except TypeError:
            # base signature only accepts (query, limit) — retry conservative
            return _clip(orig(query, limit=params.get("limit")), "search results")

    search_web_tolerant.__doc__ = (
        "Search the web using Firecrawl.\n"
        "Args:\n"
        "    query (str): The search query.\n"
        "    limit (int, optional): Max results to return (default 3).\n"
        "    source (str, optional): Restrict results to 'news' or 'web'.\n"
        "    top_n (int, optional): Alias for limit.\n"
        "    recency_days (int, optional): Only results from the last N days.\n"
    )
    tk.search_web = search_web_tolerant
    tk.register(search_web_tolerant, name="search_web")

    # Clip scrape/crawl results — full page markdown is the main TPM risk.
    orig_scrape = tk.scrape_website
    orig_crawl = tk.crawl_website

    def scrape_website(url: str) -> str:
        """Scrape a single web page. Returns the top of the page content
        (truncated) plus metadata. Prefer search_web for discovery; use this
        only when you need details from one specific page.
        """
        return _clip(orig_scrape(url), f"scrape of {url}")

    def crawl_website(url: str, limit: int | None = None) -> str:
        """Crawl a website (up to `limit` pages). Results are truncated —
        use sparingly, search_web is usually enough.
        """
        return _clip(orig_crawl(url, limit=limit), f"crawl of {url}")

    tk.scrape_website = scrape_website
    tk.register(scrape_website, name="scrape_website")
    tk.crawl_website = crawl_website
    tk.register(crawl_website, name="crawl_website")

    # Clean model-facing schema: advertise only query (+ optional limit).
    # The wrapper tolerates extra kwargs at runtime; a **kwargs param would
    # otherwise leak into the schema as a required property.
    search_fn = tk.functions["search_web"]
    search_fn.strict = False
    search_fn.parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (default 3).",
            },
            "source": {
                "type": "string",
                "description": "Restrict results to 'news' or 'web'.",
            },
        },
        "required": ["query"],
        "additionalProperties": True,
    }
    return tk


TOOLS = _make_tools

# Default model; override with LLM_MODEL in .env (e.g. a router/gateway model id).
MODEL = os.getenv("LLM_MODEL", "gpt-4o")

# Per-call retry budget for transient provider errors. Deliberately minimal:
# the model layer rotates to a healthy model on its own, so sleeping inside a
# single call mostly just delays that rotation.
_LLM_RETRIES = int(os.getenv("LLM_RETRIES", "1"))
_LLM_RETRY_DELAY = int(os.getenv("LLM_RETRY_DELAY", "1"))

# Gemini free tier enforces per-model request quotas (surfaced as 429
# RESOURCE_EXHAUSTED with a short retry window, in practice ~1 minute). A
# pipeline run needs dozens of requests, so instead of hammering one model
# until it dies, every request is round-robined across a pool of models and
# globally paced. A model that returns a quota error is skipped for the
# duration of its reported retry delay. Override the pool with
# LLM_FALLBACK_MODELS (comma-separated).
_GEMINI_DEFAULT_FALLBACKS = (
    "gemini-3.7-flash,gemini-3.6-flash,gemini-3.5-flash,gemini-3.1-flash-lite"
)
_QUOTA_COOLDOWN_DEFAULT = float(os.getenv("QUOTA_COOLDOWN_SECONDS", "60"))
_GEMINI_MIN_INTERVAL = float(os.getenv("GEMINI_MIN_REQUEST_INTERVAL", "1.2"))
# A benched model is skipped for at most this long, and the request pipeline
# never pauses longer than this waiting for a free model. Both are speed
# guards: honouring a provider's full 60s retry window while three other
# models sit idle is the single biggest source of multi-minute runs.
_QUOTA_BENCH_CAP = float(os.getenv("QUOTA_BENCH_CAP_SECONDS", "15"))
_MAX_COOLDOWN_WAIT = float(os.getenv("QUOTA_MAX_WAIT_SECONDS", "2"))
# How long to bench a model after a capacity spike (503). Short: the spike is
# usually momentary and another model in the pool can serve the request now.
_TRANSIENT_BENCH_SECONDS = float(os.getenv("TRANSIENT_BENCH_SECONDS", "3"))

_rotation_lock = threading.Lock()
_pacer_lock = threading.Lock()
_quota_marks: dict[str, float] = {}  # model -> monotonic ts when usable again
_rr_index = 0
_last_request_ts = 0.0

_RETRY_DELAY_RE = re.compile(r"retry in ([0-9.]+)\s*s", re.IGNORECASE)


def _model_pool() -> list[str]:
    """Primary model plus fallbacks, deduplicated, order preserved."""
    if MODEL.lower().startswith("gemini"):
        raw = os.getenv("LLM_FALLBACK_MODELS")
        if raw is None:
            raw = _GEMINI_DEFAULT_FALLBACKS
        candidates = [MODEL] + [m.strip() for m in raw.split(",") if m.strip()]
    else:
        candidates = [MODEL]
    pool: list[str] = []
    for m in candidates:
        if m and m not in pool:
            pool.append(m)
    return pool


def _next_model() -> str:
    """Round-robin the next usable model.

    Skips models benched by a quota error. When every model is cooling down we
    pause briefly and then return the model that frees up soonest, rather than
    blocking until its full retry window expires — a run must never stall for a
    minute because one model is throttled.
    """
    global _rr_index
    with _rotation_lock:
        pool = _model_pool()
        if len(pool) == 1:
            return pool[0]
        now = time.monotonic()
        usable = [m for m in pool if _quota_marks.get(m, 0.0) <= now]
        if usable:
            _rr_index += 1
            return usable[_rr_index % len(usable)]
        soonest = min(pool, key=lambda m: _quota_marks.get(m, 0.0))
        wait = _quota_marks[soonest] - now
    capped = min(max(wait, 0.0), _MAX_COOLDOWN_WAIT)
    print(
        f"[thrace] all Gemini models cooling down; earliest free in {wait:.0f}s "
        f"(pausing {capped:.1f}s, then trying anyway)",
        flush=True,
    )
    if capped > 0:
        time.sleep(capped)
    return soonest


def _mark_model_exhausted(model: str, seconds: float) -> None:
    """Bench `model` so the next request rotates to another model.

    The provider-reported window is honoured but capped (see
    `_QUOTA_BENCH_CAP`): with several models in the pool, a short bench plus
    immediate failover beats waiting out a long window.
    """
    with _rotation_lock:
        window = min(max(seconds, 2.0), _QUOTA_BENCH_CAP)
        until = time.monotonic() + window + 1.0
        _quota_marks[model] = max(_quota_marks.get(model, 0.0), until)


def _is_quota_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "resource_exhausted" in msg or "quota" in msg


def _parse_retry_delay(exc: Exception) -> float:
    """Extract the provider's 'Please retry in Ns' window from a quota error."""
    m = _RETRY_DELAY_RE.search(str(exc))
    return float(m.group(1)) if m else _QUOTA_COOLDOWN_DEFAULT


def _pace_gemini_request() -> None:
    """Space Gemini requests at least GEMINI_MIN_REQUEST_INTERVAL apart.

    With round-robin across the pool this caps each model at roughly
    interval x pool-size per request (well under the per-model ceiling)
    while keeping global throughput high.
    """
    global _last_request_ts
    if _GEMINI_MIN_INTERVAL <= 0:
        return
    with _pacer_lock:
        now = time.monotonic()
        wait = _last_request_ts + _GEMINI_MIN_INTERVAL - now
        if wait > 0:
            time.sleep(wait)
        _last_request_ts = time.monotonic()


class _PacedGemini(Gemini):
    """Gemini client that round-robins every request across the model pool.

    Each request picks the next usable model and is globally paced. Any
    transient provider error rotates to another model and transparently
    retries, so per-model limits and capacity spikes never surface to the
    agent layer.
    """

    def invoke(self, *args, **kwargs):
        max_attempts = max(len(_model_pool()) * 2, 4)
        for attempt in range(1, max_attempts + 1):
            self.id = _next_model()
            _pace_gemini_request()
            try:
                return super().invoke(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                if _rotate_on(self.id, exc, attempt, max_attempts):
                    continue
                raise

    def invoke_stream(self, *args, **kwargs):
        max_attempts = max(len(_model_pool()) * 2, 4)
        for attempt in range(1, max_attempts + 1):
            self.id = _next_model()
            _pace_gemini_request()
            emitted = False
            try:
                for chunk in super().invoke_stream(*args, **kwargs):
                    emitted = True
                    yield chunk
                return
            except Exception as exc:  # noqa: BLE001
                # A stream that already produced output cannot restart here
                # without duplicating content; the pipeline layer handles
                # that case (it can reset the client's accumulated text).
                if not emitted and _rotate_on(self.id, exc, attempt, max_attempts):
                    continue
                raise


def _chat_model():
    """Build the LLM client.

    Provider is auto-detected from the model id:
      - ids starting with "gemini" -> Google Gemini via the native SDK
        (key from GEMINI_API_KEY, falling back to LLM_API_KEY)
      - anything else -> any OpenAI-compatible provider:
          - LLM_API_KEY   -> provider key (falls back to OPENAI_API_KEY)
          - LLM_MODEL     -> model id (default gpt-4o)
          - LLM_BASE_URL  -> custom endpoint (e.g. an agent router / gateway); omit
                             for the default OpenAI endpoint.
    """
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if MODEL.lower().startswith("gemini"):
        return _PacedGemini(
            id=MODEL,
            api_key=os.getenv("GEMINI_API_KEY") or api_key,
            # Transient provider rate limits are retryable, but Agno's retries
            # multiply: with exponential backoff, retries=5/delay=8 sleeps
            # 8+16+32+64+128s on one flaky call. Quota errors are already
            # absorbed by the round-robin above, so keep in-call retries short
            # and let the outer stage wrapper own the real backoff.
            retries=_LLM_RETRIES,
            exponential_backoff=True,
            delay_between_retries=_LLM_RETRY_DELAY,
        )
    base_url = os.getenv("LLM_BASE_URL") or None
    return OpenAIChat(
        id=MODEL,
        api_key=api_key,
        base_url=base_url,
        # Transient provider 429s (e.g. free-tier TPM windows) are retryable;
        # Agno's `retries` defaults to 0, which disables backoff entirely.
        retries=_LLM_RETRIES,
        exponential_backoff=True,
        delay_between_retries=_LLM_RETRY_DELAY,
    )

# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
def _competitor_agent() -> Agent:
    return Agent(
        name="Startup / Competitor Analysis Agent",
        description=dedent("""
            You are a senior startup and competitor analysis strategist who evaluates
            business positioning, product launches, and venture strategy with a critical,
            evidence-driven lens.
            Your objective is to uncover:
            - How a startup or product is positioned in the market
            - Which strategies and launch tactics drove success (strengths)
            - Where execution fell short (weaknesses)
            - Actionable competitive advantages and learnings for founders and investors
            Always cite observable signals (messaging, pricing actions, channel mix, timing,
            engagement metrics). Maintain a crisp, executive tone and focus on strategic value.
            IMPORTANT: Conclude your report with a 'Sources:' section listing all URLs you
            crawled or searched.
        """),
        model=_chat_model(),
        tools=[TOOLS()],
        markdown=True,
        exponential_backoff=True,
        delay_between_retries=2,
    )


def _sentiment_agent() -> Agent:
    return Agent(
        name="Market Sentiment Analysis Agent",
        description=dedent("""
            You are a market research expert specializing in sentiment analysis and consumer
            perception tracking. Your expertise includes:
            - Analyzing social media sentiment and customer feedback
            - Identifying positive and negative sentiment drivers
            - Tracking brand perception trends across platforms
            - Monitoring customer satisfaction and review patterns
            - Providing actionable insights on market reception
            Focus on extracting sentiment signals from social platforms, review sites, forums,
            and customer feedback channels.
            IMPORTANT: Conclude your report with a 'Sources:' section listing all URLs you
            crawled or searched.
        """),
        model=_chat_model(),
        tools=[TOOLS()],
        markdown=True,
        exponential_backoff=True,
        delay_between_retries=2,
    )


def _metrics_agent() -> Agent:
    return Agent(
        name="Performance Metrics Agent",
        description=dedent("""
            You are a product and startup performance analyst who specializes in tracking and
            analyzing growth KPIs. Your focus areas include:
            - User adoption and engagement metrics
            - Revenue and business performance indicators
            - Market penetration and growth rates
            - Press coverage and media attention analysis
            - Social media traction and viral coefficient tracking
            - Competitive market share analysis
            Always provide quantitative insights with context and benchmark against industry
            standards when possible.
            IMPORTANT: Conclude your report with a 'Sources:' section listing all URLs you
            crawled or searched.
        """),
        model=_chat_model(),
        tools=[TOOLS()],
        markdown=True,
        exponential_backoff=True,
        delay_between_retries=2,
    )


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------
_team: Team | None = None
_team_error: str | None = None


def build_team() -> Team:
    """Build (or return a cached) Thrace intelligence team."""
    global _team, _team_error
    if _team is not None:
        return _team
    if not (
        os.getenv("LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("GEMINI_API_KEY")
    ) or not os.getenv("FIRECRAWL_API_KEY"):
        _team_error = (
            "Missing API keys. Configure a model key (LLM_API_KEY, GEMINI_API_KEY "
            "or OPENAI_API_KEY) and FIRECRAWL_API_KEY in .env"
        )
        raise RuntimeError(_team_error)

    _team = Team(
        name="Thrace Intelligence Team",
        model=_chat_model(),
        members=[_competitor_agent(), _sentiment_agent(), _metrics_agent()],
        instructions=[
            "Coordinate the analysis based on the user's request type:",
            "1. For competitor / startup analysis: use the Startup / Competitor Analysis Agent",
            "2. For market sentiment: use the Market Sentiment Analysis Agent",
            "3. For performance metrics: use the Performance Metrics Agent",
            "Always provide evidence-based insights with specific examples and data points",
            "Structure responses with clear sections and actionable recommendations",
            "Include a sources section with all URLs crawled or searched",
        ],
        markdown=True,
        show_members_responses=True,
    )
    return _team


VENTURE_AGENT_NAMES = [
    "Venture Validation Agent",
    "Market Intelligence Agent",
    "Competition Analysis Agent",
    "Risk & Success Agent",
    "Venture Planning Agent",
]

XRAY_AGENT_NAMES = [
    "Startup / Competitor Analysis Agent",
    "Market Sentiment Analysis Agent",
    "Performance Metrics Agent",
]


def team_status() -> dict:
    global _team, _team_error
    ready = _team is not None or bool(
        (
            os.getenv("LLM_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("GEMINI_API_KEY")
        )
        and os.getenv("FIRECRAWL_API_KEY")
    )
    return {
        "ready": ready,
        "error": _team_error,
        "model": MODEL,
        "pipelines": ["venture", "xray"],
        "agents": VENTURE_AGENT_NAMES + XRAY_AGENT_NAMES,
    }


def _check_run(resp, context: str) -> str:
    """Validate a completed agent/team run, raising a clear error on failure.

    Agno returns failed runs as RunOutput objects with the error text as
    content instead of raising, so status/content must be checked explicitly.
    """
    content = getattr(resp, "content", None)
    status = getattr(resp, "status", None)
    if status is not None and status != RunStatus.completed:
        raise RuntimeError(f"{context}: {content or status}")
    if not content or not str(content).strip():
        raise RuntimeError(f"{context}: model returned no content")
    return str(content)


# ---------------------------------------------------------------------------
# Transient provider error retry (outer, stage-level)
# ---------------------------------------------------------------------------
# Agno retries 429s at the model layer but gives up on 503 UNAVAILABLE
# capacity spikes ("model experiencing high demand"), which are common on
# new Gemini models on the free tier. This outer wrapper retries whole
# stage runs when the failure text looks transient.
# Stage-level retry budget. `_STAGE_RETRY_DELAY * attempt` used to be 15/30/45s
# of dead time per stage; stages now also run concurrently, so a long sleep on
# one stage blocks the whole report. Keep it short.
_STAGE_MAX_ATTEMPTS = int(os.getenv("STAGE_MAX_ATTEMPTS", "3"))
_STAGE_RETRY_DELAY = int(os.getenv("STAGE_RETRY_DELAY", "4"))

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


def _is_transient_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _TRANSIENT_MARKERS)


def _rotate_on(model: str, exc: Exception, attempt: int, max_attempts: int) -> bool:
    """Bench `model` and rotate to the next one.

    Called from the model layer for any transient provider error. Retrying the
    same model on a 503 ("model experiencing high demand") burns the run's time
    budget while other pooled models sit idle, so both quota (429) and capacity
    errors rotate. Returns False when we are out of attempts or the failure is
    not transient, i.e. the caller should re-raise.
    """
    if attempt >= max_attempts or not _is_transient_error(exc):
        return False
    _mark_model_exhausted(model, _bench_seconds(exc))
    print(
        f"[thrace] {model} unavailable/rate-limited; rotating to the next model",
        flush=True,
    )
    return True


def _bench_seconds(exc: Exception) -> float:
    """How long to bench the failed model: the quota window, or a short pause."""
    return _parse_retry_delay(exc) if _is_quota_error(exc) else _TRANSIENT_BENCH_SECONDS


def _run_with_retries(run_fn, context: str):
    """Run a callable, retrying on transient provider errors with backoff.

    Quota (429) and capacity (503) errors are already absorbed at the model
    layer (round-robin + transparent rotation); this outer wrapper is the
    backstop for failures that outlive every model in the pool.
    """
    for attempt in range(1, _STAGE_MAX_ATTEMPTS + 1):
        try:
            return run_fn()
        except Exception as exc:  # noqa: BLE001
            if attempt >= _STAGE_MAX_ATTEMPTS or not _is_transient_error(exc):
                raise
            wait = _STAGE_RETRY_DELAY * attempt
            print(
                f"[thrace] transient provider error in {context} "
                f"(attempt {attempt}/{_STAGE_MAX_ATTEMPTS}); retrying in {wait}s — "
                f"{str(exc)[:200]}",
                flush=True,
            )
            time.sleep(wait)


# ---------------------------------------------------------------------------
# Analysis prompts
# ---------------------------------------------------------------------------
ANALYSIS_TYPES = {"competitor", "sentiment", "metrics"}


def bullets_prompt(analysis_type: str, company: str) -> str:
    if analysis_type == "competitor":
        return (
            f"Generate up to 16 evidence-based insight bullets about {company}'s most recent "
            f"product launches.\nFormat requirements:\n"
            f"- Start every bullet with exactly one tag: Positioning | Strength | Weakness | Learning\n"
            f"- Follow the tag with a concise statement (max 30 words) referencing concrete "
            f"observations: messaging, differentiation, pricing, channel selection, timing, "
            f"engagement metrics, or customer feedback."
        )
    if analysis_type == "sentiment":
        return (
            f"Summarize market sentiment for {company} in <=10 bullets. Cover top positive & "
            f"negative themes with source mentions (G2, Reddit, Twitter, customer reviews)."
        )
    return (
        f"List (max 10 bullets) the most important publicly available KPIs & qualitative signals "
        f"for {company}'s recent product launches. Include engagement stats, press coverage, "
        f"adoption metrics, and market traction data if available."
    )


def expand_prompt(analysis_type: str, company: str, bullets: str) -> str:
    if analysis_type == "competitor":
        return dedent(f"""
            Transform the insight bullets below into a professional launch review for product
            managers analysing {company}.
            Produce well-structured **Markdown** with a mix of tables, call-outs and concise
            bullet points -- avoid long paragraphs.
            === FORMAT SPECIFICATION ===
            # {company} -- Launch Review
            ## 1. Market & Product Positioning
            - Bullet point summary of how the product is positioned (max 6 bullets).
            ## 2. Launch Strengths
            | Strength | Evidence / Rationale |
            |---|---|
            | ... | ... | (add 4-6 rows)
            ## 3. Launch Weaknesses
            | Weakness | Evidence / Rationale |
            |---|---|
            | ... | ... | (add 4-6 rows)
            ## 4. Strategic Takeaways for Competitors
            1. ... (max 5 numbered recommendations)
            === SOURCE BULLETS ===
            {bullets}
            Guidelines:
            - Populate the tables with specific points derived from the bullets.
            - Only include rows that contain meaningful data; omit any blank entries.
        """)
    if analysis_type == "sentiment":
        return dedent(f"""
            Use the tagged bullets below to create a concise market-sentiment brief for {company}.
            ### Positive Sentiment
            - List each positive point as a separate bullet (max 6).
            ### Negative Sentiment
            - List each negative point as a separate bullet (max 6).
            ### Overall Summary
            Provide a short paragraph (<=120 words) summarising the overall sentiment balance and
            key drivers.
            Tagged Bullets:
            {bullets}
        """)
    return dedent(f"""
        Convert the KPI bullets below into a launch-performance snapshot for {company} suitable
        for an executive dashboard.
        ## Key Performance Indicators
        | Metric | Value / Detail | Source |
        |---|---|---|
        | ... | ... | ... |  (include one row per KPI)
        ## Qualitative Signals
        - Bullet list of notable qualitative insights (max 5).
        ## Summary & Implications
        Brief paragraph (<=120 words) highlighting what the metrics imply about launch success and
        next steps.
        KPI Bullets:
        {bullets}
    """)


_xray_agents: dict[str, Agent] | None = None
_xray_report_agent: Agent | None = None


def build_xray_agents() -> dict[str, Agent]:
    """Build (or return cached) the X-Ray agents, keyed by analysis type.

    The X-Ray modes call the relevant specialist directly instead of routing
    through the `Team` supervisor: a single-request team run costs an extra
    round of leader model calls without adding analysis. `build_team()` is
    still built for the agent roster on /api/health.
    """
    global _xray_agents
    if _xray_agents is None:
        _xray_agents = {
            "competitor": _competitor_agent(),
            "sentiment": _sentiment_agent(),
            "metrics": _metrics_agent(),
        }
    return _xray_agents


def _build_xray_report_agent() -> Agent:
    """Formats gathered bullets into the final X-Ray report (no tools — fast)."""
    global _xray_report_agent
    if _xray_report_agent is None:
        _xray_report_agent = Agent(
            name="Thrace X-Ray Analyst",
            description=dedent("""
                You turn gathered evidence bullets into a polished, structured
                intelligence report. You add nothing that is not supported by
                the bullets you are given — you structure, tighten and format.
            """),
            model=_chat_model(),
            markdown=True,
        )
    return _xray_report_agent


def run_bullets(analysis_type: str, company: str) -> str:
    """Non-streaming first pass producing evidence-based insight bullets."""
    prompt = bullets_prompt(analysis_type, company)
    return _run_with_retries(
        lambda: _check_run(
            build_xray_agents()[analysis_type].run(prompt),
            "Evidence gathering failed",
        ),
        "Evidence gathering",
    )


def stream_report(analysis_type: str, company: str, bullets: str) -> Iterator[dict]:
    """Stream the expanded Markdown report as SSE-ready event dicts.

    Events: delta (report text) and reset (the client should clear its
    accumulated text because generation is restarting). Mid-stream transient
    failures restart generation from scratch — with round-robin at the model
    layer this is a rare backstop, not the normal path.
    """
    prompt = expand_prompt(analysis_type, company, bullets)
    emitted = False
    attempt = 0
    while True:
        attempt += 1
        failure: Exception | None = None
        for event in _build_xray_report_agent().run(prompt, stream=True):
            if isinstance(event, RunContentEvent):
                delta = event.content
                if delta:
                    emitted = True
                    yield {"type": "delta", "data": delta}
            elif isinstance(event, RunContentCompletedEvent):
                continue
            elif isinstance(event, RunErrorEvent):
                failure = RuntimeError(
                    f"Report generation failed: "
                    f"{event.content or event.error_type or 'unknown'}"
                )
                break
        if failure is None:
            return
        if attempt < _STAGE_MAX_ATTEMPTS and _is_transient_error(failure):
            if emitted:
                yield {"type": "reset"}
                emitted = False
            global _xray_report_agent
            _xray_report_agent = None
            wait = _STAGE_RETRY_DELAY * attempt
            print(
                f"[thrace] transient provider error in report generation "
                f"(attempt {attempt}/{_STAGE_MAX_ATTEMPTS}); restarting in {wait}s — "
                f"{str(failure)[:200]}",
                flush=True,
            )
            time.sleep(wait)
            continue
        raise failure


_XRAY_FOCUS = {
    "competitor": "its market positioning, recent launches, strengths and weaknesses",
    "sentiment": "how the market perceives it — the positive and negative drivers",
    "metrics": "its publicly visible performance metrics and growth signals",
}


def xray_provisional(analysis_type: str, company: str) -> Iterator[dict]:
    """Instant preliminary read for a Company X-Ray run.

    Streams delta events before research starts; the caller clears them with a
    `reset` once the researched report begins (see `_stream_provisional`).
    """
    focus = _XRAY_FOCUS.get(analysis_type, "its market position")
    return _stream_provisional(
        "Thrace Quick Read",
        dedent("""
            You give an immediate, honest first impression of a company before
            any research has been done. You are concise and never invent
            figures, metrics or sources.
        """),
        dedent(f"""
            Give your immediate preliminary read on {company}, focused on {focus}.

            Under 100 words: one bold line, then the single most notable strength
            and the single most notable concern.

            Markdown, no headings, no sources — a first impression only.
        """),
    )


# ---------------------------------------------------------------------------
# Venture Intelligence pipeline (primary feature)
# ---------------------------------------------------------------------------
VENTURE_STAGES = [
    {"id": "validation", "label": "Idea Validation",
     "detail": "Checking problem evidence and demand signals"},
    {"id": "market", "label": "Market & Location Intelligence",
     "detail": "Sizing the market and profiling customers"},
    {"id": "competition", "label": "Competitive Landscape",
     "detail": "Mapping local and online competitors"},
    {"id": "risk", "label": "Risk & Success Assessment",
     "detail": "Scoring risk and probability of success"},
    {"id": "plan", "label": "Venture Plan & Roadmap",
     "detail": "Building the venture plan and roadmap"},
]


def _validation_agent() -> Agent:
    return Agent(
        name="Venture Validation Agent",
        description=dedent("""
            You are a ruthless but fair venture validation analyst. Your job is to
            determine whether a business idea solves a real, painful problem with
            demonstrable demand — before anyone spends money on it.
            You investigate:
            - Evidence the problem exists and is painful (forums, news, statistics)
            - Demand signals: search interest, discussions, traction of existing
              solutions, informal/local market signals
            - Whether the idea is specific enough to test, and what is ambiguous
            You conclude with a verdict: PURSUE, PIVOT or DROP, backed by evidence.
            IMPORTANT: Cite source URLs inline and end with a 'Sources:' section.
        """),
        model=_chat_model(),
        tools=[TOOLS()],
        markdown=True,
        exponential_backoff=True,
        delay_between_retries=2,
    )


def _market_agent() -> Agent:
    return Agent(
        name="Market Intelligence Agent",
        description=dedent("""
            You are a market research analyst specialising in emerging markets and
            local economies, especially Nigeria and African cities.
            For a given business idea and location you estimate:
            - Market size (TAM / SAM / SOM) with clearly stated assumptions
            - Target customer segments with personas and willingness to pay
            - Local economic context: population, commerce, income levels, infrastructure
            - Pricing tolerance: what customers currently pay for alternatives
            All monetary figures in local currency (₦ for Nigeria).
            IMPORTANT: Cite source URLs inline and end with a 'Sources:' section.
        """),
        model=_chat_model(),
        tools=[TOOLS()],
        markdown=True,
        exponential_backoff=True,
        delay_between_retries=2,
    )


def _competition_agent() -> Agent:
    return Agent(
        name="Competition Analysis Agent",
        description=dedent("""
            You are a competitive intelligence analyst. For a business idea and its
            target location you map:
            - Direct competitors operating in that location (offering, pricing,
              strengths, gaps)
            - Indirect competitors: other ways customers solve the same problem,
              including informal-sector and DIY alternatives
            - Online / delivery competitors serving the same need remotely
            - White space: differentiation openings a new entrant could exploit
            You are especially attentive to local small businesses, not just big brands.
            IMPORTANT: Cite source URLs inline and end with a 'Sources:' section.
        """),
        model=_chat_model(),
        tools=[TOOLS()],
        markdown=True,
        exponential_backoff=True,
        delay_between_retries=2,
    )


def _risk_agent() -> Agent:
    return Agent(
        name="Risk & Success Agent",
        description=dedent("""
            You are a venture risk analyst who scores the probability of success of
            business ideas using a weighted rubric. You are quantitative, calibrated
            and honest — you never inflate scores to please the founder.
            You score each dimension 0-10 (10 = most favourable to the venture):
            - Market demand evidence (weight 25%)
            - Competitive intensity, inverse: less competition = higher (weight 20%)
            - Execution complexity, inverse: simpler = higher (weight 15%)
            - Capital accessibility (weight 15%)
            - Location & regulatory fit (weight 15%)
            - Timing / trend alignment (weight 10%)
            You compute the weighted total as a percentage and band it:
            >=70% Strong, 50-69% Promising, 35-49% Speculative, <35% High-risk.
            You also produce a SWOT and a risk register with mitigations.
        """),
        model=_chat_model(),
        tools=[TOOLS()],
        markdown=True,
        exponential_backoff=True,
        delay_between_retries=2,
    )


def _planning_agent() -> Agent:
    return Agent(
        name="Venture Planning Agent",
        description=dedent("""
            You are a pragmatic venture planner who turns validated ideas into
            execution-ready plans for resource-constrained founders in emerging
            markets. You produce:
            - Recommended business model and revenue streams
            - Itemised lean startup cost estimates in local currency (₦ for Nigeria)
            - Realistic funding options (savings, cooperatives, microfinance, angels, grants)
            - A go-to-market strategy and a "first 100 customers" plan
            - A phased roadmap: 0-90 days and 3-12 months
            - Regulatory checklist (e.g., CAC registration for Nigeria, sector permits, tax)
            - KPIs to track from day one
            Plans must be concrete, sequenced and affordable — no generic advice.
            IMPORTANT: Cite source URLs inline and end with a 'Sources:' section.
        """),
        model=_chat_model(),
        tools=[TOOLS()],
        markdown=True,
        exponential_backoff=True,
        delay_between_retries=2,
    )


_venture_agents: dict[str, Agent] | None = None
_synthesis_agent: Agent | None = None


def build_venture_agents() -> dict[str, Agent]:
    """Build (or return cached) the five venture pipeline agents."""
    global _venture_agents
    if _venture_agents is None:
        _venture_agents = {
            "validation": _validation_agent(),
            "market": _market_agent(),
            "competition": _competition_agent(),
            "risk": _risk_agent(),
            "plan": _planning_agent(),
        }
    return _venture_agents


def _clear_synthesis_agent() -> None:
    """Drop the cached synthesis agent so the next build picks up the active model."""
    global _synthesis_agent
    _synthesis_agent = None


# ---------------------------------------------------------------------------
# Autonomous agents: self-critique, monitoring, discovery, report Q&A, digest
# ---------------------------------------------------------------------------
def _critic_agent() -> Agent:
    return Agent(
        name="Evidence Critic Agent",
        description=dedent("""
            You are a strict evidence reviewer. You read a stage brief produced by
            a research agent and judge whether its evidence is sufficient to support
            its claims. You do not rewrite the brief — you only assess it.
            Respond with EXACTLY one of:
            SUFFICIENT
            or
            REVISE: <one or two sentences naming the specific missing evidence or
            weak claims, and what additional research would fix them>
            Be demanding but practical: briefs citing concrete sources, figures and
            named competitors are usually sufficient. Flag briefs that lean on
            assumptions, lack local specifics, or make unquantified claims.
        """),
        model=_chat_model(),
        markdown=False,
    )


def _monitor_agent() -> Agent:
    return Agent(
        name="Monitoring Agent",
        description=dedent("""
            You are a continuous-monitoring intelligence agent. You re-check a
            previously analysed business idea or company for what has CHANGED since
            the last report — not a full re-analysis, only the deltas.
            You search for recent news, new entrants, pricing moves, regulatory
            changes, funding events and demand shifts, then report:
            1. WHAT CHANGED — bullets of concrete developments with dates where known.
            2. IMPLICATIONS — how the changes affect the earlier verdict, score or plan.
            3. RECOMMENDED ACTION — monitor / re-validate / adjust plan.
            Keep it under 250 words. Cite source URLs inline and end with a
            'Sources:' section. If nothing material changed, say so plainly.
        """),
        model=_chat_model(),
        tools=[TOOLS()],
        markdown=True,
        exponential_backoff=True,
        delay_between_retries=2,
    )


DISCOVERY_MAX_IDEAS = int(os.getenv("DISCOVERY_MAX_IDEAS", "4"))


def _discovery_agent() -> Agent:
    return Agent(
        name="Opportunity Discovery Agent",
        description=dedent("""
            You are an opportunity discovery agent. You scan live news, trend
            reports and local market signals to PROPOSE business ideas worth
            validating — you find opportunities, you do not validate them.
            For a given location or sector focus, search for: emerging demand,
            supply gaps, policy changes, infrastructure shifts and rising consumer
            trends. Then propose exactly four concrete, specific ideas — never
            more than four.
            Keep the scan tight: run at most four searches, then write up the
            ideas you have evidence for.
            Output STRICTLY in this format, one block per idea:
            ### {Short title}
            idea: {one-line business idea, specific enough to validate, including location}
            why: {2-3 sentences of evidence why NOW — cite the signals found}
            Each 'idea:' line must be directly runnable as a venture validation
            prompt. Cite source URLs in the 'why:' text.
        """),
        model=_chat_model(),
        tools=[TOOLS()],
        markdown=True,
        exponential_backoff=True,
        delay_between_retries=2,
    )


def _qa_agent() -> Agent:
    return Agent(
        name="Report Q&A Agent",
        description=dedent("""
            You answer follow-up questions about an intelligence report strictly
            from the report content you are given. You add nothing that is not
            supported by the report; if the report does not contain the answer,
            say so and point to what it does cover. Keep answers concise
            (under 200 words), grounded, and reference the report's sections or
            figures when useful.
        """),
        model=_chat_model(),
        markdown=True,
    )


def _digest_agent() -> Agent:
    return Agent(
        name="Digest Analyst",
        description=dedent("""
            You assemble a periodic intelligence digest from monitoring updates.
            Given a set of monitoring briefs, produce a compact markdown digest:
            a one-line overview, then per item: the subject, what changed and the
            recommended action. No new research — only what the briefs state.
        """),
        model=_chat_model(),
        markdown=True,
    )


def build_synthesis_agent() -> Agent:
    """Lead analyst that assembles the final report from stage briefs (no tools — fast)."""
    global _synthesis_agent
    if _synthesis_agent is None:
        _synthesis_agent = Agent(
            name="Thrace Lead Analyst",
            description=dedent("""
                You are the lead analyst of the Thrace Venture Intelligence Team.
                You transform the stage briefs produced by your specialist agents
                into one polished, evidence-backed Venture Intelligence Report.
                You add nothing that is not supported by the briefs — you structure,
                tighten and format. You preserve all scores, verdicts and figures
                exactly as the specialists assessed them.
            """),
            model=_chat_model(),
            markdown=True,
        )
    return _synthesis_agent


# ---------------------------------------------------------------------------
# Venture prompts
# ---------------------------------------------------------------------------
_BRIEF_RULES = dedent("""
    Output rules for this stage brief:
    - Concise markdown, bullet points over prose, no filler.
    - Cite source URLs inline where evidence supports a claim.
    - Every factual claim must trace to something you found or were given.
    - End with a 'Sources:' section listing all URLs searched or crawled.
    - Keep the brief under 450 words.
    - Research efficiently: at most 2 web searches, and do not crawl pages.
      Each extra search costs a model request against a tight quota.
""")


def _prior_context(findings: dict[str, str]) -> str:
    if not findings:
        return "(This is the first stage — no prior findings yet.)"
    parts = []
    for stage in VENTURE_STAGES:
        if stage["id"] in findings:
            parts.append(f"### Prior stage: {stage['label']}\n{findings[stage['id']]}")
    return "\n\n".join(parts)


def venture_stage_prompt(stage_id: str, idea: str, findings: dict[str, str]) -> str:
    prior = _prior_context(findings)
    if stage_id == "validation":
        return dedent(f"""
            Validate this business idea: "{idea}"

            Investigate and report:
            1. PROBLEM — Is there a real, painful problem here? Evidence it exists.
            2. DEMAND — Search interest, discussions, traction of existing solutions,
               local demand signals for the stated market/location if given.
            3. CLARITY — Is the idea specific enough to test? Note any ambiguity.
            4. VERDICT — PURSUE / PIVOT / DROP with 2-3 sentences of reasoning.

            {_BRIEF_RULES}
        """)
    if stage_id == "market":
        return dedent(f"""
            Produce a market brief for this business idea: "{idea}"

            Using web research and the prior validation findings:
            1. MARKET SIZE — Localised TAM / SAM / SOM estimates with stated
               assumptions (₦ where the market is Nigeria).
            2. CUSTOMERS — 2-3 target segments, one line each: who, need,
               willingness to pay.
            3. LOCATION CONTEXT — Population, commerce, income levels and relevant
               infrastructure of the target location.
            4. PRICING TOLERANCE — What customers currently pay for alternatives;
               suggested price range for the new venture.

            === PRIOR FINDINGS ===
            {prior}

            {_BRIEF_RULES}
        """)
    if stage_id == "competition":
        return dedent(f"""
            Map the competitive landscape for this business idea: "{idea}"

            Using web research and the prior findings:
            1. DIRECT COMPETITORS — Businesses offering similar value in the target
               location. For each: name, offering, pricing (if findable), strength, gap.
            2. INDIRECT COMPETITORS — Other ways customers solve the problem,
               including informal-sector and DIY alternatives.
            3. ONLINE / DELIVERY competitors serving the same need remotely.
            4. WHITE SPACE — 2-3 differentiation openings the venture could exploit.

            === PRIOR FINDINGS ===
            {prior}

            {_BRIEF_RULES}
        """)
    if stage_id == "risk":
        return dedent(f"""
            Assess risk and probability of success for this business idea: "{idea}"

            Using web research where needed and the prior findings, score each
            dimension 0-10 (10 = most favourable) and compute the weighted total:
            | Dimension | Weight |
            | Market demand evidence | 25% |
            | Competitive intensity (inverse) | 20% |
            | Execution complexity (inverse) | 15% |
            | Capital accessibility | 15% |
            | Location & regulatory fit | 15% |
            | Timing / trend alignment | 10% |

            Produce:
            1. SCORING TABLE — dimension | score | weight | one-line rationale.
            2. PROBABILITY OF SUCCESS — weighted percentage and band
               (>=70% Strong, 50-69% Promising, 35-49% Speculative, <35% High-risk).
               Show the arithmetic.
            3. SWOT — 3-4 bullets per quadrant.
            4. RISK REGISTER — top 5 risks: risk | likelihood H/M/L | impact H/M/L | mitigation.

            === PRIOR FINDINGS ===
            {prior}

            {_BRIEF_RULES}
        """)
    return dedent(f"""
        Create the venture plan and roadmap for this business idea: "{idea}"

        Using web research where needed and the prior findings:
        1. BUSINESS MODEL — Recommended model and revenue streams.
        2. STARTUP COSTS — Itemised lean-scenario estimate table (₦ for Nigeria).
        3. FUNDING — Realistic options for this context (savings, cooperatives,
           microfinance, angels, grants).
        4. GO-TO-MARKET — Launch strategy, first channels, first-100-customers plan.
        5. ROADMAP — Phase 1 (0-90 days) and Phase 2 (3-12 months) with milestones.
        6. REGULATORY — Required registrations and licences (e.g., CAC business name
           registration for Nigeria, sector permits, tax obligations).
        7. KPIs — 5-7 metrics to track from day one.

        === PRIOR FINDINGS ===
        {prior}

        {_BRIEF_RULES}
    """)


def venture_report_prompt(idea: str, findings: dict[str, str]) -> str:
    prior = _prior_context(findings)
    return dedent(f"""
        Transform the five stage briefs below into the final Venture Intelligence
        Report for the idea: "{idea}"

        === FORMAT SPECIFICATION ===
        # Venture Intelligence Report — {idea}
        ## Executive Verdict
        One bold line with the verdict (PURSUE / PIVOT / DROP), the probability-of-success
        percentage and its band. Then <=80 words of overall reasoning.
        ## 1. Idea Validation
        Problem evidence, demand signals, validation verdict & reasoning (concise bullets).
        ## 2. Market & Location Intelligence
        TAM/SAM/SOM table, customer segments, local context, pricing tolerance.
        ## 3. Competitive Landscape
        Competitor table (name | offering | pricing | strength | gap), then white-space summary.
        ## 4. Risk & Success Assessment
        Scoring table, SWOT, risk register (risk | likelihood | impact | mitigation).
        ## 5. Venture Plan & Roadmap
        Business model, startup costs table, funding options, go-to-market,
        0-90-day and 3-12-month roadmap, regulatory checklist, KPIs.
        ## Sources
        All URLs from the stage briefs, deduplicated, one per line.

        === STAGE BRIEFS ===
        {prior}

        Guidelines:
        - Use tables where specified, concise bullets elsewhere; no long paragraphs.
        - Only include rows and entries with meaningful content; omit blanks.
        - Preserve the probability-of-success percentage, band and verdict EXACTLY
          as assessed in the Risk & Success brief.
        - Do not invent facts, figures or sources not present in the briefs.
    """)


# ---------------------------------------------------------------------------
# Venture pipeline runner
# ---------------------------------------------------------------------------
# Wall-clock ceiling for the research phase of a run. Sized so both waves
# (validation, then the other four in parallel) finish with room to spare; a
# stage still outstanding when it expires is abandoned and the report names the
# gap, so a run can never sprawl into the multi-minute failures we shipped
# before. Override with VENTURE_BUDGET_SECONDS.
_VENTURE_BUDGET_SECONDS = float(os.getenv("VENTURE_BUDGET_SECONDS", "180"))
_XRAY_BUDGET_SECONDS = float(os.getenv("XRAY_BUDGET_SECONDS", "120"))
# Revisions are full extra research passes — by far the most expensive thing a
# run does. Capped per run so one demanding stage cannot consume the whole
# daily request quota (the free tier allows only 20 requests/model/day).
_MAX_REVISIONS_PER_RUN = int(os.getenv("MAX_REVISIONS_PER_RUN", "2"))
# Skip a revision when this little budget is left: it cannot finish in time.
_REVISION_MIN_SECONDS = float(os.getenv("REVISION_MIN_SECONDS", "25"))


class _RevisionBudget:
    """Thread-safe cap on how many stages a single run may send back."""

    def __init__(self, limit: int) -> None:
        self._remaining = limit
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            if self._remaining <= 0:
                return False
            self._remaining -= 1
            return True


def _stream_provisional(name: str, description: str, prompt: str) -> Iterator[dict]:
    """Stream an immediate preliminary read, before any research runs.

    This is what makes the app feel like a chat product: first tokens reach the
    client in ~1-2s instead of after the entire pipeline. The text is explicitly
    provisional and is discarded (via a `reset` event) the moment the
    evidence-backed report starts streaming.
    """
    try:
        agent = Agent(
            name=name,
            description=description,
            model=_chat_model(),
            markdown=True,
        )
        for event in agent.run(prompt, stream=True):
            if isinstance(event, AgentRunContentEvent):
                if event.content:
                    yield {"type": "delta", "data": event.content}
            elif isinstance(event, AgentRunErrorEvent):
                return
    except Exception as exc:  # noqa: BLE001
        # A failed preliminary read must never fail the run.
        print(f"[thrace] provisional draft unavailable: {str(exc)[:160]}", flush=True)


def _research_stage(
    stage: dict,
    idea: str,
    prior: dict[str, str],
    emit: Callable[[dict], None],
    revision_budget: _RevisionBudget,
    deadline: float,
) -> str:
    """Run one stage to completion: brief, self-critique, and any revision.

    Executed on a worker thread, so the critique (and revision) overlap the
    other stages instead of serialising behind them.
    """
    stage_id, label = stage["id"], stage["label"]
    started = time.monotonic()
    brief = _run_with_retries(
        lambda: _check_run(
            build_venture_agents()[stage_id].run(
                venture_stage_prompt(stage_id, idea, prior)
            ),
            f"{label} stage failed",
        ),
        f"{label} stage",
    )
    print(
        f"[thrace] {label}: brief in {time.monotonic() - started:.1f}s",
        flush=True,
    )

    # Self-critique loop: a reviewer judges the brief's evidence; a REVISE
    # verdict sends the stage agent back for the specific gaps (adaptive
    # research budget — extra searches only where evidence is thin).
    try:
        critique = _run_with_retries(
            lambda: _check_run(
                _critic_agent().run(
                    f"Stage: {label}\nSubject: {idea}\n\n=== BRIEF ===\n{brief}"
                ),
                f"{label} critique failed",
            ),
            f"{label} critique",
        ).strip()
    except Exception as exc:  # noqa: BLE001
        print(f"[thrace] critique skipped for {label}: {str(exc)[:160]}", flush=True)
        return brief

    if not critique.upper().startswith("REVISE"):
        print(
            f"[thrace] {label}: done in {time.monotonic() - started:.1f}s", flush=True
        )
        return brief

    # A revision is a full extra research pass. Only spend on it when the run
    # can still afford the time, and when this run's revision budget allows.
    if (
        time.monotonic() > deadline - _REVISION_MIN_SECONDS
        or not revision_budget.take()
    ):
        print(
            f"[thrace] {label}: revision skipped (budget/quota) — keeping first brief",
            flush=True,
        )
        return brief

    emit(
        {
            "type": "status",
            "label": "Deepening research",
            "detail": f"Reviewer found evidence gaps in {label} — re-researching",
        }
    )
    revision_prompt = dedent(f"""
        Your earlier brief for "{idea}" was reviewed and judged insufficient:

        REVIEWER VERDICT: {critique}

        Original brief:
        {brief}

        Produce a REVISED brief addressing the reviewer's specific gaps.
        Run additional targeted web searches to fill the missing evidence
        (you may search multiple times with different queries). Keep the
        same output structure as the original brief and stay under 450 words.
        Cite source URLs inline and end with a 'Sources:' section.
    """)
    try:
        revised = _run_with_retries(
            lambda: _check_run(
                build_venture_agents()[stage_id].run(revision_prompt),
                f"{label} revision failed",
            ),
            f"{label} revision",
        )
        print(
            f"[thrace] {label}: revised in {time.monotonic() - started:.1f}s",
            flush=True,
        )
        return revised
    except Exception as exc:  # noqa: BLE001
        # Keep the original brief rather than losing the stage entirely.
        print(f"[thrace] revision skipped for {label}: {str(exc)[:160]}", flush=True)
        return brief


def _run_wave(
    stages: list[dict],
    idea: str,
    findings: dict[str, str],
    deadline: float,
    revision_budget: _RevisionBudget,
) -> Iterator[dict]:
    """Run a set of stages concurrently, yielding progress then results.

    Every stage is announced up front (they really are running in parallel),
    then stage_done is emitted as each finishes. Work still outstanding at
    `deadline` is abandoned and reported instead of hanging the run.
    """
    for stage in stages:
        yield {
            "type": "stage_start",
            "stage": stage["id"],
            "label": stage["label"],
            "detail": stage["detail"],
        }

    events: queue.Queue = queue.Queue()
    # Snapshot the prior findings: stages in the same wave must not read each
    # other's output, or their results would depend on completion order.
    prior = dict(findings)
    pool = ThreadPoolExecutor(max_workers=len(stages))
    try:
        futures = {
            pool.submit(
                _research_stage, stage, idea, prior, events.put, revision_budget, deadline
            ): stage
            for stage in stages
        }
        finished: set[str] = set()
        remaining = deadline - time.monotonic()
        try:
            for future in as_completed(futures, timeout=max(remaining, 1.0)):
                stage = futures[future]
                finished.add(stage["id"])
                try:
                    findings[stage["id"]] = future.result()
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[thrace] {stage['label']} stage failed: {str(exc)[:200]}",
                        flush=True,
                    )
                    yield {
                        "type": "status",
                        "label": "Stage failed",
                        "detail": f"{stage['label']}: {str(exc)[:160]}",
                    }
                yield {"type": "stage_done", "stage": stage["id"]}
        except TimeoutError:
            pass

        # Drain progress events (e.g. "deepening research") emitted while waiting.
        while True:
            try:
                yield events.get_nowait()
            except queue.Empty:
                break

        for stage in stages:
            if stage["id"] not in finished:
                print(
                    f"[thrace] budget exhausted before {stage['label']} finished",
                    flush=True,
                )
                yield {
                    "type": "status",
                    "label": "Research budget reached",
                    "detail": (
                        f"{stage['label']} did not finish in time — "
                        "the report notes the gap"
                    ),
                }
    finally:
        # Never block on stragglers; abandoned work finishes off the hot path.
        pool.shutdown(wait=False, cancel_futures=True)


def _stream_synthesis(prompt: str) -> Iterator[dict]:
    """Stream the final report, restarting generation on transient failure."""
    emitted_deltas = False
    attempt = 0
    while True:
        attempt += 1
        failure: Exception | None = None
        for event in build_synthesis_agent().run(prompt, stream=True):
            if isinstance(event, AgentRunContentEvent):
                if event.content:
                    emitted_deltas = True
                    yield {"type": "delta", "data": event.content}
            elif isinstance(event, AgentRunErrorEvent):
                failure = RuntimeError(
                    f"Report synthesis failed: {event.content or event.error_type or 'unknown'}"
                )
                break
        if failure is None:
            return
        if attempt < _STAGE_MAX_ATTEMPTS and _is_transient_error(failure):
            # Mid-stream failure: restart generation from scratch. The reset
            # event tells the client to drop the partial report text.
            if emitted_deltas:
                yield {"type": "reset"}
                emitted_deltas = False
            _clear_synthesis_agent()
            wait = _STAGE_RETRY_DELAY * attempt
            print(
                f"[thrace] transient provider error in report synthesis "
                f"(attempt {attempt}/{_STAGE_MAX_ATTEMPTS}); restarting in {wait}s — "
                f"{str(failure)[:200]}",
                flush=True,
            )
            time.sleep(wait)
            continue
        raise failure


def run_venture_pipeline(idea: str) -> Iterator[dict]:
    """Run the 5-stage venture pipeline, yielding SSE-ready event dicts.

    Shape: an instant provisional read, then research in two waves (validation;
    then the other four concurrently), then the final report streams. Events:
    status / stage_start / stage_done while researching, then
    stage_start("report") followed by delta events.
    """
    started = time.monotonic()
    deadline = started + _VENTURE_BUDGET_SECONDS
    findings: dict[str, str] = {}
    revision_budget = _RevisionBudget(_MAX_REVISIONS_PER_RUN)

    # 1. Instant preliminary read — something on screen within ~1-2s.
    yield {
        "type": "status",
        "label": "Preliminary read",
        "detail": "Drafting an immediate first impression before research runs…",
    }
    yield from _stream_provisional(
        "Thrace Quick Read",
        dedent("""
            You give founders an immediate, honest first read on a business idea
            before any research has been done. You are concise, specific and
            never invent figures, market sizes or sources.
        """),
        dedent(f"""
            A founder is considering this venture: "{idea}"

            Give your immediate preliminary read in under 120 words:
            - one bold verdict line (looks promising / needs work / weak)
            - the single biggest opportunity
            - the single biggest risk

            Markdown, no headings, no sources — a seasoned investor's gut read.
        """),
    )

    # 2. Wave 1 — validation establishes the base case every later stage reads.
    yield from _run_wave([VENTURE_STAGES[0]], idea, findings, deadline, revision_budget)

    # 3. Wave 2 — the remaining four stages run concurrently. This is the main
    #    speed win: five sequential stages become two waves.
    yield from _run_wave(
        VENTURE_STAGES[1:], idea, findings, deadline, revision_budget
    )

    # 4. Final report — drop the provisional text, stream the researched one.
    yield {"type": "reset"}
    yield {
        "type": "stage_start",
        "stage": "report",
        "label": "Synthesising report",
        "detail": "Lead analyst assembling the Venture Intelligence Report",
    }
    prompt = venture_report_prompt(idea, findings)
    missing = [s["label"] for s in VENTURE_STAGES if s["id"] not in findings]
    if missing:
        prompt += dedent(f"""

            NOTE: These research stages did not complete in time: {", ".join(missing)}.
            Write the report from the briefs you have, and add a single line under
            "Executive Verdict" headed "Research gaps" naming the missing sections
            so the reader knows what was not covered.
        """)
    print(
        f"[thrace] venture research done in {time.monotonic() - started:.1f}s "
        f"({len(findings)}/5 stages); synthesising",
        flush=True,
    )
    yield from _stream_synthesis(prompt)



# ---------------------------------------------------------------------------
# Autonomous runners: monitoring, discovery, report Q&A, digest
# ---------------------------------------------------------------------------
def monitor_report(query: str, prior_report: str | None) -> str:
    """Re-validate a watched subject: what changed since the last report."""
    prior = (prior_report or "")[:4000]
    prompt = dedent(f"""
        Re-validate this previously analysed subject: "{query}"

        === CONDENSED PREVIOUS REPORT ===
        {prior or "(no previous report stored — do a fresh light scan)"}

        Search for developments SINCE the previous analysis: news, new
        competitors, pricing moves, regulation, funding, demand shifts.
        Report only the deltas (what changed, implications, recommended
        action), under 250 words, with sources.
    """)
    return _run_with_retries(
        lambda: _check_run(
            _monitor_agent().run(prompt), "Monitoring run failed"
        ),
        "Monitoring",
    )


def run_discovery(focus: str) -> Iterator[dict]:
    """Scan live signals and propose ideas worth validating.

    Streams the scan log as deltas. Each idea is emitted the moment its block
    is finished rather than once the whole scan is over, so cards (and their
    validate buttons) appear while the agent is still searching. At most
    `DISCOVERY_MAX_IDEAS` ideas are produced.
    """
    focus_line = f"Focus: {focus}" if focus else "Focus: Nigeria (any high-potential sector)"
    prompt = dedent(f"""
        Scan today's news, trends and local market signals and propose exactly
        {DISCOVERY_MAX_IDEAS} business ideas worth validating. {focus_line}
        Keep the scan tight — run at most {DISCOVERY_MAX_IDEAS} searches — then
        propose the ideas in the required format. Search for emerging demand,
        supply gaps, policy changes, infrastructure shifts and rising consumer
        trends first.
    """)
    yield {"type": "status", "label": "Scanning live signals", "detail": "Searching news, trends and market signals…"}

    content = ""
    failure: Exception | None = None
    emitted = 0
    consumed = 0

    def drain_finished_blocks() -> Iterator[dict]:
        """Emit every idea block the agent has finished writing so far."""
        nonlocal consumed, emitted
        blocks, _ = _split_idea_blocks(content)
        while consumed < len(blocks) and emitted < DISCOVERY_MAX_IDEAS:
            block = blocks[consumed]
            consumed += 1
            idea = _parse_idea_block(block)
            if idea is not None:
                emitted += 1
                yield idea

    for event in _discovery_agent().run(prompt, stream=True):
        if isinstance(event, AgentRunContentEvent):
            if event.content:
                content += event.content
                yield {"type": "delta", "data": event.content}
                for idea in drain_finished_blocks():
                    yield {"type": "idea", **idea}
        elif isinstance(event, AgentRunErrorEvent):
            failure = RuntimeError(
                f"Discovery scan failed: {event.content or event.error_type or 'unknown'}"
            )
    if failure is not None:
        raise failure

    if not content.strip():
        # The streamed run produced nothing — retry once without streaming.
        content = _run_with_retries(
            lambda: _check_run(_discovery_agent().run(prompt), "Discovery scan failed"),
            "Discovery",
        )
        for idea in drain_finished_blocks():
            yield {"type": "idea", **idea}

    # The final block has no following header to close it, so flush the rest.
    finished, tail = _split_idea_blocks(content)
    remaining = finished[consumed:]
    if tail.strip():
        remaining = [*remaining, tail]
    for block in remaining:
        if emitted >= DISCOVERY_MAX_IDEAS:
            break
        idea = _parse_idea_block(block)
        if idea is not None:
            emitted += 1
            yield {"type": "idea", **idea}

    if emitted == 0:
        # Some models drift from the '### ' format — fall back to a lenient pass.
        for idea in _parse_ideas(content)[:DISCOVERY_MAX_IDEAS]:
            yield {"type": "idea", **idea}

    yield {"type": "done"}


def _split_idea_blocks(content: str) -> tuple[list[str], str]:
    """Separate finished idea blocks from the one still being written.

    A block is finished once the agent has started the next `### ` header, so
    the trailing chunk is the block currently arriving.
    """
    parts = re.split(r"^###\s+", content, flags=re.MULTILINE)
    if len(parts) <= 1:
        return [], ""
    return parts[1:-1], parts[-1]


def _parse_idea_block(block: str) -> dict | None:
    """Parse one '### Title / idea: / why:' block, or None if it is not one."""
    block = block.strip()
    if not block:
        return None
    title = block.splitlines()[0].strip()
    idea_line, why_line = "", ""
    for ln in block.splitlines():
        low = ln.strip().lower()
        if low.startswith("idea:"):
            idea_line = ln.strip()[5:].strip()
        elif low.startswith("why:"):
            why_line = ln.strip()[4:].strip()
    if not idea_line:
        return None
    return {
        "title": title or idea_line[:60],
        "prompt": idea_line,
        "rationale": why_line,
    }


def _parse_ideas(content: str) -> list[dict]:
    """Lenient fallback: parse every '### ' block in a finished scan."""
    blocks = re.split(r"^###\s+", content, flags=re.MULTILINE)[1:]
    return [idea for idea in (_parse_idea_block(b) for b in blocks) if idea is not None]


def answer_question(report: str, question: str, subject: str = "") -> Iterator[dict]:
    """Answer a follow-up question strictly from the given report (streamed).

    `subject` is the chat's original query — the company or idea the report is
    about — so a long conversation stays anchored to that subject instead of
    drifting into a fresh analysis.
    """
    clipped = report[:15000]
    anchor = f" The report is about {subject.strip()}." if subject.strip() else ""
    prompt = dedent(f"""
        === INTELLIGENCE REPORT ===
        {clipped}

        === QUESTION ===
        {question}

        Answer the question using ONLY the report above.{anchor}
        If the report does not contain the answer, say so briefly — do not
        start a new analysis and do not invent findings.
    """)
    yield {"type": "status", "label": "Searching report", "detail": "Reasoning over the report's evidence…"}

    emitted = False
    failure: Exception | None = None
    for event in _qa_agent().run(prompt, stream=True):
        if isinstance(event, AgentRunContentEvent):
            if event.content:
                emitted = True
                yield {"type": "delta", "data": event.content}
        elif isinstance(event, AgentRunErrorEvent):
            failure = RuntimeError(
                f"Report Q&A failed: {event.content or event.error_type or 'unknown'}"
            )
    if failure is not None and not emitted:
        raise failure
    if not emitted:
        # A Q&A turn must never close with a blank answer on screen.
        raise RuntimeError("The report did not yield an answer — try rephrasing the question.")
    yield {"type": "done"}


def digest_report(updates: list[dict]) -> str:
    """Synthesise monitoring updates into one digest (no tools)."""
    parts = []
    for u in updates:
        parts.append(f"### {u['query']}\n{u['content'][:2500]}")
    prompt = dedent(f"""
        Assemble the periodic intelligence digest from the monitoring briefs
        below. One line of overview first, then per item: subject, what
        changed, recommended action. If a brief says nothing material
        changed, list it under 'No material change'.

        === MONITORING BRIEFS ===
        {chr(10).join(parts) if parts else "(no updates this period)"}
    """)
    return _run_with_retries(
        lambda: _check_run(_digest_agent().run(prompt), "Digest failed"),
        "Digest",
    )
