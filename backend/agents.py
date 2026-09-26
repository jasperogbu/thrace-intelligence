"""
Thrace agent engine.

Three intelligence features — Venture Intelligence, Company X-Ray and
Discovery — all run through one shared fast strategy (see `intelligence`):
a single streaming model call that reasons from the model's own knowledge,
followed by optional lightweight source retrieval that never blocks the
response.

The autonomous side (watchlist re-validation, in-app digests, report Q&A) is
unchanged and still runs on a background schedule.
"""
import os
import re
import threading
import time
from textwrap import dedent
from typing import Iterator

import intelligence
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.models.google import Gemini
from agno.tools.firecrawl import FirecrawlTools
from agno.run.agent import RunContentEvent as AgentRunContentEvent
from agno.run.agent import RunErrorEvent as AgentRunErrorEvent
from agno.run.base import RunStatus

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
# Model used when the deployment supplies a Gemini key but no explicit model id.
# Documented setup (and render.yaml) asks for GEMINI_API_KEY alone, so this is
# the path almost every install takes.
_DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"


def _default_model() -> str:
    """Choose a model id when LLM_MODEL is not set explicitly.

    `_chat_model` routes on the model id: ids beginning with "gemini" go through
    Google's native SDK, anything else through an OpenAI-compatible endpoint.
    Defaulting unconditionally to gpt-4o therefore sent a Gemini-only
    configuration down the OpenAI route, where it failed with "OPENAI_API_KEY
    not set" — while `/api/health` still reported the service ready, because the
    readiness check only looked for the presence of *a* key rather than the key
    the chosen route actually needs.

    Defaulting by the key that is present removes that class of misrouting
    entirely: a Gemini key now yields a Gemini model, and any other
    configuration keeps the historical gpt-4o default.
    """
    explicit = os.getenv("LLM_MODEL", "").strip()
    if explicit:
        return explicit
    if os.getenv("GEMINI_API_KEY"):
        return _DEFAULT_GEMINI_MODEL
    return "gpt-4o"


MODEL = _default_model()

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

# Observed latency per model, as a running mean of successful calls.
#
# The pool used to be round-robin, which is why TTFT varied from 2s to 95s on
# identical requests: the free tier serves some of these models far slower than
# others (measured on a short prompt — gemini-3.1-flash-lite ~0.8s,
# gemini-3.6-flash ~1.9s, gemini-3.5-flash ~28s, and gemini-3.8-flash spends
# most of its time in 429/503). Round-robin sent a third of all requests to the
# slow ones. Selection is now latency-aware: measured models are preferred in
# ascending order of observed time, and an unmeasured model is assumed fast so
# the pool still explores on first contact.
_latency_ms: dict[str, float] = {}
_LATENCY_SMOOTHING = 0.3  # weight of the newest sample
# Assumed latency for a model we have never successfully called, in ms. Chosen
# to sit between the fast and slow observed models so an unmeasured model is
# tried early but not ahead of one we know is quick.
_ASSUMED_LATENCY_MS = 6000.0

# Lite-tier models stay in the pool as a fallback for when every full model is
# benched, but they must not win on speed alone. Pure latency ranking put ~50%
# of traffic on gemini-3.1-flash-lite, which is a real quality drop for
# reports that depend on judgement. This penalty sorts any "-lite" model behind
# every full model regardless of how fast it is, so quality is the default and
# lite is the overflow.
_LITE_PENALTY_MS = 120000.0

# Geometric decay applied per rank when allocating traffic across the pool.
# 0.15 puts ~85% of requests on the fastest model, ~13% on the second, and
# under 2% on anything past the third.
_RANK_DECAY = 0.15

# Slow-model quarantine. A model whose time-to-first-token exceeds both of
# these is not "a slower option" for an interactive product, it is broken: on
# this tier gemini-3.5-flash measured ~28s to first token against ~0.8-2s for
# its siblings. Ranking alone still hands it double-digit traffic whenever the
# pool is small, so it is benched outright for a while and re-probed later.
_SLOW_TTFT_SECONDS = float(os.getenv("SLOW_TTFT_SECONDS", "8"))
_SLOW_QUARANTINE_SECONDS = float(os.getenv("SLOW_QUARANTINE_SECONDS", "300"))
_SLOW_VS_FASTEST_RATIO = float(os.getenv("SLOW_VS_FASTEST_RATIO", "4"))


