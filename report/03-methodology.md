# CHAPTER THREE

## METHODOLOGY

### 3.1 Introduction

This chapter presents the methodology adopted for the design and implementation
of the Thrace Startup Intelligence Platform for Business Discovery and Venture
Planning. It describes the fast intelligence architecture, the shared analyst
rules that govern output honesty, the source-collection design and its
source-integrity guarantee, the model-selection strategy, the three feature
prompts, the report generation format, the system interface, the technology
stack, and the testing approach used to validate the implementation.

### 3.2 Research Methodology

The project adopted a design-and-implementation methodology suited to producing
a working software artefact. Development proceeded iteratively in five phases:

1. **Requirements analysis** — translating the venture-planning problem into
   functional requirements: idea validation, market and competitor
   intelligence, business modelling, risk, validation planning, company
   analysis, and opportunity discovery.
2. **System design** — defining the single-analyst architecture, the analyst
   honesty rules, the source-collection tiers, the API contract, and the user
   interface.
3. **Implementation** — building the system with the chosen technology stack.
4. **Measurement** — instrumenting the request path to establish where latency
   actually came from, rather than optimising an assumed bottleneck.
5. **Testing and validation** — verifying launch, streaming, source integrity,
   error handling, and end-to-end workflow execution for all three features.

Phase 4 is described in detail in section 3.7 and is the phase that most
### 3.3 System Architecture

The platform is built around a single shared intelligence layer serving three
features. Each request is one streaming model call with no tools, followed by
optional background source collection.

```
                 ┌───────────────────────────────────────────────┐
                 │          User Interface (React 19)            │
                 │   Venture ⇄ X-Ray · Discover · Library         │
                 └───────┬───────────────────────┬───────────────┘
                         │                       │
          POST /api/venture              POST /api/analyze
          POST /api/discover                    │
                         │                       │
        ┌────────────────▼───────────────────────▼───────────────┐
        │              SHARED INTELLIGENCE LAYER                 │
        │                                                       │
        │   FAST_ANALYST_RULES  (honesty constraints)           │
        │   stream_agent()      (1 streaming call, no tools)    │
        │   is_permanent_error() (retry classification)         │
        │   looks_truncated()   (output-cap guard)              │
        │   SourceCollector     (background thread, 3 tiers)    │
        │   render_sources()    (3–5 real links)                │
        └───────┬───────────────────────────────┬───────────────┘
                │                               │
   ┌────────────▼─────────────┐   ┌─────────────▼──────────────┐
   │  VENTURE INTELLIGENCE    │   │  COMPANY X-RAY             │
   │  9 fixed sections        │   │  8 fixed sections          │
   │  ≤1300 output tokens     │   │  ≤1000 output tokens       │
   └──────────────────────────┘   └────────────────────────────┘
   ┌──────────────────────────┐
   │  DISCOVERY               │   4 opportunity cards, framed as
   │  ≤900 output tokens      │   hypotheses worth validating
   └──────────────────────────┘
                │
   ┌────────────▼───────────────────────────────────────────────┐
   │   MODEL LAYER                                             │
   │   latency-aware selection · quota rotation · pacing        │
   │   quarantine · bounded retries · per-feature ceilings      │
   └────────────┬──────────────────────────────────────────────┘
                │
   ┌────────────▼──────────────────────────────────────────────┐
   │   Google Gemini (native SDK) — any OpenAI-compatible       │
   │   provider also supported                                  │
   └───────────────────────────────────────────────────────────┘

   ┌───────────────────────────────────────────────────────────┐
   │  PERSISTENCE & SCHEDULER                                   │
   │  SQLite (local or Turso): users, runs, exchanges,          │
   │  watchlist, meta, password resets, discovery scans        │
   │  Background thread: watched-chat re-validation, digests   │
   └───────────────────────────────────────────────────────────┘
```

**Figure 3.1: High-level architecture. One intelligence layer, three features,
no tools on the request path.**

### 3.4 Design of the Shared Intelligence Layer

Three features share one execution strategy. The design rests on a small number
of decisions, each of which responds to an identified problem.

#### 3.4.1 One streaming call, no tools

The analyst runs with **no tools at all**. It cannot search, cannot browse, and
therefore cannot be delayed by, or fail because of, a retrieval backend. This
is the single most important decision in the system: it makes report generation
a function of the model alone, and makes generation time a function of output
length alone.

