# Thrace — Startup Intelligence Platform

An AI platform for **business discovery and venture planning**.
Describe a business idea — e.g. *"AI-powered marketplace for Nigerian
farmers"* — and Thrace returns a structured, decision-ready report in
seconds: an executive verdict, the opportunity, target customers, market
sizing, competition, business model, key risks, a validation plan, and
recommended next steps, with a short list of real source links at the end.

Three capabilities share one intelligence layer:

- **Venture Intelligence** — validate and plan a new business idea
- **Company X-Ray** — analyse an existing company
- **Discovery** — generate business opportunities *worth validating*

**User accounts** — sign in (email + password, bcrypt-hashed, JWT sessions) or
continue with Google, to sync chats and the watchlist across devices;
anonymous guests keep a local session in the browser.

---

## Design principle

> **Fast intelligence first. Deep research is optional, not the default.**

Thrace reasons from the model's own knowledge first and answers immediately.
Source retrieval is lightweight and runs in the background: it never blocks the
report, and if it fails the report still streams. There is no deep crawling, no
sequential multi-agent pipeline, and no fabricated URLs.

This is a deliberate reversal of an earlier design. The original architecture
ran five specialised agents with web tools across several waves, then a
synthesis pass. It was thorough, and it was unusable: on a free-tier model pool
a single report took the better part of a minute, and Discovery — which ran up
to four web searches per request — was the slowest thing in the product. The
current architecture replaces all of that with a single streaming model call
per request.

---

## Architecture

```
frontend/   React 19 + TypeScript + Vite + Tailwind CSS v4 + shadcn/ui
backend/    FastAPI + a single fast intelligence agent (Gemini)
            + background source collection + SQLite + scheduler thread
start.sh    One-command launcher (backend + frontend)
stop.sh     Stop both servers
```

### One request, one call

Every interactive feature follows the same path:

```
POST /api/venture | /api/analyze | /api/discover
        ↓
  intelligence.stream_agent()          # one streaming model call, no tools
        ↓
  deltas → existing UI renders Markdown progressively
        ↓
  SourceCollector (background thread)   # started BEFORE generation
        ↓
  3–5 real source links appended to the finished report
```

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

Reports target 900–1300 words and are capped at 1300 output tokens. The user
can go deeper on any section with a follow-up question.

### Company X-Ray

The same analyst, a different structure. For `competitor` analyses: company
overview, product and target market, business model, competitive position,
strengths, weaknesses and risks, opportunities, key takeaways. `sentiment` and
`metrics` variants structure the report around perception and KPIs
respectively. Capped at 1000 output tokens.

If the user supplies a URL instead of a company name, it is passed to the model
as a hint about which company is meant. The site is **not** crawled.

### Discovery

A no-tools analyst proposes business opportunities from pretrained knowledge.
Ideas are framed as **hypotheses worth validating**, never as validated
findings. Each idea is emitted as soon as its block completes, so cards appear
while the analyst is still writing, and any card can be sent straight into
Venture Intelligence with one click.

---

## Intelligence layer

`backend/intelligence.py` holds the strategy shared by all three features.

**Analyst rules.** One system prompt, enforced for every feature: never
fabricate sources, URLs, citations, statistics, companies, people or funding
rounds; label estimates as estimates and state the assumption; hedge
judgements; never imply that research was performed.

**Source integrity.** The model is *forbidden* from writing a URL. Real links
are attached by the backend afterwards:

1. **Live search** (when a search provider is configured) — most specific, first
2. **Curated official bodies** scored against the query
3. **Broad cross-sector bodies** to reach the floor of 3

Relevance is scored rather than first-matched, with a locale boost, so
*"fintech in Nigeria"* leads with the Central Bank of Nigeria and the
securities regulator rather than a global institution. The result is always
3–5 deduplicated, real links.

Retrieval runs on a background thread started **before** generation, so by the
time the report finishes there is usually something to show. A bounded wait
follows, and any failure is swallowed — a dead search backend costs the user
their sources, never their report.

> The curated fallback ships while no search provider has credits. Add
> `FIRECRAWL_API_KEY` with credit and tier 1 fills with live results instead.

**Truncation guard.** The output cap is what makes generation fast, and a
report cut off mid-sentence reads as a bug. Reports are checked for a
truncation signature and the condition is logged rather than silently shipped.

---

## Model layer

Provider-flexible and tuned for latency. Model ids starting with `gemini` route
through Google's native SDK (`GEMINI_API_KEY`); anything else goes through any
OpenAI-compatible endpoint (`LLM_API_KEY` / `LLM_BASE_URL`).

- **Latency-aware selection.** Every call records its time-to-first-token per
  model, and traffic is weighted by observed speed rather than rotated
  blindly. This matters more than it sounds: on the free tier the same API
  served sibling flash models anywhere between 0.8s and 28s to first token, and
  round-robin was sending a third of all requests to the slow one.
