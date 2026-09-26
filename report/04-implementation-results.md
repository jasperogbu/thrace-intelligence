# CHAPTER FOUR

## SYSTEM IMPLEMENTATION AND RESULTS

### 4.1 Introduction

This chapter describes the implementation of the Thrace platform and presents
the results obtained. It covers the project structure, the shared intelligence
layer, the model layer, the three feature prompts, the backend API with SSE
streaming, the authentication flow, the user interface, the reports the system
generates, and the measured latency. Testing results are tabulated at the end
of the chapter.

The implementation reflects the design position stated in Chapter One:

> **Fast intelligence first.**

Concretely, this means one analyst per request with no tools on the request
path, a per-feature output ceiling, and source collection that runs on a
background thread and is architecturally incapable of delaying the report.

### 4.2 Project Structure

```
startup-intelligence-platform/
├── backend/
│   ├── intelligence.py             # 621 lines. Shared layer: analyst rules,
│   │                               #   stream_agent, error classification,
│   │                               #   truncation guard, SourceCollector
│   ├── agents.py                   # 1353 lines. Model layer + prompts:
│   │                               #   latency-aware selection, quota
│   │                               #   rotation, quarantine; feature prompts;
│   │                               #   monitoring, digest and Q&A agents
│   ├── main.py                     # 573 lines. FastAPI server, SSE endpoints,
│   │                               #   auth routes, sync, watchlist, discover
│   ├── auth.py                     # 325 lines. bcrypt, JWT, Google OAuth,
│   │                               #   password reset
│   ├── store.py                    # 569 lines. SQLite (local or Turso)
│   ├── scheduler.py                # 135 lines. Background re-validation + digest
│   └── requirements.txt
├── frontend/
│   ├── public/thracehero.webp      # Auth-screen hero image
│   └── src/
│       ├── App.tsx                 # Shell, routing, view state
│       ├── components/
│       │   ├── landing.tsx         # Hero: mode toggle + adaptive input
│       │   ├── workspace.tsx       # Chat-like streaming report view
│       │   ├── discover.tsx        # Opportunity scan + idea cards
│       │   ├── sidebar.tsx         # Collapsible nav + grouped history
│       │   ├── library.tsx         # Saved reports gallery
│       │   ├── explore.tsx         # One-click example prompts
│       │   ├── settings.tsx        # Status, scheduler trigger, theme, data
│       │   ├── auth.tsx            # Sign-in / register / password reset
│       │   ├── status-steps.tsx    # Generation status indicator
│       │   ├── pipeline-steps.tsx  # Stage tracker component
│       │   ├── markdown.tsx        # Report rendering (tables, links)
│       │   ├── logo.tsx
│       │   └── ui/                 # 16 shadcn/Radix primitives
│       └── lib/
│           ├── api.ts              # SSE reader + typed clients
│           ├── use-analyze.ts      # Run state machine, persistence, polling
│           ├── discover-store.ts   # Discovery scan state
│           ├── auth.tsx            # Session context
│           └── utils.ts            # Class-name helper
├── scripts/
│   ├── bench_intelligence.py       # Per-phase latency harness
│   ├── test_xray_guard.py          # Regression suite
│   ├── test_venture.py             # Live end-to-end probe
│   ├── test_discovery_ideas.py
│   ├── test_quota_failfast.py
│   └── render_report.py            # This report → .docx / .pdf
├── start.sh / stop.sh
├── .env                            # API keys and configuration
└── report/                         # This project report
```

### 4.3 Implementation of the Shared Intelligence Layer

`backend/intelligence.py` is the strategic core of the platform and is shared
verbatim by all three features.

**Analyst rules.** A single system prompt, passed as the agent description,
constrains output for every feature. Its load-bearing clause is the second:

```
- Never fabricate sources, URLs or citations. Another process attaches
  real links to the report for you; your job is the analysis, not the
  sourcing. Do not print a "Sources" section and do not mention that
  sources were or were not checked.
```

Telling the model that links are supplied for it removes any incentive to
produce one.