The cost is that the model has no fresh evidence. That cost is managed
honestly rather than hidden — see 3.4.2 and section 3.5.

#### 3.4.2 Analyst honesty rules

One system prompt governs every feature, so the three differ only in their user
prompt, never in their honesty constraints. It forbids fabrication of sources,
URLs, citations, statistics, companies, people and funding rounds; requires
that estimates be labelled as estimates with their assumption stated; requires
hedged language for judgements rather than asserted fact; forbids implying
that research was performed; and requires direct, non-repetitive answer.

The rule that the analyst **may never write a URL** is load-bearing. It is what
makes it safe to attach real sources: the model is not trusted with links
because it is not permitted to produce any. Real links are supplied by the
backend.

The prompt also states that another process attaches the links, which removes
any incentive for the model to produce one.

#### 3.4.3 Output ceilings

Generation time scales with output length, so each feature has a hard token
ceiling: 1300 for Venture Intelligence, 1000 for Company X-Ray, 900 for
Discovery, 500 for report Q&A. Dense markdown tokenises at roughly 4–6
characters per token on the model in use, so the venture ceiling corresponds to
roughly a 5.8k-character report.

The ceilings are tuned to **complete** rather than to truncate. A report cut
off mid-sentence reads as a broken product rather than a concise one. A
truncation detector checks finished reports and logs the condition rather than
shipping it silently, and the prompt states an explicit word budget so the
model aims for concision rather than being merely clipped.

The detector is deliberately biased towards silence. Markdown legitimately
ends without sentence punctuation — on a heading, a table row, a blockquote, a
fence, or a short bolded label — and only a long plain-prose line ending on a
bare word is treated as truncation.

#### 3.4.4 Progressive output for Discovery

Discovery emits each opportunity as its block completes rather than after the
whole response, so cards appear while the analyst is still writing. This
requires no change to the streaming contract: the analyser tracks completed
blocks in the accumulated text and yields a structured `idea` event for each.

### 3.5 Design of the Source-Collection Layer

Source collection is a separate concern from generation, and the design goal
was to obtain genuine links **without ever delaying the report**.

#### 3.5.1 The source-integrity guarantee

Three rules together guarantee that no fabricated URL can reach a user:

1. The model is forbidden by system prompt from writing a URL.
2. The renderer is the only component that emits a link, and it formats a list
   of structured source objects — it never accepts free text from the model.
3. Every URL is either returned by an actual search result, or is a known
   official organisation's root domain held in a curated list in source code.

#### 3.5.2 Three tiers

Sources are assembled in descending relevance, each tier filling only what the
tier above left short:

| Tier | Source | Role |
|------|--------|------|
| 1 | Live search results | Most specific; always first |
| 2 | Curated official bodies, scored against the query | Sector and regulator relevance |
| 3 | Broad cross-sector official bodies | Reaches the floor of three |

The curated tier holds 21 official bodies spanning multilateral development
finance, agriculture, industry, trade, health, digital connectivity, national
regulators and development agencies. The result is bounded to a maximum of five
and a minimum of three, deduplicated by URL, and the renderer re-applies the
same rules so a caller that bypassed the collector still cannot emit a stub or
an over-long list. An empty list renders nothing rather than a fabricated
block.

A tier-2 body scores higher for a sector term (*fintech*, *agricultur*,
*health*) than for a catch-all (*market*, *business*), and a local regulator
receives a boost when the query names its country. A query of *"fintech in
Lagos"* therefore leads with the Central Bank of Nigeria and the securities
regulator, while *"agriculture marketplace for farmers"* leads with the FAO.

#### 3.5.3 Non-blocking by construction

The collector runs on a background thread started **before** generation begins,
so by the time the model finishes, retrieval is usually already complete. A
bounded wait follows, and every exception is swallowed. A dead search backend,
an exhausted quota, or a malformed result costs the user their sources and
nothing else. This is also why the search API key is optional: without it the
system falls back to the curated tiers and still emits three to five links.

### 3.6 Design of the Model-Selection Layer

The model layer exists to keep a single call fast and reliable on a free-tier
provider. It makes four decisions.

**Latency-aware selection.** Every call records its time-to-first-token per
model, smoothed as a running mean. Traffic is then weighted by observed speed
with a steep geometric decay by rank, rather than rotated uniformly. This
decision was made on the basis of measurement, not intuition — see 3.7.

