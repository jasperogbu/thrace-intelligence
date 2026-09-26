# Thrace — Venture Intelligence: Scope & Implementation

> Project: Startup Intelligence Platform for Business Discovery and Venture Planning
> Status: **BUILT & RUNNING** — full stack, verified end-to-end
> Architecture: one streaming analyst per request, with background source collection
> Branding: Thrace, terminal aesthetic, XVII MAY LTD

---

## 1. The Vision

Thrace answers one question for a founder: *is this idea worth pursuing — and if
so, how do I execute it?*

The user types a **business idea** (e.g., *"AI-powered marketplace for Nigerian
farmers"*) and Thrace returns a structured **Venture Intelligence Report**: an
executive verdict, the opportunity, target customers, market sizing,
competition, business model, key risks, a validation plan, recommended next
steps, and a short list of real source links.

A second capability, **Company X-Ray**, applies the same intelligence layer to
an existing company. A third, **Discovery**, proposes business opportunities
*worth validating*.

---

## 2. Architectural Position

### 2.1 The principle

> **Fast intelligence first.**

Thrace uses the model's existing knowledge to produce useful intelligence
immediately, and attaches a small number of real sources when they are
available. It does not perform research before responding.

### 2.2 No tools on the request path

The most consequential decision in the system: the analyst runs with **no
tools at all**. It cannot search, cannot browse, and therefore cannot be
delayed by, or fail because of, a retrieval backend. Generation is a function
of the model alone, which makes latency predictable and failure modes small.

The cost is that the model has no fresh evidence. That cost is managed
honestly rather than hidden — the analyst must label estimates, hedge
judgements, and must never claim that research was performed — and it is
partially offset by real source links attached afterwards (section 5).

### 2.3 What the system does not do

- No web crawling or recursive site inspection
- No agent orchestration on the request path
- No research loop that blocks the response
- No model-generated URLs, ever
- No fabricated statistics, companies, people, funding rounds or citations
- No inline academic citation scheme; a plain link list is used instead

---

## 3. Primary User Journey

1. The user lands on Thrace and types a **business idea** into the hero input.
2. The request is accepted immediately and the first words of the report
   appear within a few seconds.
3. The report streams into the workspace, section by section, while background
   source collection runs independently.
4. The report ends with 3–5 real, clickable source links.
5. The user leaves with an actionable answer, and can ask a follow-up question
   answered strictly from that report.
6. Completed reports are archived in the **Library**; opportunities discovered
   in **Discovery** can be validated with one click.

Entering a signed-in state — by signing in, or by loading the app with an
existing session — always lands on a new chat. Chat history is retained and
listed in the sidebar; only the selection is cleared.

---

## 4. The Three Capabilities

All three share one execution strategy: **one streaming model call, then
optional background sources**.

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

The prompt fixes the section list and gives each section a word budget. Depth
is available on demand through follow-up questions rather than paid for
upfront.

### 4.2 Company X-Ray

Sections for `competitor`: Company Overview · Product & Target Market · Business
Model · Competitive Position · Strengths · Weaknesses & Risks · Opportunities ·
Key Takeaways · Sources. `sentiment` and `metrics` restructure the report around
perception drivers and KPIs.

A URL supplied by the user is passed to the model as a hint about which company
is meant. The site is not fetched.

### 4.3 Discovery

A no-tools analyst proposes four opportunities from pretrained knowledge. Two
rules are enforced in the prompt and are the point of the feature:

- **Language discipline.** Every idea is a *hypothesis worth validating*, not a
  finding. The analyst is instructed to say "appears worth validating" and "the
  first thing to test", and never "the market is proven" or "demand is
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
2. **21 curated official bodies**, scored against the query
3. **Broad cross-sector official bodies** — to reach the floor of three

Relevance is scored, not first-matched, with a locale boost. *"Fintech in
Nigeria"* leads with the Central Bank of Nigeria and the securities regulator
rather than a global institution. The result is always 3–5 deduplicated real
links, capped at five.

Retrieval runs on a background thread started **before** generation, so it is
usually finished by the time the report is. A bounded wait follows, and every
failure is swallowed: a dead search backend, an exhausted quota, or a malformed
result costs the user their sources and nothing else. This is also why
`FIRECRAWL_API_KEY` is optional — without it the curated tiers still emit three
to five links.

### 5.3 Streaming and error handling

`stream_agent` retries a transient failure once on a fresh model; a restart
emits a `reset` event so the client clears partial text rather than showing two
stitched attempts. Permanent errors — bad key, bad model id, malformed request
— are never retried. A run that completes without emitting a single token
raises rather than closing a successful-looking blank report.

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
- **Persistence** — SQLite server-side (optionally hosted on Turso),
  `localStorage` client-side
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
- **Per-feature output ceilings** and a reduced thinking level.

### Streaming protocol (SSE)

| Event | Purpose |
|-------|---------|
| `status` | Progress label + detail |
| `stage_start` / `stage_done` | Report stage transitions |
| `delta` | Incremental report Markdown |
| `reset` | Client clears accumulated text (generation restarted) |
| `idea` | A completed Discovery opportunity card |
| `done` / `error` | Terminal states |

### Authentication

Email and password with bcrypt hashing and JWT sessions, Google OAuth 2.0 via
popup, and password reset by emailed link. Reset tokens are 256-bit secrets
stored as SHA-256 digests, are single-use and expire in one hour; the
forgot-password endpoint returns an identical response for known and unknown
addresses so it cannot be used to discover which emails have accounts.

### Persistence

Seven tables — users, runs, exchanges, watchlist, meta, password resets and
discovery scans. Chats persist both to browser `localStorage` (up to 60, instant
load) and server-side (synced on completion), the latter powering autonomous
re-validation and digests.

### API

| Endpoint | Purpose |
|----------|---------|
| `POST /api/venture` | `{ "idea" }` → streamed Venture Intelligence report |
| `POST /api/analyze` | `{ "company", "analysis_type" }` → streamed Company X-Ray report |
| `POST /api/discover` | `{ "focus"? }` → streamed opportunity cards |
| `POST /api/ask` | `{ "content", "question" }` → streamed answer grounded in the report |
| `POST /api/auth/register`, `/login`, `/me` | Accounts and sessions |
| `GET /api/auth/google/url`, `/callback` | Google popup sign-in |
| `POST /api/auth/forgot-password`, `/reset-password` | Password recovery |
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
| Intelligence layer | `backend/intelligence.py` — analyst rules, streaming, source collection, truncation guard, error classification |
| Analysts and model layer | `backend/agents.py` — feature prompts, model pool, latency-aware selection, monitoring/digest/QA agents |
| API server | `backend/main.py` — FastAPI, SSE endpoints, auth, sync, watch, discover |
| Auth | `backend/auth.py` — bcrypt, JWT, Google OAuth, password reset |
| Persistence | `backend/store.py` — SQLite (local or Turso) |
| Scheduler | `backend/scheduler.py` — background thread: re-validations + digests |
| App shell | `frontend/src/App.tsx` |
| Views | `landing.tsx`, `workspace.tsx`, `library.tsx`, `explore.tsx`, `discover.tsx`, `settings.tsx`, `auth.tsx` |
| Components | `sidebar.tsx`, `status-steps.tsx`, `markdown.tsx`, `logo.tsx`, `ui/` (shadcn primitives) |
| Client | `lib/api.ts` (SSE reader + typed clients), `lib/use-analyze.ts` (chat state, sync, polling), `lib/discover-store.ts`, `lib/auth.tsx` |
| Tooling | `scripts/bench_intelligence.py`, `scripts/test_*.py`, `scripts/render_report.py` |

---

## 7. Verification

| Check | Result |
|-------|--------|
| Venture Intelligence live run | 8–14s, ~5.5k chars, streamed, 3–5 real sources |
| Company X-Ray live run (Paystack) | 6–10s, ~4.5k chars, streamed, 3–5 real sources |
| Discovery live run | 5–10s, 4 ideas emitted progressively, 3–5 real sources |
| Source integrity | Only real, deduplicated URLs; no model-generated links in any run |
| Source relevance | Fintech → CBN + SEC; agriculture → FAO; health → WHO |
| Search-backend outage | Report still streams; sources fall back to the curated tiers |
| Password reset | Single-use token, one-hour expiry, identical response for unknown addresses |
| Regression suites | 4 scripts, all passing, offline (stubbed agents, no quota) |
| Type check and build | `tsc --noEmit` clean; production build succeeds |
| Latency benchmark | `scripts/bench_intelligence.py`, per-phase timing |

---

## 8. Future Enhancements

**None of the following is implemented.** These are directions for making
Thrace more autonomous and a stronger product.

### 8.1 Continuous and scheduled intelligence

- **Continuous market monitoring** — track a venture's market, competitors and
  demand signals continuously rather than validating at a point in time
- **Automatic trend detection** — identify emerging sectors and shifting
  consumer behaviour without a user prompt
- **Scheduled intelligence updates** — user-defined cadences per idea, company
  or watchlist entry, replacing the fixed weekly re-validation
- **Automated competitor monitoring** — detect new entrants, pricing moves,
  funding events and product launches
- **Notification and alerting** — surface alerts when a monitored signal crosses
  a threshold, rather than requiring the user to open the app

### 8.2 Memory and learning

- **Persistent startup and idea memory** — retain the analytical history of an
  idea and track how its assessment evolves
- **Learning from user feedback** — use which recommendations were acted on to
  calibrate future output
- **Personalised recommendations** — tailor discovery and analysis depth to a
  user's sector, geography and stage

### 8.3 Opportunity intelligence

- **Opportunity scoring** — a transparent, weighted score per discovered
  opportunity, so cards can be ranked rather than only read
- **Validation-experiment design** — generate cheap, concrete falsification
  tests with sample sizes and success thresholds
- **Autonomous follow-up research** — trigger deeper retrieval only where the
  fast pass found the evidence too thin

### 8.4 Trust and verification

- **Stronger source verification** — confirm a cited URL resolves and supports
  the claim attributed to it
- **Claim-level provenance** — attach evidence to individual claims rather than
  to the report as a whole
- **Recency weighting** — prefer recent sources for fast-moving markets

### 8.5 Product surface

- **Report export** to PDF, DOCX and CSV
- **Team and shared workspaces** — collaborative reports and shared watchlists
- **Public API** for third-party tools
- **Session revocation** — invalidate outstanding sessions on password reset

---

## 9. Out of Scope

Deliberately not part of the system, and not planned as described above:

- Web crawling of company websites
- Agent orchestration on the request path
- Academic citation graphs or inline `[1][2]` schemes
- Third-party job queues, vector databases, or microservice decomposition
