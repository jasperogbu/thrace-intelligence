# CHAPTER TWO

## LITERATURE REVIEW

### 2.1 Introduction

This chapter reviews the literature and background concepts relevant to the
design of a startup intelligence platform for business discovery and venture
planning. The review is organised into six areas: entrepreneurship and venture
validation; business intelligence and market analysis; web data acquisition and
processing; large language models and generative AI; quantitative risk scoring;
and multi-agent systems. The chapter concludes with a review of related systems
and a statement of the research gap this project addresses.

### 2.2 Conceptual Review

#### 2.2.1 Entrepreneurship and Venture Validation

Modern entrepreneurship theory places idea validation at the centre of new
venture creation. The lean startup methodology argues that startups should
treat ideas as hypotheses to be tested rapidly and cheaply, before committing
significant resources. Customer development theory similarly insists that
founders must first verify that a real, painful problem exists and that
customers will pay for a solution, before building the product.

Validation, however, is only the first stage of venture planning. A validated
idea must still be examined against its market (size, customer segments,
pricing tolerance), its competition (direct, indirect, and informal
alternatives), its risk profile, and its practical execution requirements —
capital, funding options, go-to-market strategy, regulatory obligations, and a
phased roadmap. In emerging markets this planning is complicated by thin
formal data coverage: statistics about secondary cities, informal-sector
competitors, and local purchasing power are scattered, inconsistent, or simply
unpublished. Entrepreneurs in these environments routinely plan with little
more evidence than personal observation, and venture failure rates reflect it.

A recurring theme in the literature is that the discipline of validation —
explicit verdicts, quantified assessments, and staged planning — separates
deliberate founders from gamblers. Yet the analytical labour required to do
this discipline well is exactly what small founders cannot afford. This is the
tension this project addresses: delivering consultant-grade validation and
planning analysis at negligible marginal cost through automation.

#### 2.2.2 Business Intelligence and Market Analysis

Business intelligence practice establishes a general principle that this
project applies: an analysis is only as useful as the structure it imposes on
incomplete information. Analysts working with sparse or partial data rely on a
fixed analytical frame — defined questions, consistent categorisation, and
explicit separation of observation from inference — because a free-form
narrative invites the reader to accept conclusions that the evidence does not
support.

Two properties of BI practice transfer directly to this problem. The first is
**structural consistency**: the same analytical questions are answered in the
same order every time, so that two analyses of different subjects can be
compared. The second is **explicit provenance of uncertainty**: a professional
analysis distinguishes what is known from what is estimated, and attaches an
assumption to every figure it cannot source.

Thrace adopts both. Each report follows a fixed section list, and the analyst
is required to label estimated figures and state the assumption behind them.
Section 3.4 of Chapter Three describes how these constraints are implemented
and why the language discipline is a functional requirement rather than a
stylistic preference.

#### 2.2.3 Web Data Acquisition and Processing

Three techniques are relevant to acquiring venture-planning evidence:

- **Web search** returns ranked results with titles, URLs and snippets, quickly
  and cheaply, without downloading page bodies.
- **Web crawling** systematically downloads pages by traversing links,
  providing the full text of a site rather than a snippet.
- **Web scraping/extraction** converts page content into clean text or
  structured fields by stripping markup and boilerplate.

The trade-off between them is central to this project's design. Search is fast
and cheap but returns snippets; crawling yields full text but is slow,
expensive, and open-ended, since a single site can expand into hundreds of
pages. For a system whose output must appear in seconds, the cost profile
favours search decisively, and the depth that crawling would provide is not the
constraint that matters most.

In this project, the Firecrawl API is used for **search only**, and only for
source collection. Search results supply genuine URLs which the backend
attaches to the completed report; pages are not crawled and no analyst browses
them. The analytical content of a report is produced by the model from its own
pretrained knowledge, so no claim in the report depends on a retrieved page
being read. This separation is deliberate: it is what allows source retrieval
to be optional, and to fail without affecting the report. See Section 3.5.

#### 2.2.4 Large Language Models and Generative AI

Large language models are deep neural networks trained on massive text corpora.
Their relevance to this problem rests on three capabilities.

**Pretrained domain knowledge.** Language models encode substantial
information about industries, business models, market structures and
competitive dynamics acquired during pretraining. For well-trodden domains this
is a usable analytical substrate without retrieval.

**Instruction following.** Modern instruction-tuned models accept a detailed
specification and conform to it, which makes it possible to constrain an
analyst's structure, register and honesty in a system prompt. This is the
mechanism by which the report format and the language discipline in Section 3.4
are enforced.

**Streaming generation.** Tokens are produced incrementally, so a response can
be transmitted as it is written. This converts generation latency from a
blocking wait into a progressive experience and is the basis of the streaming
protocol in Section 3.6.

Two limitations are equally relevant. Language models are prone to
**hallucination** — producing plausible but unverified entities, figures and
citations — which is the central risk in a business-advice context and the
subject of Section 3.5. They are also **non-deterministic**: two runs on the
same input may differ, which is why this project does not present a single
composite score and instead decomposes judgement across named sections where a
reader can locate and assess each dimension separately.

#### 2.2.5 Quantitative Venture Assessment