**Slow-model quarantine.** A model whose smoothed first-token time exceeds both
a fixed threshold and a multiple of the fastest known model is benched for five
minutes. Ranking alone was insufficient: with a small pool, even a heavily
down-weighted slow model still received double-digit traffic, and one very slow
request is a failed product.

**Lite-model demotion.** A lite-tier model is ranked behind every full model
regardless of observed speed. Pure latency ranking placed roughly half of all
traffic on a lite model, which is a real quality regression for reports that
depend on judgement. Speed must not silently buy a quality drop; lite models
remain the overflow when every full model is benched.

**Quota rotation and bounded retries.** A quota error benches that model for
its provider-reported window and the request transparently retries on another.
Retries are capped at two attempts, two seconds apart, and fire only for
genuine transient failures. Errors indicating an authentication failure,
permission denial, unknown model or malformed request are classified as
permanent and surfaced immediately, since no number of retries can resolve
them.

### 3.7 Measurement-Driven Optimisation

The optimisation pass began by instrumenting the request path to time each
phase separately — request received, model call started, first token, final
token, sources attached, response complete — rather than guessing. The
benchmark harness is retained in the repository and is described in Chapter
Four.

The measurement contradicted the initial hypothesis. Prompt sizes were small
(about 2.3k characters), source retrieval cost approximately zero, and no retry
cycles were firing. The actual cause was model selection: the pool rotated
blindly across sibling models that the same provider served at dramatically
different speeds. Measured on a short prompt, first-token latency ranged from
0.8 seconds to 28 seconds, and roughly a third of all requests were routed to
the slowest model. This is what produced a 2-to-95-second spread in
time-to-first-token across identical requests.

Two further causes were identified and addressed. Output volume dominated
generation time, fixed by the per-feature ceilings and prompts that state
explicit word budgets. Pre-answer reasoning on the model contributed several
seconds of time-to-first-token, reduced by setting the thinking level to low.

The result is set out in Chapter Four. The methodological point is the one
worth carrying forward: the assumed bottleneck was prompt design, and the
measured bottleneck was model routing. Only measurement distinguished them.

### 3.8 Report Generation

**Venture Intelligence** follows a fixed nine-section structure: Executive
Summary (verdict and reasoning) · Opportunity · Target Customers · Market (one
paragraph plus a three-row TAM/SAM/SOM table) · Competition (incumbents,
pricing, and the gap a new entrant could exploit) · Business Model · Key Risks
(each with its mitigation) · Validation Plan (tests ordered cheapest-first,
each naming what result would falsify the idea) · Recommended Next Steps ·
Sources.

**Company X-Ray** follows eight sections: Company Overview · Product and
Target Market · Business Model · Competitive Position · Strengths · Weaknesses
and Risks · Opportunities · Key Takeaways · Sources, with `sentiment` and
`metrics` variants restructuring the report around perception and KPIs.

**Discovery** emits concise opportunity cards rather than a report, each
framed explicitly as a hypothesis worth validating rather than a finding.

All three terminate with the same Sources section, containing three to five
real, deduplicated, clickable links.

### 3.9 System Interface

The interface was designed around a minimal, chat-style experience:

- **Landing (hero):** a pinned platform banner; a headline that changes with
  the mode; a segmented toggle between **Venture Intelligence** (default) and
  **Company X-Ray**; one input whose placeholder adapts to the mode.
- **Workspace:** chat-like view — user request bubble, then the streamed
  response rendered as Markdown with tables and clickable source links. A
  compact status indicator shows while the first tokens arrive; progressive
  rendering is the normal case, not a special one.
- **Sidebar:** collapsible, with new chat, library, explore, discover, and
  settings, plus a searchable chat history grouped by recency with a Pinned
  section and per-item pin/delete actions.
- **Discover:** a focus input and a scan action producing opportunity cards;
  each card carries a one-click *validate* action that launches the idea
  directly into Venture Intelligence. Scans persist per account.
- **Library:** a gallery of completed reports with previews.
- **Settings:** live system status from `/api/health`, a manual scheduler
  trigger, theme switching (dark/light/system), and history management.
- **Authentication:** an account screen with email/password, Google sign-in,
  and a two-step password reset. On laptop and desktop widths the sign-in and
  register views are laid out as two columns with a product hero, the hero and
  the form swapping sides between the two modes; below 1280px the hero is not
  rendered and the form occupies a single centred column.
