# Thrace — Autonomous Startup Intelligence Platform

An AI-powered platform for **business discovery and venture planning**.
Describe a business idea — e.g. *"Start a business in Jos, Nigeria"* — and a
coordinated team of autonomous AI agents validates the idea and delivers
intelligence at every stage of business planning: probability of success,
competitors, market sizing, risks, and an execution-ready venture plan —
one evidence-backed report, every source cited.

Beyond on-demand reports, Thrace runs autonomously: agents **self-critique and
deepen weak evidence**, **watch** subjects and re-validate them on a schedule,
**digest** changes in-app, **discover** new opportunities from live signals,
and answer **follow-up questions** over any report.

**User accounts** — sign in (email + password, bcrypt-hashed, JWT sessions) to
sync chats, watchlist and digests across devices; anonymous guests keep a local
session in the browser.

Built as a modern full-stack product: a React + Tailwind CSS + shadcn/ui frontend
with a FastAPI backend wrapping a multi-agent LLM engine (Agno + Google Gemini +
Firecrawl) with SQLite persistence and a background scheduler.

---

## Architecture

```
frontend/   React 19 + TypeScript + Vite + Tailwind CSS v4 + shadcn/ui
backend/    FastAPI + Agno multi-agent engine (Google Gemini + Firecrawl)
            + SQLite persistence + autonomous scheduler thread
start.sh    One-command launcher (backend + frontend)
stop.sh     Stop both servers
```

### Pipeline 1 — Venture Intelligence (primary)

Enter any business idea and the **Venture Intelligence Pipeline** runs five
stages, each handled by a specialised agent with live web access:

| # | Stage | Agent | Key questions answered |
|---|-------|-------|------------------------|
| 1 | Idea Validation | **Venture Validation Agent** | Real problem? Demand evidence? Verdict: pursue / pivot / drop |
| 2 | Market & Location | **Market Intelligence Agent** | TAM/SAM/SOM, customer segments, local context, pricing tolerance |
| 3 | Competitive Landscape | **Competition Analysis Agent** | Local & online competitors, strengths, gaps, white space |
| 4 | Risk & Success | **Risk & Success Agent** | Weighted scoring → probability of success, SWOT, risk register |
| 5 | Plan & Roadmap | **Venture Planning Agent** | Business model, startup costs (₦), funding, GTM, roadmap, regulatory, KPIs |

The **Thrace Lead Analyst** then synthesises the five stage briefs into the final
**Venture Intelligence Report** — streamed live into the UI, section by section.

#### Probability-of-success rubric (stage 4)

| Dimension | Weight |
|-----------|--------|
| Market demand evidence | 25% |
| Competitive intensity (inverse) | 20% |
| Execution complexity (inverse) | 15% |
| Capital accessibility | 15% |
| Location & regulatory fit | 15% |
| Timing / trend alignment | 10% |

**Bands:** ≥ 70% **Strong** · 50–69% **Promising** · 35–49% **Speculative** · < 35% **High-risk**

### Pipeline 2 — Company X-Ray (secondary)

Research an **existing company** with the original three-agent team:

| Agent | Role |
|-------|------|
| **Startup / Competitor Analysis Agent** | Positioning, launch strategy, strengths, weaknesses |
| **Market Sentiment Analysis Agent** | Positive/negative perception drivers across social & review platforms |
| **Performance Metrics Agent** | Public KPIs, adoption signals, press traction |

Analyses run in two stages — evidence bullets first, then a streamed, structured
Markdown report rendered live in the UI.

## Autonomous capabilities