Quantitative venture assessment has a long history, from credit-scoring
techniques to weighted multi-criteria decision analysis. The consistent lesson
is that decomposing a judgement into explicit, weighted dimensions improves
calibration and transparency compared with holistic intuition. Classic
frameworks — SWOT analysis, weighted scoring models, and stage-gate
feasibility reviews — all share this decomposition principle.

This project retains the decomposition principle but not the composite score. A
single weighted probability is avoided for a specific reason: the model
supplies both the inputs and the arithmetic, and the inputs are estimates. A
number with banded thresholds presents an appearance of precision that the
underlying evidence does not support, and a reader has no way to audit the
inputs. The report instead separates Opportunity, Target Customers, Market,
Competition, Business Model, Key Risks and Validation Plan into distinct
sections, so that a reader can see which dimensions are well evidenced and
which are judgement, and can interrogate any of them with a follow-up question.

#### 2.2.6 Multi-Agent Systems

A multi-agent system (MAS) is composed of multiple interacting intelligent
agents, each with a scoped role and limited tools, coordinated to decompose a
task that exceeds the competence of a single agent. The literature reports
benefits — parallelism, specialisation, and fault isolation — alongside
significant costs: coordination overhead, inter-agent error propagation, and
markedly higher latency, since a sequence of agents multiplies the wall-clock
time of the slowest one.

The design decision in Section 3.4 is made against this background. A staged
agent architecture is appropriate when a task genuinely decomposes and when
per-stage evidence retrieval is required. It is a poor fit when a single
reasoning pass over pretrained knowledge can produce the deliverable, because
the coordination cost is then paid without corresponding benefit. Thrace uses
one analyst with a shared system prompt across all three features; the three
capabilities differ in their user prompt and output ceiling, not in execution
strategy.

### 2.3 Review of Related Systems

#### 2.3.1 Market-Research Databases

Commercial databases (CB Insights, Crunchbase) aggregate structured
company records. They are strong on funded, developed-market companies and
weak in exactly the segments this project targets: pre-seed ideas, informal
local competition, and secondary cities in emerging markets, which are
systematically under-recorded. They also answer questions about companies that
already exist, not about whether a proposed idea should be pursued.

#### 2.3.2 Business-Planning Software

Business Model Canvas tools and template planners structure the founder's own
assumptions. They generate no external evidence; the output is only as good as
the founder's prior knowledge, and the analytical work is not performed at all.

#### 2.3.3 Social-Listening Tools

Brandwatch and comparable platforms monitor brand mentions across social
channels. They serve established brands tracking their own perception and
cover a single analytical dimension. The actor and the question are both
different from an aspiring founder validating a new idea.

#### 2.3.4 General-Purpose Conversational Assistants

The most important related system is not a specialised tool but the general
conversational assistant, because it is what a founder will otherwise open.
These systems can produce a competent business analysis, and on raw output
quality they are difficult to beat. Their differences from a purpose-built
platform are structural rather than qualitative:

- **No fixed analytical frame.** A conversational assistant answers the question
  asked. It does not reliably apply a consistent section structure, so two runs
  on the same idea may not be comparable.
- **No evidence boundary.** There is no separation between what the model knows
  and what it has been verified against, and no mechanism preventing invented
  citations.
- **Interaction cost.** Obtaining a structured report requires a sequence of
  prompt engineering by the user, who must specify format, depth, sections and
  constraints.
- **No continuity.** Analyses are not retained, versioned, or comparable over
  time, and cannot be watched for change.

#### 2.3.5 Multi-Agent Intelligence Demonstrators

Open-source multi-agent demonstrators have shown that teams of tool-equipped LLM
agents can produce competitor, sentiment, and metrics reports for a given
company. These validate the underlying architecture and directly informed the
design of the Company X-Ray capability. The comparison is developed in Chapter
Five.

### 2.4 Summary of the Gap

The review identifies the following gaps:

1. No existing consumer-accessible tool **validates a raw business idea** and
   then carries the analysis through market sizing, competition, business model,
   risk, and validation planning in one integrated, consistently structured
   flow.
2. Existing tools are **not location-aware** in emerging-market contexts; none
   reason about a specific city's market, costs, informal competitors, or
   regulatory steps (e.g., CAC registration in Nigeria).
3. Tools that analyse companies are **fragmented by dimension** (data,
   sentiment, or metrics) and manual in operation.
4. Where generative systems do offer venture analysis, they offer no
   **source-integrity guarantee** — the model may produce plausible but
   unverified URLs — and no fixed report structure, so that two analyses of the
   same idea are not comparable.
5. Retrieval-heavy architectures are **too slow for conversational use**,
   returning minutes after submission, which forecloses the rapid
   compare-several-ideas workflow that most founders actually want.
6. Few tools **propose opportunities** to a founder who does not yet have a
   specific idea.

This project addresses these gaps with a fast single-analyst platform that
produces a fixed, decision-ready report within seconds, separates model
knowledge from verified sources, guarantees real clickable links, and extends
to opportunity discovery.

### 2.5 Summary

This chapter reviewed entrepreneurship and validation theory, business
intelligence, web data acquisition, large language models, risk-scoring
frameworks, and multi-agent systems, and examined related tools. The review
established the gap: no fast, location-aware, source-integrity-guaranteed system
validates business ideas and generates complete venture planning intelligence.
The next chapter presents the methodology adopted to fill this gap.