def _rank_key(model: str) -> tuple[float, str]:
    """Sort key for model selection: effective latency, then name."""
    base = _latency_ms.get(model, _ASSUMED_LATENCY_MS)
    if "lite" in model.lower():
        base += _LITE_PENALTY_MS
    return (base, model)


_RETRY_DELAY_RE = re.compile(r"retry in ([0-9.]+)\s*s", re.IGNORECASE)


def _record_latency(model: str, seconds: float) -> None:
    """Fold one successful call's duration into the model's running mean.

    A model that is pathologically slow to first token is quarantined here
    rather than merely ranked last: ranking still routes double-digit traffic
    to it whenever the pool is small, and one 28s request is a failed product.
    """
    with _rotation_lock:
        sample = max(seconds, 0.0) * 1000.0
        prior = _latency_ms.get(model)
        _latency_ms[model] = sample if prior is None else (
            _LATENCY_SMOOTHING * sample + (1 - _LATENCY_SMOOTHING) * prior
        )
        smoothed = _latency_ms[model] / 1000.0
        others = [v / 1000.0 for m, v in _latency_ms.items() if m != model]
        fastest = min(others) if others else None
        if (
            smoothed > _SLOW_TTFT_SECONDS
            and fastest is not None
            and smoothed > fastest * _SLOW_VS_FASTEST_RATIO
        ):
            _quota_marks[model] = time.monotonic() + _SLOW_QUARANTINE_SECONDS
            print(
                f"[thrace] {model} quarantined: {smoothed:.1f}s to first token "
                f"vs {fastest:.1f}s best; benched {_SLOW_QUARANTINE_SECONDS:.0f}s",
                flush=True,
            )


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
    """Pick the fastest usable model, rather than the next in rotation.

    Skips models benched by a quota or capacity error, and among the rest
    prefers the one with the lowest observed latency (see `_latency_ms`). This
    replaces round-robin, which sent a third of requests to models the free
    tier serves an order of magnitude slower.

    When every model is cooling down we pause briefly and then return the model
    that frees up soonest, rather than blocking until its full retry window
    expires — a run must never stall for a minute because one model is
    throttled.
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
            # Ascending latency, then weighted pick. Uniform rotation still sent
            # a third of traffic to the slowest model, so slots are allocated
            # by rank with a steep geometric decay: the fastest usable model
            # takes ~75% of traffic, the next ~19%, then ~5%, ~1%, ~0.3%. The
            # tail stays reachable so a recovered model is not starved, but it
            # no longer costs the user 20s on one request in five.
            ordered = sorted(usable, key=_rank_key)
            if len(ordered) == 1:
                return ordered[0]
            weights = [_RANK_DECAY**rank for rank in range(len(ordered))]
            total = sum(weights)
            # Deterministic walk over the cumulative weights, so the
            # distribution is exactly the intended one rather than sampled.
            point = (_rr_index % 1000) / 1000.0 * total
            upto = 0.0
            for model, weight in zip(ordered, weights):
                upto += weight
                if point < upto:
                    return model
            return ordered[-1]
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


def _is_daily_quota_error(exc: Exception) -> bool:
    """True when the provider says the *daily* allowance is gone.

    This is not a burst limit: it will not clear by retrying in a few seconds,
    so grinding through the model pool only delays the error the user needs to
    see. Wording is deliberately free of the `_TRANSIENT_MARKERS` tokens so the
    raised message is not itself retried by the layers above.
    """
    msg = str(exc).lower()
    return "generaterequestsperday" in msg or "per day" in msg


def _all_models_benched() -> bool:
    now = time.monotonic()
    with _rotation_lock:
        pool = _model_pool()
        return bool(pool) and all(_quota_marks.get(m, 0.0) > now for m in pool)


def _quota_exhausted_error() -> RuntimeError:
    pool = ", ".join(_model_pool())
    return RuntimeError(
        "Daily free-tier ceiling reached for every pooled model "
        f"({pool}). Nothing can be generated until the allowance resets. "
        "Add a paid key, or another provider via LLM_API_KEY / LLM_BASE_URL, "
        "to lift the ceiling — instant mode already needs one request per "
        "report instead of roughly twenty."
    )


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
    """Gemini client that picks the fastest usable model for every request.

    Each request selects the quickest model that is not currently benched (see
    `_next_model`), and is globally paced. Any transient provider error rotates
    to another model and transparently retries, so per-model limits and
    capacity spikes never surface to the agent layer.

    The SDK's own HTTP retry is left at its default on purpose. It does add
    ~1/2/4/8s of backoff on a hard 503, but disabling it (via
    `client._http_options`) changed the shape of the error Agno surfaces —
    `RunErrorEvent.content` became a raw `HttpResponse` object instead of a
    message, which would have leaked `<google.genai._api_client.HttpResponse
    object at 0x...>` to the user. Measured TTFT on this tier is dominated by
    which model is chosen, not by that backoff, and the selection logic below
    already fixes that.
    """

    def invoke(self, *args, **kwargs):
        max_attempts = max(len(_model_pool()) * 2, 4)
        for attempt in range(1, max_attempts + 1):
            self.id = _next_model()
            _pace_gemini_request()
            started = time.monotonic()
            try:
                result = super().invoke(*args, **kwargs)
                _record_latency(self.id, time.monotonic() - started)
                return result
            except Exception as exc:  # noqa: BLE001
                if _rotate_on(self.id, exc, attempt, max_attempts):
                    continue
                raise

    def invoke_stream(self, *args, **kwargs):
        max_attempts = max(len(_model_pool()) * 2, 4)
        for attempt in range(1, max_attempts + 1):
            self.id = _next_model()
            _pace_gemini_request()
            started = time.monotonic()
            emitted = False
            try:
                for chunk in super().invoke_stream(*args, **kwargs):
                    if not emitted:
                        emitted = True
                        # Record time-to-first-token, not total stream length:
                        # that is the latency the user perceives, and a long
                        # report from a fast model should not be penalised for
                        # being long.
                        _record_latency(self.id, time.monotonic() - started)
                    yield chunk
                return
            except Exception as exc:  # noqa: BLE001
                # A stream that already produced output cannot restart here
                # without duplicating content; the pipeline layer handles
                # that case (it can reset the client's accumulated text).
                if not emitted and _rotate_on(self.id, exc, attempt, max_attempts):
                    continue
                raise


# Output ceiling per feature. Generation time scales with output length, so
# this is the single biggest latency lever: the venture report went from ~14.2k
# characters to ~3.7k, which is most of the speedup.
#
# The prompt also states a word budget, but a hard token cap is the only thing
# that bounds a runaway completion — a model that ignores "be concise" will
# otherwise stream until it exhausts its own limit.
#
# These ceilings are ceilings, not targets: the model's own sense of how long
# the answer should be decides the length, and the cap only has to be high
# enough to let it finish. It is NOT a knob for making reports concise — a cap
# below the natural length does not produce a shorter report, it produces a
# report with the last third lopped off, which reads as a broken product.
#
# Measured, not guessed. Running each feature with the cap lifted until nothing
# truncated, and reading the length the model actually chose:
#
#   feature    natural output        old cap   verdict
#   venture    ~8,600 chars ~2,150t   1,300     truncated ~42% of the report
#   xray       ~3,600 chars   ~900t   1,000     fit, but with almost no margin
#   discovery  ~3,550 chars   ~890t     900     fit by a handful of tokens
#
# So venture was not "concise", it was amputated: a report cut at 1,300 tokens
# ends mid-sentence around "Rider Utilization Rate (the number of completed
# paid deliveries per", and the Sources block that follows makes it look
# deliberate. Each cap below is the measured natural length plus roughly a third
# of headroom, which absorbs run-to-run variance without inviting essays.
_MAX_TOKENS = {
    "venture": int(os.getenv("VENTURE_MAX_TOKENS", "2900")),
    "xray": int(os.getenv("XRAY_MAX_TOKENS", "1400")),
    "discover": int(os.getenv("DISCOVERY_MAX_TOKENS", "1250")),
    "qa": int(os.getenv("QA_MAX_TOKENS", "700")),
}
_DEFAULT_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1800"))

# Shortest plausible finished output per feature, used to catch a stub that the
# tail heuristic cannot. Measured natural lengths are ~7,100-9,000 characters
# for venture, ~3,600 for x-ray and ~3,550 for discovery, so these floors sit
# well below the real thing: they exist to catch a report that stopped after a
# couple of hundred characters, not to police length.
#
# The tail heuristic alone misses that case. A real 204-character report ended
# on "* **High-Yield Niche:** Abuja's decentralized geography and high" — 66
# characters, starting with a bullet, so it read as a deliberate short label
# and was reported complete. Only the caller knows its own floor, which is why
# this lives here rather than inside the detector.
_MIN_REPORT_CHARS = {
    "venture": 2500,
    "xray": 1500,
    "discover": 1500,
    # Follow-up answers are meant to be short, so only a near-empty one counts.
    "qa": 200,
}


def _max_tokens(kind: str) -> int:
    return _MAX_TOKENS.get(kind, _DEFAULT_MAX_TOKENS)


def _chat_model(kind: str = "venture"):
    """Build the LLM client for one feature.

    Provider is auto-detected from the model id:
      - ids starting with "gemini" -> Google Gemini via the native SDK
        (key from GEMINI_API_KEY, falling back to LLM_API_KEY)
      - anything else -> any OpenAI-compatible provider:
          - LLM_API_KEY   -> provider key (falls back to OPENAI_API_KEY)
          - LLM_MODEL     -> model id (default gpt-4o)
          - LLM_BASE_URL  -> custom endpoint (e.g. an agent router / gateway); omit
                             for the default OpenAI endpoint.

    `kind` selects the output ceiling for the feature being generated.
    """
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    max_tokens = _max_tokens(kind)
    if MODEL.lower().startswith("gemini"):
        return _PacedGemini(
            id=MODEL,
            api_key=os.getenv("GEMINI_API_KEY") or api_key,
            max_output_tokens=max_tokens,
            # Gemini 3.x reasons before it answers. Measured on this tier,
            # leaving thinking at the default added ~4-5s to time-to-first-token
            # on a short prompt, which is a third of the whole budget for an
            # x-ray. "low" keeps enough reasoning to stay accurate on the
            # judgement calls these reports make while cutting the pre-answer
            # overhead. Override with GEMINI_THINKING_LEVEL=high to restore the
            # default for harder work.
            thinking_level=os.getenv("GEMINI_THINKING_LEVEL", "low"),
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
        max_tokens=max_tokens,
        # Transient provider 429s (e.g. free-tier TPM windows) are retryable;
        # Agno's `retries` defaults to 0, which disables backoff entirely.
        retries=_LLM_RETRIES,
        exponential_backoff=True,
        delay_between_retries=_LLM_RETRY_DELAY,
    )

# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
# The analyst names reported by /api/health. There is no multi-agent team any
# more — every feature runs a single analyst — but the list is kept so the
# health payload still describes the intelligence the app can produce.
FEATURE_NAMES = [
    "Venture Intelligence Analyst",
    "Company X-Ray Analyst",
    "Opportunity Discovery Analyst",
]


def _model_key() -> str:
    """The API key the currently selected model route will actually use.

    Mirrors `_chat_model`. A readiness check that only asked "is *any* key
    present" would report ready for a route with no usable key — which is how a
    Gemini-keyed deployment could serve a healthy /api/health and then fail
    every single report.
    """
    if MODEL.lower().startswith("gemini"):
        return (
            os.getenv("GEMINI_API_KEY")
            or os.getenv("LLM_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        )
    return os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""


def team_status() -> dict:
    """Readiness for /api/health and the pre-flight check on every route.

    A model key is required, and it must be one the selected route can use.
    FIRECRAWL_API_KEY is NOT required — source retrieval is optional by
    design, and a missing or out-of-credits key only costs the user their
    Sources block, never their report.
    """
    ready = bool(_model_key())
    if ready:
        error = None
    elif MODEL.lower().startswith("gemini"):
        error = f"No API key for the selected model ({MODEL}). Set GEMINI_API_KEY."
    else:
        error = (
            f"No API key for the selected model ({MODEL}). Set LLM_API_KEY or "
            "OPENAI_API_KEY, or set LLM_MODEL to a gemini model to use "
            "GEMINI_API_KEY."
        )
    return {
        "ready": ready,
        "error": error,
        "model": MODEL,
        "pipelines": ["venture", "xray", "discovery"],
        "agents": FEATURE_NAMES,
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
#
# Retry policy now lives in `intelligence` so the fast paths and the
# quota/rotation logic below agree on what counts as transient. Re-exported
# under the private names the rest of this module (and scripts/) already use.
_TRANSIENT_MARKERS = intelligence._TRANSIENT_MARKERS
_STAGE_MAX_ATTEMPTS = intelligence.STAGE_MAX_ATTEMPTS
_STAGE_RETRY_DELAY = intelligence.STAGE_RETRY_DELAY
_is_transient_error = intelligence.is_transient_error


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
    if _is_daily_quota_error(exc) and _all_models_benched():
        # Every pooled model is out of daily allowance. Rotating again cannot
        # succeed, and the sleeps would stall the run for minutes before
        # surfacing an error — so surface it now.
        raise _quota_exhausted_error()
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




















# ---------------------------------------------------------------------------
# Venture Intelligence pipeline (primary feature)
# ---------------------------------------------------------------------------


















# ---------------------------------------------------------------------------
# Autonomous agents: self-critique, monitoring, discovery, report Q&A, digest
# ---------------------------------------------------------------------------


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
        model=_chat_model("qa"),
        tools=[TOOLS()],
        markdown=True,
        exponential_backoff=True,
        delay_between_retries=2,
    )


DISCOVERY_MAX_IDEAS = int(os.getenv("DISCOVERY_MAX_IDEAS", "4"))

_DISCOVERY_AGENT_CACHE: Agent | None = None

# Discovery used to be a search-driven agent: up to four Firecrawl searches,
# each a full model round-trip, with exponential backoff on top. That made the
# feature the slowest thing in the app — and when the search backend was
# unavailable it was the *slowest and least useful* combination, since the
# agent burned its retry budget discovering it could not search.
#
# The agent now reasons from its own knowledge and writes ideas directly. It
# still cannot print a URL (see FAST_ANALYST_RULES) — the real links come from
# SourceCollector afterwards.
_DISCOVERY_RULES = dedent(f"""
    You are Thrace's opportunity discovery analyst. You PROPOSE business ideas
    worth validating — you find opportunities, you do not validate them.

    You have no research tools and no live data. Work from your own knowledge
    of the location, sector, customer segments, infrastructure, regulation and
    consumer trends you know about.

    Propose exactly {DISCOVERY_MAX_IDEAS} concrete, specific ideas — never more
    than {DISCOVERY_MAX_IDEAS}.

    Language matters. Every idea is a HYPOTHESIS, not a finding:
    - Say an idea "appears worth validating", not "is profitable".
    - Say "potential signal" or "this should be tested", never "the market is
      proven" or "demand is confirmed".
    - Give reasons to believe it deserves attention, not evidence that it works.
    - Never invent statistics, survey figures or market sizes. If you give a
      number, label it an estimate and give the assumption behind it.
    - Never invent a company, a person or a funding round. Describe categories.
    - Never print a URL or a source list. Sources are attached for you later.

    Output STRICTLY in this format, one block per idea, no extra commentary:
    ### {{Short title}}
    idea: {{one-line business idea, specific enough to validate, including location}}
    why: {{2-4 sentences: the problem, who has it, the target customer, a
    possible business model, and why it is worth validating now. Name the
    specific thing that should be tested first.}}

    Each 'idea:' line must be directly runnable as a venture validation prompt.
