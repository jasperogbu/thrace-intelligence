# JASPER — Setup Commands & Development Log

> Project: Autonomous Startup Intelligence Platform
> Project folder: `/Users/mac/Documents/AI Projects/Final Year Projects/startup-intelligence-platform`

---

## Part 1 — Setup & Run Commands

### 1. Create and activate a virtual environment

```bash
cd "/Users/mac/Documents/AI Projects/Final Year Projects/startup-intelligence-platform"
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure API keys

Create a `.env` file in the project root (already created):

```ini
OPENAI_API_KEY=sk-REPLACE_WITH_YOUR_OPENAI_API_KEY
FIRECRAWL_API_KEY=fc-REPLACE_WITH_YOUR_FIRECRAWL_API_KEY
```

### 4. Run the app

```bash
streamlit run startup_intelligence_agent.py
```

Or, to run in the background and keep working in the terminal:

```bash
nohup .venv/bin/streamlit run startup_intelligence_agent.py --server.port 8501 > /tmp/streamlit_live.log 2>&1 &
```

App URL: <http://localhost:8501>

### 5. Restart the app (after code changes)

```bash
pkill -f "streamlit run startup_intelligence_agent.py"
nohup .venv/bin/streamlit run startup_intelligence_agent.py --server.port 8501 > /tmp/streamlit_live.log 2>&1 &
```

### 6. Stop the app

```bash
pkill -f "streamlit run startup_intelligence_agent.py"
```

### 7. Quick health check

```bash
curl -s http://localhost:8501/_stcore/health    # returns "ok" if running
```

---

## Part 2 — Development Log

### Files in the project

| File | Purpose |
|------|---------|
| `startup_intelligence_agent.py` | Main Streamlit application (multi-agent system) |
| `requirements.txt` | Python dependencies |
| `README.md` | Project documentation (rewritten to match the proposal) |
| `.env` | API keys (OpenAI + Firecrawl) |
| `.gitignore` | Prevents committing secrets / venv to Git |

### Timeline of work completed

1. **Fixed startup bug** — Removed a stray leading space on line 1
   (` import streamlit as st`), which caused a `SyntaxError` and stopped the app
   from launching at all.

2. **Installed dependencies** — Created/used the `.venv` virtual environment and
   installed all packages from `requirements.txt` (`streamlit`, `agno`,
   `firecrawl`, `openai`, `python-dotenv`).

3. **Verified app launch** — Confirmed the Streamlit server starts cleanly
   (HTTP 200, health endpoint `ok`, no errors).

4. **Rewrote project documentation** — `README.md` fully rewritten to match the
   JASPER PROJECT PROPOSAL: Introduction, Problem Statement, Aim & Objectives,
   ️System Architecture (3 agents), Data Collection & Processing, Multi-Agent
   Workflow, Report Generation, System Interface, Technology Stack, Expected
   Outcomes, and Conclusion. No references to the original tutorial remain.

5. **Rebranded the application** — Updated titles, agent names, team name, and
   sidebar to match the proposal:
   - App title: **JASPER — Autonomous Startup Intelligence Platform**
   - Agents: **Startup / Competitor Analysis Agent**, **Market Sentiment
     Analysis Agent**, **Performance Metrics Agent**
   - Team: **JASPER Intelligence Team**

6. **Model & framework changes**:
   - OpenAI model upgraded to **GPT-5**, then switched back to **GPT-4o** at
     the user's request (all 4 agent/model references).
   - agno pinned to **`agno>=3`** and installed version **3.0.4**.

7. **Fixed agno 3.x incompatibility** — `FirecrawlTools(search=True, crawl=True)`
   raised `TypeError` on agno 3.x. Updated to the new API:
   `FirecrawlTools(enable_search=True, enable_crawl=True, poll_interval=10)`.
   Applied to all three agents.

8. **Created VS Code workspace** — `~/Documents/VS Code/JASPER.code-workspace`
   (folder + workspace file with the venv interpreter pre-configured), and
   opened the project in VS Code.

9. **Configured API keys** — Created `.env` with placeholders for
   `OPENAI_API_KEY` and `FIRECRAWL_API_KEY`, plus a `.gitignore` so keys are
   never committed to Git.

10. **Streamlit first-run prompt disabled** — Created `~/.streamlit/credentials.toml`
    and `~/.streamlit/config.toml` so the email prompt no longer blocks startup.

11. **App launched and verified live** at <http://localhost:8501> with the fixes
    applied.

---

## Part 3 — Future Upgrade Roadmap

The current app is a solid, working baseline. The following upgrades will make it
more sophisticated, modern, and closer to the fully "autonomous, continuously
monitoring" platform described in the proposal.

### Analysis depth
- **Multi-region / multi-market expansion** — analyze a startup across different
  geographies.
- **Trend tracking over time** — store historical runs so sentiment and metrics
  can be charted over weeks/months (matches the proposal's "continuously
  monitors" promise).
- **New specialized agents** — fundraising / funding-round analysis, hiring
  signals, regulatory risk.

### Data & reliability
- **Structured data persistence** — SQLite or Postgres so results are saved and
  queryable instead of discarded after each run.
- **Scheduled / automated runs** — cron-based scheduling so the platform truly
  runs autonomously.
- **Deduplication + source verification** — reduce noise and improve evidence
  quality.

### UX & polish
- **Interactive charts** — Streamlit native charts or Plotly for sentiment
  breakdowns and KPI trends.
- **Export to PDF / DOCX / CSV** — for report submission and sharing.
- **User accounts, history, dark mode** — better caching for lower cost and
  faster responses.

### Engineering
- **Advanced agent patterns** — task routing, reflection / self-critique loops,
  and RAG over collected documents.
- **Tests + CI** — automated tests and a CI pipeline.
- **Dockerfile** — one-command deployment.
- **Cloud deploy** — Hugging Face Spaces or Streamlit Community Cloud for a
  live, shareable demo.

> **Status:** No upgrades from this roadmap have been implemented yet. The app
> remains the working v1 baseline as of the submission.
