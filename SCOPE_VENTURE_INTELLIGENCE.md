# Thrace — Venture Intelligence: Scope & Project Plan

> Project: Startup Intelligence Platform for Business Discovery and Venture Planning
> Status: **BUILT & RUNNING** — full stack, verified end-to-end
> Architecture: fast single-analyst intelligence layer with lightweight sources
> Branding: Thrace, terminal aesthetic, XVII MAY LTD

---

## 1. The Vision

Thrace answers one question for a founder: *is this idea worth pursuing — and if
so, how do I execute it?*

The user types a **business idea** (e.g., *"AI-powered marketplace for Nigerian
farmers"*) and Thrace returns a structured **Venture Intelligence Report**:
an executive verdict, the opportunity, target customers, market sizing,
competition, business model, key risks, a validation plan, recommended next
steps, and a short list of real source links.

A secondary capability, **Company X-Ray**, applies the same intelligence layer
to an existing company. A third, **Discovery**, proposes business opportunities
*worth validating*.

---

## 2. Architectural Position

### 2.1 The principle

> **Fast intelligence first. Deep research is optional, not the default.**

Thrace uses the model's existing knowledge to produce useful intelligence
immediately, and attaches a small number of real sources when they are
available. It does not run deep research before responding.

### 2.2 What changed, and why

The platform was originally built as a deep-research system: a five-stage
venture pipeline in which specialist agents (validation, market, competition,
risk, planning) each ran with web search and crawl tools, executed in waves,
then handed their briefs to a lead analyst for synthesis. Company X-Ray used a
parallel three-agent team. Discovery ran up to four web searches per request
before proposing a single idea.

That architecture was thorough and it was unusable. Measured on the free-tier
model pool, a Venture Intelligence report took 54.4s, Company X-Ray 28.7s, and
time-to-first-token varied between 2s and 95s on identical requests. Two
distinct causes were identified and both were real:

1. **Output volume.** The venture prompt asked for a TAM/SAM/SOM table, a SWOT,
   a risk register, a startup-cost table, a two-horizon roadmap, a regulatory
   checklist and KPIs. This reliably produced ~14.2k characters of dense
   markdown, and generation time scales with output length.
2. **Model selection.** The model pool rotated blindly across sibling models
   that the same free tier served at wildly different speeds — measured between
   0.8s and 28s to first token. Roughly a third of all requests went to the
   slowest model.

The current architecture replaces the staged pipeline with a single streaming
model call and fixes model selection empirically. The deep-research
architecture is not part of the system; it is documented here as history.

### 2.3 What the current system does not do

- No sequential multi-agent orchestration
- No deep crawling or recursive site inspection
- No research loop that blocks the response
- No model-generated URLs, ever
- No fabricated statistics, companies, funding rounds or citations

---

## 3. Primary User Journey

1. The user lands on Thrace and types a **business idea** into the hero input.
2. The request is accepted immediately and the first words of the report appear
   within a few seconds.
3. The **Venture Intelligence Report** streams into the workspace, section by
   section, while background source collection runs independently.
4. The report ends with 3–5 real, clickable source links.
5. The user leaves with an actionable answer, and can ask a follow-up question
   answered strictly from the report.
6. Completed reports are archived in the **Library**; opportunities discovered
   in **Discovery** can be validated with one click.

---

## 4. The Three Capabilities

All three share the same execution strategy: **one streaming model call, then
optional lightweight sources**.

| | Venture Intelligence | Company X-Ray | Discovery |
|---|---|---|---|
| **Subject** | A new business idea | An existing company | A region, sector or question |
| **Output** | Structured validation report | Structured company analysis | 4 opportunity cards |
| **Tools** | none | none | none |
| **Output cap** | 1300 tokens | 1000 tokens | 900 tokens |
| **Sources** | 3–5 real links | 3–5 real links | 3–5 real links |
| **Measured total** | 8–14s | 6–10s | 5–10s |

### 4.1 Venture Intelligence

Sections: Executive Summary (verdict + 3 bullets) · Opportunity · Target
Customers · Market (one paragraph + TAM/SAM/SOM table, figures labelled
*estimate*) · Competition (incumbents, pricing, the gap you exploit) · Business
Model · Key Risks (each with its mitigation) · Validation Plan (tests ordered
cheapest-first, with falsification criteria) · Recommended Next Steps · Sources.

The prompt fixes the section list and gives each section a word budget. Depth is
available on demand through follow-up questions rather than paid for upfront.

### 4.2 Company X-Ray

Sections for `competitor`: Company Overview · Product & Target Market · Business
Model · Competitive Position · Strengths · Weaknesses & Risks · Opportunities ·
Key Takeaways · Sources. `sentiment` and `metrics` restructure the report around
perception drivers and KPIs respectively.

A URL supplied by the user is passed to the model as a hint about which company
is meant. The site is not fetched.

### 4.3 Discovery

A no-tools analyst proposes opportunities from pretrained knowledge. Two rules
are enforced in the prompt and are the point of the feature:

- **Language discipline.** Every idea is a *hypothesis worth validating*, not a
  finding. The analyst is instructed to say "appears worth validating" and
  "the first thing to test", and never "the market is proven" or "demand is
  confirmed".
- **No fabrication.** No invented statistics, companies, people or URLs.

Each idea block is emitted the moment it completes, so cards appear while the
analyst is still writing. Any card launches directly into Venture Intelligence.

---

## 5. The Intelligence Layer

`backend/intelligence.py` holds the strategy shared by all three features.

### 5.1 Analyst rules

One system prompt, enforced everywhere: never fabricate sources, URLs,
citations, statistics, companies, people or funding rounds; label estimates as
estimates and state the assumption behind them; hedge judgements rather than
asserting them; never imply that research was performed; answer directly and
avoid repetition.

### 5.2 Source collection

The model is forbidden from writing a URL. Real links are attached by the
backend in three tiers, each filling only what the tier above left short:

1. **Live search** — most specific, always first
2. **Curated official bodies** scored against the query
3. **Broad cross-sector bodies** — to reach the floor

Relevance is scored, not first-matched, with a locale boost. *"Fintech in
Nigeria"* leads with the Central Bank of Nigeria and the securities regulator
rather than a global institution. The result is always 3–5 deduplicated real
links, and the list is capped at 5.

Retrieval runs on a background thread started **before** generation, so it is
usually finished by the time the report is. A bounded wait follows, and every
failure is swallowed: a dead search backend costs the user their sources, never
their report.

### 5.3 Streaming

`stream_agent` retries a transient failure once on a fresh model; a restart
emits a `reset` event so the client clears partial text rather than showing two
stitched attempts. Permanent errors — bad key, bad model id, malformed request
— are never retried.

### 5.4 Truncation guard

The output cap is the main reason generation is fast, and a report cut off
mid-sentence reads as a bug. Finished reports are checked for a truncation
signature and the condition is logged rather than silently shipped.

---

## 6. Architecture

### Stack

- **Backend** — FastAPI, Server-Sent Events, the Agno agent framework, and
  Google Gemini via its native SDK (any OpenAI-compatible provider also
  supported)
- **Frontend** — React 19 + TypeScript + Vite + Tailwind CSS v4 + shadcn/ui,
  terminal aesthetic
- **Persistence** — SQLite server-side, `localStorage` client-side
- **Runners** — `start.sh` / `stop.sh`

### Model layer

- **Latency-aware selection.** Every call records time-to-first-token per model
  and traffic is weighted by observed speed, not rotated blindly.
- **Slow-model quarantine.** A model slower than 8s *and* 4× the fastest is
  benched for five minutes.
- **Lite models rank last** — speed must not silently buy a quality drop.
- **Quota rotation** — a 429 benches that model and retries on another; errors
  never surface to the user.
- **Global pacing** — `GEMINI_MIN_REQUEST_INTERVAL`.
- **Bounded retries** — two attempts, 2s apart, transient failures only.

### Streaming protocol (SSE)

| Event | Purpose |
|-------|---------|
| `status` | Progress label + detail |
| `stage_start` / `stage_done` | Report stage transitions |
| `delta` | Incremental report Markdown |
| `reset` | Client clears accumulated text (generation restarted) |
| `idea` | A completed Discovery opportunity card |
| `done` / `error` | Terminal states |

### API

| Endpoint | Purpose |
|----------|---------|
| `POST /api/venture` | `{ "idea" }` → streamed Venture Intelligence report |
| `POST /api/analyze` | `{ "company", "analysis_type" }` → streamed Company X-Ray report |
| `POST /api/discover` | `{ "focus"? }` → streamed opportunity cards |
| `POST /api/ask` | `{ "content", "question" }` → streamed answer grounded in the report |
| `POST /api/auth/*` | Register, login, session, Google sign-in |
| `POST /api/runs/sync` | Persist a completed chat exchange |
| `GET /api/chats`, `DELETE /api/chats/{id}`, `PATCH /api/chats/{id}/pin` | Chat history management |
| `GET/POST /api/watchlist`, `DELETE /api/watchlist/{id}` | Watch management |
| `GET/POST/DELETE /api/discover/scan` | Per-user discovery scan persistence |
| `GET /api/updates` | Server-originated exchanges since a timestamp |
| `POST /api/digest/run` | Manual scheduler cycle |
| `GET /api/health` | Readiness, active model, analyst roster, features |

### Codebase map

| Area | Files |
|------|-------|
| Intelligence layer | `backend/intelligence.py` — analyst rules, streaming, source collection, truncation guard |
| Analyst prompts | `backend/agents.py` — the three feature prompts, model pool, Q&A / monitor / digest agents |
| API server | `backend/main.py` — FastAPI, SSE endpoints, auth, sync, watch, discover |
| Auth | `backend/auth.py` — bcrypt, JWT, Google OAuth |
| Persistence | `backend/store.py` — SQLite (runs, exchanges, watchlist, scans) |
| Scheduler | `backend/scheduler.py` — background thread: re-validations + digests |
| App shell | `frontend/src/App.tsx` |
| Views | `landing.tsx`, `workspace.tsx`, `library.tsx`, `explore.tsx`, `discover.tsx`, `settings.tsx`, `auth.tsx` |
| Components | `sidebar.tsx`, `pipeline-steps.tsx`, `status-steps.tsx`, `markdown.tsx`, `logo.tsx` |
| Client | `lib/api.ts` (SSE reader + typed clients), `lib/use-analyze.ts` (chat state, sync, polling), `lib/discover-store.ts` |

---

## 7. Verification

| Check | Result |
|-------|--------|
| Venture Intelligence live run | 8–14s, ~5.5k chars, streamed, 3–5 real sources |
| Company X-Ray live run (Paystack) | 6–10s, ~4.5k chars, streamed, 3–5 real sources |
| Discovery live run | 5–10s, 4 ideas emitted progressively, 3–5 real sources |
| Source integrity | Only real, deduplicated URLs; no model-generated links in any run |
| Source relevance | Fintech → CBN + SEC; agriculture → FAO; health → WHO |
| Search-backend outage | Report still streams; sources fall back to the curated tier |
| Regression suites | 4 scripts, all passing, offline (stubbed agents, no quota) |
| Type check | `tsc --noEmit` clean |
| Latency benchmark | `scripts/bench_intelligence.py`, per-phase timing |

---

## 8. Future Enhancements / Future Autonomy

**None of the following is implemented.** These are the roadmap for making
Thrace more autonomous and stronger as a product.

### 8.1 Continuous and scheduled intelligence

- **Continuous market monitoring** — track a venture's market, competitors and
  demand signals continuously rather than validating once at a point in time
- **Automatic trend detection** — identify emerging sectors and shifting
  consumer behaviour without a user prompt
- **Scheduled intelligence updates** — user-defined refresh cadences per idea,
  company or watchlist entry, replacing the fixed weekly re-validation
- **Automated competitor monitoring** — detect new entrants, pricing moves,
  funding events and product launches for tracked companies
- **Notification and alerting** — push or email alerts when a monitored signal
  crosses a threshold, rather than requiring the user to open the app

### 8.2 Memory and learning

- **Persistent startup and idea memory** — retain the full analytical history of
  an idea and track how its assessment evolves over time
- **Learning from user feedback** — capture which recommendations users acted on
  and which they dismissed, and use that signal to calibrate future output
- **Personalised recommendations** — tailor opportunity discovery and analysis
  depth to a user's sector, geography and stage

### 8.3 Opportunity intelligence

- **Opportunity scoring** — a transparent, weighted score per discovered
  opportunity, comparable to the rubric the original pipeline applied to risk
- **Validation-experiment design** — generate cheap, concrete falsification
  tests automatically, including sample sizes and success thresholds
- **Autonomous follow-up research** — trigger deeper retrieval automatically
  where the fast pass found the evidence too thin, rather than either crawling
  by default or never following up

### 8.4 Trust and verification

- **Stronger source verification** — validate that cited URLs resolve and
  support the claim attributed to them, and score source quality
- **Claim-level provenance** — attach evidence to individual claims rather than
  to the report as a whole
- **Recency weighting** — prefer recent sources for fast-moving markets

### 8.5 Product surface

- **Report export** to PDF, DOCX and CSV for submission to banks, investors and
  grant programmes
- **Team and shared workspaces** — collaborative reports and shared watchlists
- **Public API** — let third-party tools request a report programmatically

---

## 9. Out of Scope

Deliberately not part of the system, and not planned as described above:

- Deep recursive crawling of company websites
- A sequential multi-agent research pipeline on the normal request path
- Academic citation graphs or inline `[1][2]` citation systems
- Third-party job queues, vector databases, or microservice decomposition
