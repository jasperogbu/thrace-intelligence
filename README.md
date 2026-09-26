# Thrace — Startup Intelligence Platform

An AI platform for **business discovery and venture planning**.
Describe a business idea — e.g. *"AI-powered marketplace for Nigerian
farmers"* — and Thrace returns a structured, decision-ready report in
seconds: an executive verdict, the opportunity, target customers, market
sizing, competition, business model, key risks, a validation plan, and
recommended next steps, followed by a short list of real source links.

Three capabilities share one intelligence layer:

- **Venture Intelligence** — validate and plan a new business idea
- **Company X-Ray** — analyse an existing company
- **Discovery** — generate business opportunities *worth validating*

**User accounts** — sign in with email and password (bcrypt-hashed, JWT
sessions) or Google, to sync chats and the watchlist across devices;
anonymous guests keep a local session in the browser.

---

## Design principle

> **Fast intelligence first.**

Thrace reasons from the model's own knowledge and answers immediately, in
one streaming call per request. Source retrieval is lightweight, runs on a
background thread, and never blocks the report. There is no web crawling, no
agent orchestration on the request path, and no fabricated URLs.

The system has **no tools on the request path**. The analyst cannot search
or browse, so report generation is a function of the model alone and of
output length alone. This is what makes the latency predictable and the
failure modes small.

---

## Architecture

```
frontend/   React 19 + TypeScript + Vite + Tailwind CSS v4 + shadcn/ui
backend/    FastAPI + one streaming analyst per request (Agno + Gemini)
            + background source collection + SQLite + scheduler thread
scripts/    Latency benchmark, regression suites, report renderer
start.sh    One-command launcher (backend + frontend)
stop.sh     Stop both servers
```

### One request, one call

```
POST /api/venture | /api/analyze | /api/discover
        ↓
  intelligence.stream_agent()          # one streaming call, no tools
        ↓
  delta events → existing UI renders Markdown progressively
        ↓
  SourceCollector (background thread)   # started BEFORE generation
        ↓
  3–5 real source links appended to the finished report
```

The two independent branches are what make the report fast: generation never
waits on retrieval, and retrieval never waits on generation.

### Venture Intelligence

A single analyst writes a structured report in one pass:

| Section | Content |
|---------|---------|
| Executive Summary | Verdict (PURSUE / PIVOT / DROP) + 3 bullets |
| Opportunity | The problem and who has it |
| Target Customers | The specific buyer, not a demographic sketch |
| Market | One paragraph + TAM/SAM/SOM table, figures labelled *estimate* |
| Competition | Incumbents, what they charge, the gap you exploit |
| Business Model | How money is made, price point, the deciding metric |
| Key Risks | 3–4 risks, each with its mitigation |
| Validation Plan | 3–4 tests, cheapest first, with falsification criteria |
| Recommended Next Steps | 3 actionable items |
| Sources | 3–5 real, clickable links |

Reports target 900–1300 words and are capped at 1300 output tokens. Any
section can be taken deeper with a follow-up question.

### Company X-Ray

The same analyst, a different structure. For `competitor`: company
overview, product and target market, business model, competitive position,
strengths, weaknesses and risks, opportunities, key takeaways. `sentiment`
and `metrics` restructure the report around perception and KPIs. Capped at
1000 output tokens.

If the user supplies a URL instead of a company name it is passed to the
model as a hint about which company is meant. The site is not fetched.

### Discovery

A no-tools analyst proposes business opportunities from pretrained
knowledge, framed explicitly as **hypotheses worth validating**, never as
validated findings. Each idea is emitted as soon as its block completes, so
cards appear while the analyst is still writing, and any card launches
directly into Venture Intelligence with one click. Capped at 900 tokens.

---

## The intelligence layer

`backend/intelligence.py` holds the strategy shared by all three features.

**Analyst rules.** One system prompt enforces the honesty constraints for
every feature: never fabricate sources, URLs, citations, statistics,
companies, people or funding rounds; label estimates as estimates and state
the assumption; hedge judgements rather than assert them; never imply that
research was performed; answer directly without repetition.

**Source integrity.** The model is *forbidden* from writing a URL. Three
mechanisms must all fail for a fabricated link to reach a user:

1. the system prompt forbids the model from writing one;
2. the renderer is the only component that emits a link, and it accepts
   only structured source objects — never free text from the model;
3. every URL is either a real search result or a known official
   organisation's root domain held in source code.