""")


def _discovery_agent() -> Agent:
    global _DISCOVERY_AGENT_CACHE
    if _DISCOVERY_AGENT_CACHE is None:
        _DISCOVERY_AGENT_CACHE = Agent(
            name="Opportunity Discovery Analyst",
            description=_DISCOVERY_RULES,
            model=_chat_model("discover"),
            markdown=True,
        )
    return _DISCOVERY_AGENT_CACHE


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
        model=_chat_model("qa"),
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
        model=_chat_model("qa"),
        markdown=True,
    )




# ---------------------------------------------------------------------------
# Venture prompts
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# Venture pipeline runner
# ---------------------------------------------------------------------------
# Wall-clock ceiling for the research phase of a run. Sized so both waves
# (validation, then the other four in parallel) finish with room to spare; a
# stage still outstanding when it expires is abandoned and the report names the
# gap, so a run can never sprawl into the multi-minute failures we shipped
# before. Override with VENTURE_BUDGET_SECONDS.
# Revisions are full extra research passes — by far the most expensive thing a
# run does. Capped per run so one demanding stage cannot consume the whole
# daily request quota (the free tier allows only 20 requests/model/day).
# Skip a revision when this little budget is left: it cannot finish in time.












# ---------------------------------------------------------------------------
# Fast reports (the one path all three features use)
# ---------------------------------------------------------------------------
# The research pipeline is what made Thrace slow: five stages, each running an
# agent with web tools, so one report was many sequential model round-trips —
# and on the free tier the quota turned each of those into rotations and
# cooldowns. The fast path replaces all of it with ONE streaming call, so the
# first tokens arrive in about a second and nothing waits on a search.
#
# The honesty rules are unchanged and still enforced: the analyst may not
# print a link. What changed is that we no longer have to leave the user with
# no sources at all — `intelligence.SourceCollector` gathers real URLs on a
# background thread while the report streams, and appends them at the end. The
# model still never writes a URL; we supply the real ones.
#
# One agent per feature kind rather than one shared agent: each kind carries its
# own output ceiling, and caching by kind is what lets a venture request and an
# x-ray request use different budgets without rebuilding the client per call.
_instant_agent_cache: dict[str, Agent] = {}


def _instant_agent(kind: str = "venture") -> Agent:
    cached = _instant_agent_cache.get(kind)
    if cached is None:
        cached = Agent(
            name="Thrace Intelligence Analyst",
            description=intelligence.FAST_ANALYST_RULES,
            model=_chat_model(kind),
            markdown=True,
        )
        _instant_agent_cache[kind] = cached
    return cached




def instant_venture_prompt(idea: str) -> str:
    """Concise Venture Intelligence report.

    Section list is fixed; section *depth* is not. The old format asked for a
    TAM/SAM/SOM table, a SWOT, a risk register, a startup-cost table, a
    two-horizon roadmap, a regulatory checklist and KPIs — which reliably
    produced ~14k characters and ~55s of generation for a first read.

    The user can ask for depth in a follow-up question, so the first pass
    optimises for decision speed: one tight section per question a founder
    actually asks, hard length ceilings, and no section that restates another.
    """
    return dedent(f"""
        Write a Venture Intelligence report on this idea, in one pass.

        Idea: "{idea}"

        === STRUCTURE (use these headings, in this order) ===
        # Venture Intelligence — {idea}
        ## Executive Summary
        Verdict (PURSUE / PIVOT / DROP) + 3 bullets. Max 90 words total.
        ## Opportunity
        The problem and who has it. 2-3 bullets.
        ## Target Customers
        2-3 bullets. Name the specific buyer, not a demographic sketch.
        ## Market
        One short paragraph + a 3-row table (TAM / SAM / SOM). Label every
        figure "estimate" and state the assumption in one clause.
        ## Competition
        A 3-4 row table: incumbent | what they charge | the gap you exploit.
        ## Business Model
        How money is made, price point, and the one metric that decides
        whether this works. 2-3 bullets.
        ## Key Risks
        3-4 bullets, each one line: risk, then its mitigation.
        ## Validation Plan
        3-4 bullets, ordered cheapest-first. Each names a concrete test, its
        cost and what result would falsify the idea.
        ## Recommended Next Steps
        3 bullets, actionable this week.

        === RULES ===
        - Target 900-1300 words TOTAL. Stay inside that; the token ceiling
          that actually stops generation is set well above it, so running over
          means the report really is too long.
        - Bullets over paragraphs. Tables only where a table is the clearer form.
        - Never repeat a point in two sections.
        - No preamble, no "in this report I will", no closing summary — the
          sections are the whole report.
        - Do not write a Sources section; sources are attached separately.
    """)


def instant_xray_prompt(analysis_type: str, company: str) -> str:
    """Concise Company X-Ray report.

    Same length discipline as the venture report: the first pass answers
    "should I care about this company and why", and the user drills into any
    section with a follow-up question.
    """
    if analysis_type == "sentiment":
        body = dedent("""
            ## Positive Signals
            3-4 bullets.
            ## Negative Signals
            3-4 bullets.
            ## Balance
            Max 70 words: what drives the net read, and what would flip it.
        """)
    elif analysis_type == "metrics":
        body = dedent("""
            ## Key Metrics
            A table: metric | value | confidence. 5-7 rows. Use "not public"
            rather than inventing a number, and mark any estimate.
            ## Qualitative Signals
            3-4 bullets.
            ## What To Watch
            2-3 bullets.
        """)
    else:
        body = dedent(f"""
            # {company} — Company X-Ray
            ## Company Overview
            2-3 bullets: what it is, who runs it, stage/scale.
            ## Product & Target Market
            2-3 bullets: what it sells and to whom.
            ## Business Model
            2 bullets: how it makes money, and pricing if known.
            ## Competitive Position
            2-3 bullets against its closest alternatives.
            ## Strengths
            3 bullets, one line each.
            ## Weaknesses & Risks
            3 bullets, one line each.
            ## Opportunities
            2-3 bullets: the most credible growth opening.
            ## Key Takeaways
            3 bullets: what a competitor or investor should actually do with
            this.
        """)
    # A URL is a strong hint about which company is meant, and its domain
    # often reveals the sector. Use it as context; do not fetch it.
    context = ""
    if re.match(r"^\s*https?://", company):
        context = dedent(f"""
            The user supplied this URL as the subject: {company}
            Treat it as a hint about which company they mean. You have not
            visited it — do not claim to describe anything only visible on the
            site, and do not invent page content, pricing or features.
        """)
    return dedent(f"""
        Write a concise {analysis_type} report on {company}, in one pass.
        {context}
        === STRUCTURE (use these headings) ===
        {body}

        === RULES ===
        - Target 500-800 words TOTAL. The token ceiling that stops generation
          is set above that, so this is the budget that governs length.
        - Bullets, one line each where possible. No long paragraphs.
        - Never repeat a point across sections.
        - No preamble and no closing summary.
        - If you are not confident about a company or a fact, say so in one
          clause and move on. Do not invent customers, funding or products.
        - Do not write a Sources section; sources are attached separately.
    """)


def _stream_instant(
    prompt: str, sources_query: str = "", kind: str = "venture"
) -> Iterator[dict]:
    """Stream a knowledge-based report, then append real sources if any arrive.

    Sources are gathered on a background thread that starts *before* the report
    does, so by the time the model finishes there is usually something to show.
    The bounded wait in `results()` is the only place a slow search backend can
    cost the user time, and it is a fixed ceiling rather than an open-ended
    crawl. If retrieval fails, the report simply ends without a Sources block.

    The output cap keeps generation fast but can cut a report off mid-sentence.
    We do not try to patch that with a second call: the client has no way to
    replace the tail of a report it has already streamed, so a continuation
    would be appended after the dangling clause and read as garbled text.
    Instead the cap is set above the length the model actually writes (see
    `_MAX_TOKENS`), and truncation is detected two ways — the tail heuristic in
    `intelligence.looks_truncated`, plus the per-feature floor in
    `_MIN_REPORT_CHARS`, which catches a report that stopped far too early to
    be judged by its ending at all.
    """
    collector = (
        intelligence.SourceCollector(sources_query).start() if sources_query else None
    )
    produced = False
    body = ""
    for event in intelligence.stream_agent(lambda: _instant_agent(kind), prompt):
        if event.get("type") == "delta" and event.get("data"):
            produced = True
            body += event["data"]
        yield event
    if not produced:
        # A run that completes without emitting a single token is a provider
        # failure, not an empty answer. Raising here stops the client closing a
        # successful-looking but blank report — the same class of bug the old
        # research path had.
        raise RuntimeError(
            "The report came back empty. Please try again — this is usually a "
            "transient provider issue."
        )
    if intelligence.looks_truncated(
        body, min_chars=_MIN_REPORT_CHARS.get(kind, 0)
    ):
        print(
            f"[thrace] {kind} report hit the {_max_tokens(kind)}-token cap and "
            f"ends mid-sentence ({len(body)} chars); raise "
            f"{kind.upper()}_MAX_TOKENS if this recurs",
            flush=True,
        )
    if collector is not None:
        block = intelligence.render_sources(collector.results())
        if block:
            yield {"type": "delta", "data": block}


def run_instant_venture(idea: str) -> Iterator[dict]:
    """Write a whole Venture Intelligence Report in one streaming call.

    One model request, no tools, no research stages. The caller emits `done`.
    """
    started = time.monotonic()
    yield {
        "type": "status",
        "label": "Analysing opportunity",
        "detail": "Reasoning over the idea and drafting the report…",
    }
    yield {"type": "stage_start", "stage": "report", "label": "Report"}
    yield from _stream_instant(
        instant_venture_prompt(idea), sources_query=idea, kind="venture"
    )
    print(
        f"[thrace] venture report in {time.monotonic() - started:.1f}s",
        flush=True,
    )


def run_instant_xray(analysis_type: str, company: str) -> Iterator[dict]:
    """Write a whole Company X-Ray report in one streaming call.

    One model request, no tools, no research stages. The caller emits `done`.
    """
    started = time.monotonic()
    yield {
        "type": "status",
        "label": "Analysing company",
        "detail": f"Reasoning about {company} and drafting the report…",
    }
    yield {"type": "stage_start", "stage": "report", "label": "Report"}
    # The user may type a URL instead of a name. We hand it to the model as
    # context (it is a strong hint about which company is meant) but we do not
    # crawl it — that is the deep-research behaviour this path replaces.
    yield from _stream_instant(
        instant_xray_prompt(analysis_type, company),
        sources_query=company,
        kind="xray",
    )
    print(
        f"[thrace] {analysis_type} report for {company} "
        f"in {time.monotonic() - started:.1f}s",
        flush=True,
    )





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
    """Propose ideas worth validating, from the model's own knowledge.

    One streaming call, no tools. Each idea is emitted the moment its block is
    finished rather than once the whole response is over, so cards (and their
    validate buttons) appear while the analyst is still writing. At most
    `DISCOVERY_MAX_IDEAS` ideas are produced.
    """
    focus_line = (
        f"Focus: {focus}" if focus else "Focus: Nigeria (any high-potential sector)"
    )
    prompt = dedent(f"""
        Propose {DISCOVERY_MAX_IDEAS} business opportunities worth validating.
        {focus_line}

        Think about problems first: who is currently paying for a bad
        workaround, what supply gap or infrastructure shift makes a new entrant
        plausible now, and what a small team could actually reach and sell.
        Prefer specific, unglamorous, reachable opportunities over big abstract
        ones.
    """)
    yield {
        "type": "status",
        "label": "Generating opportunities",
        "detail": "Reasoning about problems, customers and business models…",
    }

    sources_query = focus.strip() or "Nigeria business opportunities"
    collector = intelligence.SourceCollector(sources_query).start()

    content = ""
    emitted = 0
    consumed = 0

    def drain_finished_blocks() -> Iterator[dict]:
        """Emit every idea block the analyst has finished writing so far."""
        nonlocal consumed, emitted
        blocks, _ = _split_idea_blocks(content)
        while consumed < len(blocks) and emitted < DISCOVERY_MAX_IDEAS:
            block = blocks[consumed]
            consumed += 1
            idea = _parse_idea_block(block)
            if idea is not None:
                emitted += 1
                yield idea

    try:
        for event in _discovery_agent().run(prompt, stream=True):
            if isinstance(event, AgentRunContentEvent):
                if event.content:
                    content += event.content
                    yield {"type": "delta", "data": event.content}
                    for idea in drain_finished_blocks():
                        yield {"type": "idea", **idea}
            elif isinstance(event, AgentRunErrorEvent):
                raise RuntimeError(
                    f"Discovery failed: {intelligence._error_text(event)}"
                )
    except Exception as exc:  # noqa: BLE001
        # Fall back to one non-streaming attempt before giving up, so a flaky
        # stream does not cost the user their whole scan.
        if not content.strip():
            content = _run_with_retries(
                lambda: _check_run(
                    _discovery_agent().run(prompt), "Discovery failed"
                ),
                "Discovery",
            )
            for idea in drain_finished_blocks():
                yield {"type": "idea", **idea}
        else:
            print(f"[thrace] discovery stream interrupted: {str(exc)[:160]}", flush=True)

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

    # Real sources, appended to the scan log. Never fatal, never blocking.
    block = intelligence.render_sources(collector.results())
    if block:
        yield {"type": "delta", "data": block}

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
                f"Report Q&A failed: {intelligence._error_text(event)}"
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