**Streaming.** `stream_agent` iterates the agent's event stream and yields
`delta` events. On a transient failure it retries once on a fresh agent, first
emitting a `reset` event so the client discards partial text rather than
showing two stitched attempts.

**Error classification.** `is_permanent_error` matches authentication
failures, permission errors, unknown model ids and malformed requests;
`is_transient_error` matches capacity and quota errors. An `_error_text` helper
normalises error content, which the framework sometimes populates with a
non-string object that would otherwise be rendered to the user as a raw HTTP
response object.

**Truncation guard.** `looks_truncated` inspects the final line of a report and
reports whether generation appears to have been cut mid-sentence. It is biased
towards silence: headings, table rows, blockquotes and fences legitimately end
without punctuation, and a short bolded label is a deliberate fragment. Only a
long plain-prose line ending on a bare word is treated as truncation. A report
that trips the guard is logged with its length and the applicable ceiling.

### 4.4 Implementation of Source Collection

`SourceCollector` runs on a daemon thread. Its lifecycle is deliberately
simple: `start()` is called **before** generation begins, and `results()` is
called after the report is complete, with a bounded wait.

`_run` populates the list in three tiers, deduplicating by URL and never
exceeding the configured maximum. `_official_fallback` scores each of the 21
curated official bodies against the query, weighting sector terms above
catch-alls and boosting a local regulator when the query names its country. If
the result is still short, broad cross-sector bodies fill it to the floor.

`render_sources` re-applies the same rules at the boundary, so a caller that
bypassed the collector still cannot emit a stub or an over-long list. An empty
list renders nothing rather than a fabricated block.

### 4.5 Implementation of the Model Layer

`agents.py` owns the model client. Four decisions are implemented.

**Latency tracking.** `_record_latency` folds each call's time-to-first-token
into a running mean per model, and quarantines a model that is both slower than
a fixed threshold and a multiple of the fastest known model.

**Weighted selection.** `_next_model` sorts usable models by an effective
latency — with the lite-model penalty applied — and walks a cumulative weight
distribution with a 0.15 decay per rank. The fastest usable model therefore
receives the large majority of traffic and the tail a small fraction, so a slow
model no longer costs the user a very long wait on a predictable fraction of
requests.

**Lite-model demotion.** `_rank_key` adds a large penalty to any model id
containing `lite`, so it sorts behind every full model regardless of measured
speed.

**Bounded, classified retries.** Two attempts, two seconds apart, and only for
errors classified as transient. Permanent errors short-circuit the retry
entirely.

Output ceilings are applied per feature at model construction, and the Gemini
thinking level is set to low, which removes several seconds of pre-answer
reasoning from time-to-first-token.

### 4.6 Implementation of the Feature Prompts

Each feature supplies a distinct user prompt and an output ceiling; the system
prompt and honesty rules are shared.

**Venture Intelligence** fixes a nine-section structure and gives each section
a word budget, with an explicit instruction that no section may repeat
another's content and that the sections are the whole report with no preamble
or closing summary.

**Company X-Ray** fixes eight sections for `competitor` analyses, with
`sentiment` and `metrics` variants restructuring the report around perception
and KPIs. A user-supplied URL is detected and passed to the model as a hint
about which company is meant, with an explicit instruction that the site was
not visited and nothing only visible on it may be claimed.

**Discovery** proposes exactly four opportunities and enforces the framing rule
the product depends on: ideas are *hypotheses worth validating*, never
findings. The prompt directs the analyst to say "appears worth validating" and
"the first thing to test", never "the market is proven" or "demand is
confirmed", and to state the specific thing that should be tested first. It
runs with no tools, so it cannot be delayed by a search backend.

### 4.7 Implementation of the Backend API

The FastAPI backend exposes 24 endpoints across intelligence, authentication
and persistence.

- **`GET /api/health`** — readiness, active model, feature list, analyst
  roster. A model key is required; the search API key is explicitly *not*,
  because source retrieval is optional by design.
- **`POST /api/venture`** — `{ "idea": string }` → `status`, `stage_start`,
  `delta` events, then `done` or `error`.
