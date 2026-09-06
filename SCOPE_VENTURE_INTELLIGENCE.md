# Thrace — Venture Intelligence: Scope & Project Plan

> Project: Autonomous Startup Intelligence Platform for Business Discovery and Venture Planning
> Status: **BUILT & RUNNING** — full stack with autonomous capabilities, verified end-to-end
> Branding: Thrace, terminal aesthetic, XVII MAY LTD

---

## 1. The Vision

Thrace answers one question for a founder: *is this idea worth pursuing — and if
so, how do I execute it?*

The user types a **business idea** (e.g., "Start a food processing business in
Jos, Nigeria") → Thrace **validates the idea** and delivers **intelligence at
every stage of business planning**, producing an evidence-backed **Venture
Intelligence Report** that includes:

- **Idea validation verdict** — pursue / pivot / drop, with reasoning
- **Probability of success** — a structured, weighted score with rationale
- **Competitor landscape** — local and online, with differentiation openings
- **Planning & execution intelligence** — market size, customers, costs, pricing,
  go-to-market, roadmap, regulations, risks, KPIs

A secondary mode, **Company X-Ray**, researches an existing company (positioning,
sentiment, KPIs) using the same agent engine.

Thrace is also **autonomous** beyond on-demand reports: agents self-critique and
deepen weak evidence, watch subjects and re-validate them on a schedule, digest
changes in-app, discover new opportunities from live signals, and answer
follow-up questions over any report (see section 4b).

---

## 2. Primary User Journey

1. Visitor lands on Thrace. The hero input asks for a **business idea**:
   *"e.g. Start a food processing business in Jos…"*
2. On submit, the **Venture Intelligence Pipeline** runs — five stages, each handled
   by a specialised agent, with live status streamed to the UI (SSE).
3. The **Venture Intelligence Report** streams into the terminal, section by
   section, with every claim tied to cited web sources.
4. The user leaves with an actionable answer to: *Is this idea worth pursuing —
   and if so, how do I execute it?*
5. Completed reports are archived in the **Library**; a new idea can be submitted
   directly from the workspace input.

---

## 3. The Venture Intelligence Pipeline

| # | Stage | Agent | Key questions answered |
|---|-------|-------|------------------------|
| 1 | **Idea Validation** | Venture Validation Agent | Is this a real, painful problem? Is there demand evidence (search trends, local signals)? Is the idea clear enough to test? Verdict: **pursue / pivot / drop** + reasoning |
| 2 | **Market & Location Intelligence** | Market Intelligence Agent | Market size (localised TAM/SAM/SOM), target customer segments & personas, local economic context (e.g., Jos: population, commerce, income), pricing tolerance and spending power |
| 3 | **Competitive Landscape** | Competition Analysis Agent | Direct/indirect competitors in the target location & online; their strengths, gaps and pricing; white-space / differentiation opportunities |
| 4 | **Risk & Success Assessment** | Risk & Success Agent | Weighted scoring rubric → **probability-of-success score**; SWOT; risk register with likelihood, impact, and mitigations |
| 5 | **Venture Plan & Roadmap** | Venture Planning Agent | Recommended business model & pricing, startup cost estimate (₦), funding options, go-to-market strategy, phased execution roadmap (0–90 days, 3–12 months), regulatory steps (CAC, licences), KPIs to track |

Each stage runs web search + crawl (Firecrawl) so every section is grounded in
live evidence, and each section ends with a **Sources** list. After each stage,
an **Evidence Critic** reviews the brief; when evidence is weak, the stage agent
re-researches the specific gaps (self-critique + adaptive research budget)
before the **Thrace Lead Analyst** synthesises the five stage briefs into the
final report, which streams to the client as Markdown deltas.

### Probability-of-success rubric (Stage 4)

Each dimension scored 0–10, weighted, rolled into one composite score and band:

| Dimension | Weight |
|-----------|--------|
| Market demand evidence | 25% |
| Competitive intensity (inverse) | 20% |
| Execution complexity (inverse) | 15% |
| Capital accessibility | 15% |
| Location & regulatory fit | 15% |
| Timing / trend alignment | 10% |

**Bands:** ≥ 70% **Strong** · 50–69% **Promising** · 35–49% **Speculative** · < 35% **High-risk**

---

## 4. Company X-Ray (secondary mode)

The X-Ray mode researches an **existing company** the user names (e.g., "Opay").
Three agents coordinate through the Thrace Intelligence Team:

| Agent | Focus |
|-------|-------|
| Startup / Competitor Analysis Agent | Positioning, launch strategy, strengths, weaknesses |
| Market Sentiment Analysis Agent | Social/review sentiment, perception drivers, reception |
| Performance Metrics Agent | Adoption, revenue and growth KPIs vs benchmarks |

In the app UI, the chat mode switcher exposes three modes — **VENT** (Venture
Intelligence), **COMP** (Company X-Ray, which runs the competitor analysis) and
**ASK** (report Q&A, enabled once the chat holds a report). Chats are
conversational: new prompts continue the same chat as additional turns.

---

## 4b. Autonomous capabilities

| # | Capability | Implementation |
|---|------------|----------------|
| 1 | **Watchlist re-validation** | Any chat can be watched; a scheduler thread re-runs a Monitoring Agent against the subject (weekly by default, `REVAL_INTERVAL_HOURS`) and appends *what changed* updates into the chat server-side |
| 2 | **Server-side persistence** | SQLite (`backend/store.py`, `backend/data/`): runs, exchanges and watchlist; completed turns sync fire-and-forget from the client |
| 3 | **In-app alert digest** | Monitoring updates aggregate daily (`DIGEST_INTERVAL_HOURS`) into an Intelligence Digest chat; manual `run_cycle_now()` trigger in Settings |
| 4 | **Self-critique loop** | Evidence Critic reviews every stage brief; `REVISE` verdicts trigger a targeted re-research pass |
| 5 | **Adaptive research budget** | Extra searches run only where the critic finds gaps — deep on thin evidence, fast on solid evidence |
| 6 | **Opportunity discovery** | `/api/discover` + Discover view: agents scan live news/trends and propose validated-ready ideas (one click launches the pipeline) |
| 7 | **Report Q&A** | `/api/ask` + ASK mode: follow-up questions answered strictly from the report content — no new pipeline run |

The frontend polls `/api/updates` every 30 seconds and merges autonomous
re-validations and digests into the chat list; chats, turns and watched state
survive reloads (localStorage + SQLite).

---

## 5. Architecture

### Stack
- **Backend** — FastAPI + Agno multi-agent engine, Gemini (via Google's native
  SDK) with Firecrawl web search/crawl tools
- **Frontend** — React 19 + Vite + Tailwind CSS + shadcn/ui, terminal aesthetic
- **Runners** — `start.sh` / `stop.sh` one-command launch

### Model layer (resilience)
The LLM layer is provider-flexible and free-tier resilient:

- Model ids starting with `gemini` route through the native Gemini SDK
  (`GEMINI_API_KEY`); anything else goes through any OpenAI-compatible endpoint
  (`LLM_API_KEY` / `LLM_BASE_URL`).
- **Round-robin across a model pool** — every request cycles across the primary
  model plus `LLM_FALLBACK_MODELS`, so per-model free-tier quotas are spread
  instead of exhausted.
- **Transparent quota rotation** — a 429 marks that model as cooling down for its
  provider-reported retry window and the request transparently retries on the
  next model. Errors never surface to the user.
- **Request pacing** — `GEMINI_MIN_REQUEST_INTERVAL` spaces requests globally.
- **Stage-level retries + mid-stream restart** — transient failures (503 capacity
  spikes) retry the whole stage; a failed report stream restarts generation and
  emits a `reset` event so the client clears partial text instead of showing an
  error.

### Streaming protocol (SSE)
Both modes stream events over `POST`:

| Event | Purpose |
|-------|---------|
| `status` | Progress label + detail (X-Ray) |
| `stage_start` / `stage_done` | Pipeline stage transitions (Venture) |
| `delta` | Incremental report Markdown |
| `reset` | Client should clear accumulated report text (generation restarted) |
| `done` / `error` | Terminal states |

### API
| Endpoint | Purpose |
|----------|---------|
| `POST /api/venture` | `{ "idea": string }` → 5-stage pipeline + streamed report |
| `POST /api/analyze` | `{ "company", "analysis_type" }` → X-Ray team report |
| `POST /api/ask` | `{ "content", "question" }` → streamed answer grounded in the report |
| `POST /api/discover` | `{ "focus"? }` → streamed opportunity ideas |
| `POST /api/runs/sync` | Persist a completed chat exchange |
| `GET /api/updates` | Server-originated exchanges since a timestamp (client polling) |
| `GET/POST /api/watchlist`, `DELETE /api/watchlist/{id}` | Watch management |
| `POST /api/digest/run` | Manual scheduler cycle (re-validations + digest) |
| `GET /api/health` | Readiness, active model, agent roster, pipelines, autonomous features |

### Codebase map
| Area | Files |
|------|-------|
| Agent engine | `backend/agents.py` — 8 pipeline/team agents + Critic, Monitor, Discovery, Q&A, Digest agents; prompts; pipeline runners; model rotation |
| API server | `backend/main.py` — FastAPI, SSE endpoints, sync/watch/discover/ask/digest |
| Persistence | `backend/store.py` — SQLite (runs, exchanges, watchlist, meta) |
| Scheduler | `backend/scheduler.py` — background thread: due re-validations + digests |
| App shell / routing | `frontend/src/App.tsx` |
| Views | `landing.tsx`, `workspace.tsx`, `library.tsx`, `explore.tsx`, `discover.tsx`, `settings.tsx` |
| Components | `sidebar.tsx` (collapsible, watch/digest badges), `pipeline-steps.tsx`, `status-steps.tsx`, `markdown.tsx`, `logo.tsx` |
| Client | `frontend/src/lib/api.ts` (SSE reader + sync/watch/discover/ask clients), `frontend/src/lib/use-analyze.ts` (chat state, server sync, autonomous-update polling) |

### Persistence
Chats (report content, per-turn stages/modes, timestamps, pins) persist both to
browser `localStorage` (up to 60 chats, instant load) and server-side SQLite
(synced on completion) — the latter powering autonomous re-validation and
digests. Individual reports can be deleted, pinned or watched.

---

## 6. Venture Intelligence Report Format (final deliverable)

```markdown
# Venture Intelligence Report — {idea}
## Executive Verdict
Pursue / Pivot / Drop + probability-of-success score & band
## 1. Idea Validation
Problem evidence, demand signals, validation verdict & reasoning
## 2. Market & Location Intelligence
TAM/SAM/SOM table, customer segments, local context, pricing tolerance
## 3. Competitive Landscape
Competitor table (name, offering, pricing, strength, gap), white-space summary
## 4. Risk & Success Assessment
Scoring table, SWOT, risk register (risk / likelihood / impact / mitigation)
## 5. Venture Plan & Roadmap
Business model, startup costs (₦), funding options, GTM, 0–90-day &
3–12-month roadmap, regulatory checklist, KPIs
## Sources
All URLs crawled or searched
```

---

## 7. Verification

| Check | Result |
|-------|--------|
| Full venture run ("food processing in Jos", "laundry service in Jos") | 5/5 stages, ~10–12k-char report, zero surfaced errors |
| Full X-Ray run (Paystack) | Complete report, zero surfaced errors |
| Quota resilience | 11+ mid-run 429s absorbed transparently via model rotation |
| Type check + lint | `tsc --noEmit` clean; lint warnings pre-existing only |
| Health endpoint | Reports model, 8 agents, both pipelines, ready |

---

## 8. Out of Scope (future roadmap)

- Email / push delivery of digests (in-app only for now)
- User accounts, multi-session support
- Interactive charts for market/risk sections
- PDF/DOCX export of the report
- Updating the academic write-up in `report/` (separate exercise)