Sources are assembled in three tiers, each filling only what the tier above
left short:

| Tier | Source | Role |
|------|--------|------|
| 1 | Live search results (`FIRECRAWL_API_KEY`) | Most specific, always first |
| 2 | 21 curated official bodies, scored against the query | Sector and regulator relevance |
| 3 | Broad cross-sector official bodies | Reaches the floor of three |

Relevance is scored rather than first-matched: sector terms (*fintech*,
*agricultur*, *health*) outrank catch-alls (*market*, *business*), and a
local regulator is boosted when the query names its country. *"Fintech in
Lagos"* therefore leads with the Central Bank of Nigeria and the securities
regulator. The result is 3–5 deduplicated real links, capped at five.

**Truncation guard.** The output cap is what makes generation fast, and a
report cut off mid-sentence reads as a bug. Finished reports are checked for
a truncation signature and the condition is logged rather than silently
shipped. The detector is biased towards silence, since Markdown legitimately
ends without sentence punctuation.

**Error classification.** Transient failures (429, 503) are retried on a
fresh model; permanent ones (401, 403, 400, unknown model) surface
immediately, so the user never waits out a backoff that cannot help.

---

## Model layer

`backend/agents.py` owns the model client and the feature prompts. Model
ids starting with `gemini` route through Google's native SDK
(`GEMINI_API_KEY`); anything else goes through any OpenAI-compatible
endpoint (`LLM_API_KEY` / `LLM_BASE_URL`).

- **Latency-aware selection.** Every call records its time-to-first-token
  per model as a running mean, and traffic is weighted by observed speed
  with a 0.15 decay per rank rather than rotated uniformly. This matters
  more than it sounds: the same provider serves sibling flash models
  anywhere between 0.8s and 28s to first token.
- **Slow-model quarantine.** A model slower than 8s *and* 4× the fastest is
  benched for five minutes and re-probed later.
- **Lite models rank last.** Speed alone must not buy a quality drop;
  lite-tier models are the overflow, not the default.
- **Quota rotation.** A 429 benches that model for its reported retry
  window and the request transparently retries on another.
- **Global pacing.** `GEMINI_MIN_REQUEST_INTERVAL` spaces requests.
- **Per-feature output ceilings.** Venture 1300, X-ray 1000, Discovery
  900, Q&A 500 tokens. Dense markdown tokenises at roughly 4–6 characters
  per token, so these are tuned to *complete*, not to truncate.
- **Thinking level.** Gemini 3.x reasons before it answers; the level is
  set to `low`, which removes several seconds of pre-answer latency.

---

## Measured performance

Recorded with `scripts/bench_intelligence.py`, which times each phase
separately. Figures are from the Gemini free tier and vary with model load.

| Feature | Time to first token | Total | Output | Sources |
|---------|--------------------|-------|--------|---------|
| Venture Intelligence | 2–8s | 8–14s | ~5.5k chars | 3–5 |
| Company X-Ray | 2–8s | 6–10s | ~4.5k chars | 3–5 |
| Discovery | 2–6s | 5–10s | ~3.4k chars, 4 ideas | 3–5 |

> The Gemini free tier permits 20 requests per day per model. Sustained
> benchmarking exhausts it; failures during measurement are that quota, not
> the application.

---

## Autonomous capabilities

| Capability | How it works |
|------------|--------------|
| **Streaming** | Every feature streams Server-Sent Events; the report renders as it is written |
| **Source collection** | 3–5 real links appended to each report, retrieved in the background |
| **Server-side persistence** | Completed exchanges sync to SQLite; chats remain conversational across turns |
| **Watchlist re-validation** | Watch any chat; a background scheduler re-runs the monitoring agent when due and appends *what changed* |
| **In-app digest** | Monitoring updates aggregate into a daily Intelligence Digest; manual trigger in Settings |
| **Opportunity discovery** | The Discover view proposes opportunities worth validating, each launchable into Venture Intelligence |
| **Report Q&A** | Follow-up questions answered strictly from the chat's report — no new generation run |

The frontend polls `/api/updates` and merges autonomous updates into the
chat list automatically.

## Requirements