| Capability | How it works |
|------------|--------------|
| **Server-side persistence** | Completed exchanges sync to SQLite (`backend/data/`); chats remain conversational (multiple turns per chat, continuing in place) |
| **Watchlist re-validation** | "Watch" any chat; a background scheduler re-runs a Monitoring Agent against the subject weekly (configurable) and appends *what changed* updates into the chat |
| **In-app digest** | Monitoring updates are aggregated daily into an **Intelligence Digest** chat; a manual `run_cycle_now()` trigger lives in Settings |
| **Self-critique loop** | After each pipeline stage, an Evidence Critic reviews the brief; weak evidence triggers a targeted re-research pass before synthesis |
| **Adaptive research budget** | Extra web searches happen only where the critic finds evidence gaps — deep research on thin sections, fast passes on solid ones |
| **Opportunity discovery** | The **Discover** view scans live news/trends and proposes validated-ready ideas, each launchable into the pipeline with one click |
| **Report Q&A** | The **ASK** mode answers follow-up questions strictly from the chat's report — no new pipeline run needed |

The frontend polls `/api/updates` every 30s and merges autonomous
re-validations and digests into the chat list automatically.

## Requirements

- Python 3.10+
- Node.js 20+
- API keys in `.env`:
  ```ini
  GEMINI_API_KEY=...        # primary provider (Google Gemini)
  FIRECRAWL_API_KEY=fc-...
  # Optional: LLM_MODEL, LLM_FALLBACK_MODELS, LLM_API_KEY, LLM_BASE_URL
  # for Gemini pool tuning or any OpenAI-compatible provider
  ```

### Model layer (resilience)

The engine runs Google Gemini (`gemini-3.8-flash` by default) and survives
free-tier quotas transparently:

- every request is **round-robined** across a pool of models
  (`LLM_FALLBACK_MODELS`), spreading per-model quotas;
- a 429 quota error rotates that model out for its reported retry window and
  retries on the next model — errors never surface to the user;
- requests are globally paced (`GEMINI_MIN_REQUEST_INTERVAL`);
- transient failures (503 capacity spikes) retry the whole stage, and a failed
  report stream restarts generation (the client receives a `reset` event and
  clears partial text).

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
| `/api/health` | GET | Service status, model, pipelines, autonomous features, agents, readiness |
| `/api/auth/register` | POST | Create an account (email, name, password) → user + session token |
| `/api/auth/login` | POST | Sign in → user + session token |
| `/api/auth/me` | GET | Validate the session token → current user |
| `/api/venture` | POST | Run the Venture Intelligence pipeline for an idea; streams SSE events (`stage_start`, `stage_done`, `delta`, `reset`, `done`, `error`) |
| `/api/analyze` | POST | Company X-Ray; streams SSE events (`status`, `delta`, `reset`, `done`, `error`) |
| `/api/ask` | POST | Report Q&A — `{ content, question }`; answers strictly from the given report (SSE) |
| `/api/discover` | POST | Opportunity discovery — scans live signals, streams structured `idea` events (SSE) |
| `/api/runs/sync` | POST | Persist a completed chat exchange server-side (user-scoped when authed) |
| `/api/chats` | GET | The signed-in user's full chat history from the server |
| `/api/chats/{id}` | DELETE | Delete a chat server-side |
| `/api/updates` | GET | Server-originated exchanges (monitor/digest) since a timestamp, for client polling |
| `/api/watchlist` | GET/POST | List / add watched chats (autonomous re-validation) |
| `/api/watchlist/{id}` | DELETE | Stop watching a chat |
| `/api/digest/run` | POST | Manually trigger one scheduler cycle (re-validations + digest) |

```bash
# Venture Intelligence — validate an idea
curl -N -X POST http://localhost:8000/api/venture \
  -H "Content-Type: application/json" \
  -d '{"idea":"Start a food processing business in Jos, Nigeria"}'

# Company X-Ray — analyse an existing company
curl -N -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"company":"OpenAI","analysis_type":"competitor"}'
```

`analysis_type` ∈ `competitor` | `sentiment` | `metrics`

### Autonomous scheduler

- `REVAL_INTERVAL_HOURS` (default `168`) — how often each watched subject is re-validated
- `DIGEST_INTERVAL_HOURS` (default `24`) — digest aggregation window
- `SCHEDULER_CHECK_SECONDS` (default `60`) — scheduler tick