- **Post-authentication routing:** entering a signed-in state — by signing in,
  or by loading the app with an existing session — always lands on a new chat.
  History is retained and listed in the sidebar; only the selection is cleared.
- **Persistence & theming:** history persists in `localStorage` and syncs to
  the server; light and dark palettes are both supported.

### 3.10 Technology Stack

Only technologies actually used by the implementation are listed.

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Programming Language | Python (v3.13) | Backend development and AI integration |
| Web Framework | FastAPI | REST API with SSE streaming |
| ASGI Server | Uvicorn (standard) | Application server and SSE transport |
| Frontend Library | React 19 | User interface |
| Language | TypeScript (~6.0) | Frontend type safety |
| Build Tool | Vite (v8) + @vitejs/plugin-react | Dev server and production bundling |
| CSS | Tailwind CSS v4 | Utility-first styling |
| UI Primitives | shadcn/ui on Radix UI | Button, dialog, select, sheet, tooltip and related primitives |
| Utilities | class-variance-authority, clsx, tailwind-merge | Variant handling and class composition |
| Markdown | react-markdown + remark-gfm | Report rendering with tables and links |
| Icons | lucide-react | Interface iconography |
| Theming | next-themes | Dark/light/system colour scheme |
| Notifications | sonner | Toast notifications |
| Fonts | @fontsource-variable (Geist, JetBrains Mono, Newsreader) | Self-hosted variable fonts |
| Linting | oxlint | Frontend linting |
| AI / ML | Google Gemini via google-genai (default gemini-3.8-flash) | Reasoning and report generation |
| Agent Framework | Agno (>=3) | Agent construction and streaming |
| Source Retrieval | Firecrawl (optional) | Live web search for source links |
| HTTP Client | httpx | Google OAuth token and profile exchange |
| Authentication | bcrypt + PyJWT | Password hashing and session tokens |
| Persistence | SQLite via libsql-experimental, or Turso | Chats, exchanges, watchlist, accounts |
| Email | Python smtplib (stdlib) | Password-reset delivery |
| Streaming | Server-Sent Events | Real-time delivery of report deltas |
| Environment | python-dotenv | API key and configuration loading |
| Version Control | Git | Project management and versioning |

### 3.11 Testing Approach

The system was tested at several levels:

- **Import and syntax verification** of backend modules, with `pyflakes` for
  unused imports and undefined names.
- **Launch testing:** backend health endpoint and frontend production build.
- **Streaming verification:** live SSE runs confirming ordered `status`,
  `stage_start`, `delta` and `done` events.
- **Workflow testing:** Venture Intelligence against a real business idea;
  Company X-Ray against a real company; Discovery against a real sector focus.
- **Source-integrity testing:** automated checks that every report's Sources
  section contains between three and five deduplicated, real URLs, across a
  range of query types, under three conditions — no search backend, a search
  backend returning a single result, and a search backend returning only
  duplicates. Relevance is asserted directly, so that a fintech query is led by
  a fintech regulator, an agricultural query by the FAO, and a healthcare
  query by the WHO.
- **Degradation testing:** simulated source-retrieval failure confirms the
  report still streams and no Sources block is fabricated.
- **Error handling:** verification that a failed generation surfaces as a clear
  SSE `error` event rather than a silently blank report, that a run producing
  no output raises rather than closing a successful-looking blank, and that
  missing API keys produce actionable messages.
- **Authentication testing:** password-reset tokens verified single-use,
  one-hour expiry, one live token per user, hashed-at-rest, short-password
  rejection, and an identical response for known and unknown addresses.
- **Regression suites:** offline scripts run against stubbed agents, so they
  consume no provider quota. They cover source integrity, truncation
  detection, retry classification, model-selection weighting, and discovery
  block parsing. A separate live probe exercises a real venture run end to
  end.
- **Latency benchmarking:** a retained harness times each phase of a real
  request separately, so optimisation targets the measured bottleneck.

### 3.12 Summary

This chapter described the methodology: the single-analyst architecture and the
reasoning behind it, the shared honesty rules, the three-tier source-collection
design and its source-integrity guarantee, the latency-aware model-selection
strategy, the measurement process that identified the true bottleneck, the
report formats, the interface design, the technology stack, and the testing
approach. The next chapter presents the implementation and the measured
results.