- **Slow-model quarantine.** A model slower than 8s *and* 4× the fastest is
  benched outright for five minutes and re-probed later.
- **Lite models rank last.** Speed alone must not buy a quality drop;
  lite-tier models are the overflow, not the default.
- **Quota rotation.** A 429 benches that model for its reported retry window
  and the request transparently retries on another. Errors never surface.
- **Global pacing.** `GEMINI_MIN_REQUEST_INTERVAL` spaces requests.
- **Bounded retries.** Two attempts, 2s apart, and only for genuine transient
  failures. Authentication errors, bad model ids and malformed requests are
  never retried — the user sees the error immediately instead of waiting out
  a backoff that cannot help.
- **Per-feature output ceilings.** Venture 1300, X-ray 1000, Discovery 900,
  Q&A 500 tokens. Dense markdown tokenises at roughly 4–6 characters per token,
  so these are tuned to *complete*, not to truncate.

---

## Measured performance

Recorded with `scripts/bench_intelligence.py`, which times each phase
separately. Figures are from the Gemini free tier and vary with model load.

| Feature | Time to first token | Total | Output |
|---------|--------------------|-------|--------|
| Venture Intelligence | 2–8s | 8–14s | ~5.5k chars |
| Company X-Ray | 2–8s | 6–10s | ~4.5k chars |
| Discovery | 2–6s | 5–10s | ~3.4k chars, 4 ideas |

Before this pass the same features took 54.4s, 28.7s and 9.2s. Time-to-first-
token ranged from 2s to 95s on identical requests because of the model
selection problem described above.

> The Gemini free tier allows 20 requests per day per model. Sustained
> benchmarking exhausts it; failures during measurement are that quota, not the
> application.

---

## Autonomous capabilities

| Capability | How it works |
|------------|--------------|
| **Streaming** | Every feature streams Server-Sent Events; the report renders as it is written |
| **Source collection** | 3–5 real links appended to each report, retrieved in the background |
| **Server-side persistence** | Completed exchanges sync to SQLite (`backend/data/`); chats remain conversational |
| **Watchlist re-validation** | Watch any chat; a background scheduler re-runs a monitoring agent on a schedule and appends *what changed* |
| **In-app digest** | Monitoring updates aggregate into a daily Intelligence Digest; manual trigger in Settings |
| **Opportunity discovery** | The Discover view proposes opportunities worth validating, each launchable into Venture Intelligence |
| **Report Q&A** | Follow-up questions answered strictly from the chat's report — no new generation run |

The frontend polls `/api/updates` and merges autonomous updates into the chat
list automatically.

## Requirements

- Python 3.10+
- Node.js 20+
- API keys in `.env`:
  ```ini
  GEMINI_API_KEY=...        # model provider (required)
  FIRECRAWL_API_KEY=fc-...  # optional — enables live source links
  # Optional: LLM_MODEL, LLM_FALLBACK_MODELS, LLM_API_KEY, LLM_BASE_URL
  # for the model pool or any OpenAI-compatible provider
  ```

A model key is required. `FIRECRAWL_API_KEY` is **not** — source retrieval is
optional by design, and a missing or out-of-credits key only costs the user
their Sources block.

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
| `/api/auth/google/url` | GET | Google consent-screen URL for popup sign-in |
| `/api/venture` | POST | `{ idea }` → streamed Venture Intelligence report |
| `/api/analyze` | POST | `{ company, analysis_type }` → streamed Company X-Ray report |
| `/api/discover` | POST | `{ focus? }` → streamed opportunity ideas |
| `/api/ask` | POST | `{ content, question }` → streamed answer grounded in the report |
| `/api/runs/sync` | POST | Persist a completed chat exchange (user-scoped when authed) |
| `/api/chats` | GET | The signed-in user's full chat history |
| `/api/chats/{id}` | DELETE | Delete a chat server-side |
| `/api/chats/{id}/pin` | PATCH | Pin/unpin a chat server-side |
| `/api/updates` | GET | Server-originated exchanges since a timestamp, for client polling |
| `/api/watchlist` | GET/POST | List / add watched chats |
| `/api/watchlist/{id}` | DELETE | Stop watching a chat |
| `/api/digest/run` | POST | Manually trigger one scheduler cycle |
| `/api/discover/scan` | GET/POST/DELETE | Persist, load or clear a discovery scan per user |

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
.venv/bin/python scripts/test_xray_guard.py             # regression suite
.venv/bin/python scripts/test_venture.py
.venv/bin/python scripts/test_discovery_ideas.py
.venv/bin/python scripts/test_quota_failfast.py
```

## Future enhancements

Not implemented. See `SCOPE_VENTURE_INTELLIGENCE.md` and Chapter Six of the
project report for the full roadmap.