- Python 3.10+
- Node.js 20+
- API keys in `.env`:
  ```ini
  GEMINI_API_KEY=...        # model provider (required)
  FIRECRAWL_API_KEY=fc-...  # optional — enables live source links
  # Optional: LLM_MODEL, LLM_FALLBACK_MODELS, LLM_API_KEY, LLM_BASE_URL
  # for the model pool or any OpenAI-compatible provider
  # Optional: AUTH_SECRET, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
  # Optional: SMTP_HOST, SMTP_USER, SMTP_PASSWORD — password-reset email
  # Optional: TURSO_DATABASE_URL, TURSO_AUTH_TOKEN — hosted SQLite
  ```

A model key is required. `FIRECRAWL_API_KEY` is **not** — source retrieval
is optional by design, and a missing or out-of-credits key only costs the
user their Sources block.

## Quick Start

```bash
# 1. Python environment + backend deps
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt

# 2. Frontend deps
(cd frontend && npm install)

# 3. Launch everything
./start.sh
```

The launcher starts the API on `http://localhost:8000` and the app on
`http://localhost:5173`, then opens your browser.

### Manual start

```bash
# backend
.venv/bin/python -m uvicorn main:app --port 8000 --app-dir backend

# frontend (separate terminal)
(cd frontend && npm run dev)
```

### Stop

```bash
./stop.sh
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Readiness, model, features, analyst roster |
| `/api/auth/register` | POST | Create an account → user + session token |
| `/api/auth/login` | POST | Sign in → user + session token |
| `/api/auth/me` | GET | Validate the session token → current user |
| `/api/auth/google/url` | GET | Google consent URL for popup sign-in |
| `/api/auth/google/callback` | GET | Google redirect that posts the token back to the app |
| `/api/auth/forgot-password` | POST | Start a password reset by emailed link |
| `/api/auth/reset-password` | POST | Complete a reset with a single-use token |
| `/api/venture` | POST | `{ idea }` → streamed Venture Intelligence report |
| `/api/analyze` | POST | `{ company, analysis_type }` → streamed Company X-Ray report |
| `/api/discover` | POST | `{ focus? }` → streamed opportunity ideas |
| `/api/ask` | POST | `{ content, question }` → streamed answer grounded in the report |
| `/api/runs/sync` | POST | Persist a completed chat exchange |
| `/api/chats` | GET | The signed-in user's full chat history |
| `/api/chats/{id}` | DELETE | Delete a chat server-side |
| `/api/chats/{id}/pin` | PATCH | Pin/unpin a chat server-side |
| `/api/updates` | GET | Server-originated exchanges since a timestamp |
| `/api/watchlist` | GET/POST | List / add watched chats |
| `/api/watchlist/{id}` | DELETE | Stop watching a chat |
| `/api/digest/run` | POST | Manually trigger one scheduler cycle |
| `/api/discover/scan` | GET/POST/DELETE | Load, persist or clear a discovery scan per user |

```bash
# Venture Intelligence
curl -N -X POST http://localhost:8000/api/venture \
  -H "Content-Type: application/json" \
  -d '{"idea":"AI-powered marketplace for Nigerian farmers"}'

# Company X-Ray
curl -N -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"company":"Paystack","analysis_type":"competitor"}'
```

`analysis_type` ∈ `competitor` | `sentiment` | `metrics`

### Stream events

| Event | Purpose |
|-------|---------|
| `status` | Progress label and detail |
| `stage_start` / `stage_done` | Report stage transitions |
| `delta` | Incremental Markdown |
| `reset` | Client clears accumulated text (generation restarted) |
| `idea` | A completed Discovery opportunity card |
| `done` / `error` | Terminal states |

### Autonomous scheduler

- `REVAL_INTERVAL_HOURS` (default `168`) — how often each watched subject is re-validated
- `DIGEST_INTERVAL_HOURS` (default `24`) — digest aggregation window
- `SCHEDULER_CHECK_SECONDS` (default `60`) — scheduler tick

### Benchmarking and tests

```bash
.venv/bin/python scripts/bench_intelligence.py          # latency phases
.venv/bin/python scripts/bench_intelligence.py --repeat 3 --json
.venv/bin/python scripts/test_xray_guard.py             # regression suites
.venv/bin/python scripts/test_venture.py                # live probe
.venv/bin/python scripts/test_discovery_ideas.py
.venv/bin/python scripts/test_quota_failfast.py
```

The four suites run against stubbed agents and consume no provider quota,
except `test_venture.py`, which is a live probe against a running server.

### Project report

The full academic write-up lives in `report/`, as Markdown chapters plus
generated `.docx` and `.pdf`. Regenerate the binary formats after editing
the chapters:

```bash
.venv/bin/python scripts/render_report.py
```