- **`POST /api/analyze`** — `{ "company", "analysis_type" }` → the same event
  shape.
- **`POST /api/discover`** — `{ "focus"? }` → `delta` and `idea` events, then
  `done`.
- **`POST /api/ask`** — `{ "content", "question" }` → an answer grounded
  strictly in the supplied report.

All streaming endpoints execute work on a background thread feeding a queue, so
the server remains responsive while events are flushed. Idle periods emit SSE
comment lines to keep intermediaries from closing the connection. Validation
returns clear HTTP 400/503 errors.

### 4.8 Implementation of Authentication

Accounts support three paths. **Email and password** registration and sign-in
use bcrypt hashing and JWT sessions with a two-week expiry; a bearer token is
sent by the client and resolved by a FastAPI dependency. **Google OAuth 2.0**
runs in a popup with a single-slot anti-forgery state, posting the session
token back to the app via `postMessage`. **Password reset** uses a single-use,
time-limited token: only its SHA-256 digest is stored, so the database never
holds a usable reset link; the forgot-password endpoint returns an identical
response for known and unknown addresses, so it cannot be used to discover
which emails have accounts; requests are throttled per address; and delivery
goes over SMTP when configured.

### 4.9 Implementation of Persistence and the Scheduler

`store.py` abstracts SQLite behind a narrow interface and works unchanged
against a hosted Turso database, normalising the differences between the local
and remote drivers behind the same connection wrapper. Seven tables are
maintained: users, runs, exchanges, watchlist, meta, password resets and
discovery scans.

`scheduler.py` runs a background thread inside the FastAPI process. It
re-validates watched chats when due using the monitoring agent, appending
update exchanges server-side, and generates the in-app intelligence digest when
new monitoring updates exist. A manual trigger is exposed for demonstration.

### 4.10 Implementation of the User Interface

The React interface implements the design described in Chapter Three. The
interface displays a compact status indicator while the first tokens arrive,
after which the streamed report is the primary presentation.

**Workspace staging.** A stage-tracker component is retained in the codebase,
but the current request path emits a single report stage and never signals the
five research stages the component can display. The workspace therefore gates
the tracker on whether any stage has actually activated, and falls back to the
status indicator — so the tracker is not rendered during a normal run.

**Auth screen.** On widths of 1280px and above the sign-in and register views
are two-column, with a product hero image on one side and the form on the
other; toggling between sign-in and register swaps which side the hero
occupies. Below 1280px the hero is not rendered and the form centres as a
single narrow column. The hero is served as WebP.

**Post-authentication routing.** Signing in, and loading the app with an
existing session, both clear the active chat selection and show the new-chat
view. History is retained in the sidebar; only the selection is cleared, so
nothing is lost.

### 4.11 System Output and Results

#### 4.11.1 Venture Intelligence Report

A run on *"AI marketplace for Nigerian farmers"* produces:

```markdown
# Venture Intelligence — AI marketplace for Nigerian farmers

## Executive Summary
**Verdict: PIVOT**
- Marketplace models face significant friction in Nigerian agriculture…
- Shift focus to an AI-enabled B2B supply chain optimisation tool…
- The primary value proposition is for the corporate buyer, not the farmer…

## Opportunity
## Target Customers
## Market                      (paragraph + TAM/SAM/SOM table, figures
                                labelled as estimates with assumptions)
## Competition                 (incumbents, pricing, the gap to exploit)
## Business Model
## Key Risks                   (each with its mitigation)
## Validation Plan             (cheapest-first, with falsification criteria)
## Recommended Next Steps
## Sources
- [NITDA (Nigerian IT Development Agency)](https://www.nitda.gov.ng)
- [FAO (UN Food & Agriculture)](https://www.fao.org)
- [World Bank](https://www.worldbank.org)
- [African Development Bank](https://www.afdb.org)
```

#### 4.11.2 Company X-Ray Output

Eight sections ending in the same Sources block:

```markdown
# Paystack — Company X-Ray
## Company Overview
## Product & Target Market
## Business Model
## Competitive Position
## Strengths
## Weaknesses & Risks
## Opportunities
## Key Takeaways
## Sources
```

#### 4.11.3 Discovery Output

Four opportunity cards, each with a title, a one-line idea runnable as a
venture prompt, and a rationale stating the problem, the target customer, a
possible business model, and the first thing to test. A real run on
*"business opportunities in Nigeria for young people"* returned ideas including
solar-powered cold-chain storage for peri-urban markets, a shared hardware and
training centre for creative freelancers, apprenticeship matching for informal
trades, and on-demand spare-parts delivery to mechanics. The specificity of the
local references indicates the model is reasoning from pretrained knowledge
rather than retrieving, consistent with the no-tools design.

#### 4.11.4 Measured Latency

Recorded with `scripts/bench_intelligence.py`, which times request receipt,
model call start, first token, final token, source attachment and completion
separately. Figures are from the Gemini free tier and vary with model load.

| Feature | Time to first token | Total | Output | Sources |
|---------|--------------------|-------|--------|---------|
| Venture Intelligence | 2–8s | 8–14s | ~5.5k chars | 3–5 |
| Company X-Ray | 2–8s | 6–10s | ~4.5k chars | 3–5 |
| Discovery | 2–6s | 5–10s | ~3.4k chars | 3–5 |

The reduction is attributable to three changes, in order of measured impact:
latency-aware model selection, which removed the routing of a predictable
fraction of requests to a model served at around 28s to first token; per-feature
output ceilings and prompts that state explicit word budgets, which cut Venture
output substantially; and a reduced thinking level, which removed several
seconds of pre-answer latency.

> **Measurement caveat.** The Gemini free tier permits 20 requests per day per
> model. Sustained benchmarking exhausts this allowance, and failures observed
> during measurement are that quota rather than application faults. The figures
> above come from runs that completed.

#### 4.11.5 Testing Results

| Test | Method | Result |
|------|--------|--------|
| Syntax and import | `pyflakes` + module import | Passed — no unused or undefined names |
| Backend launch | Uvicorn start + `/api/health` | Passed — model, features and analyst roster reported |
| Frontend build | `tsc -b && vite build` | Passed (typecheck + bundle) |
| Venture streaming | `POST /api/venture` over SSE | Passed — `status`/`stage_start`, then deltas, then `done` |
| X-Ray streaming | `POST /api/analyze` over SSE | Passed — ordered events |
| Discovery streaming | `POST /api/discover` over SSE | Passed — 4 `idea` events emitted progressively |
| Source count and integrity | 14 query types × 3 backend conditions | Passed — 3–5 deduplicated real links in every case |
| Source relevance | Asserted per sector | Passed — fintech→CBN, agriculture→FAO, health→WHO |
| Search-backend outage | Simulated retrieval failure | Passed — report streamed, no fabricated Sources block |
| Empty report handling | Stubbed silent agent | Passed — raises rather than closing a blank report |
| Retry classification | Auth, bad-request, capacity and quota inputs | Passed — permanent errors not retried, transient ones are |
| Model selection | Simulated pool with known latencies | Passed — slow model receives a minimal share; quarantined model receives none |
| Truncation detection | Markdown/prose cases | Passed — detects cut prose, ignores structural endings |
| Password reset | Live end-to-end | Passed — single use, expiry enforced, no user enumeration, old password rejected |
| Regression suites | 3 offline scripts | Passed — no provider quota consumed |
| Live probe | `test_venture.py` against a running server | Passed — 54 delta events, report generated, no errors |
| Input validation | Empty and oversized idea | Passed — HTTP 400 with clear detail |

### 4.12 Summary

This chapter described the implementation: the shared intelligence layer and its
honesty mechanisms; the three-tier source collector; the latency-aware model
layer; the three feature prompts; the SSE API and its supporting endpoints; the
authentication and persistence layers; and the interface. Measured results
confirm streaming delivery in seconds rather than minutes, concise output, and
3–5 genuine sources on every report. The next chapter discusses these results.
