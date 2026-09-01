# JASPA — Autonomous Startup Intelligence Platform

An AI-powered platform for business opportunity discovery and venture planning.
Enter any company and a coordinated team of autonomous AI agents scours the live
web — weighing competitive positioning, market sentiment and performance signals
into one clear, evidence-backed report.

Built as a modern full-stack product: a React + Tailwind CSS + shadcn/ui frontend
with a FastAPI backend wrapping a multi-agent LLM engine (Agno + OpenAI + Firecrawl).

---

## Architecture

```
frontend/   React 19 + TypeScript + Vite + Tailwind CSS v4 + shadcn/ui
backend/    FastAPI + Agno multi-agent team (OpenAI GPT-4o + Firecrawl)
start.sh    One-command launcher (backend + frontend)
stop.sh     Stop both servers
```

### Multi-agent team

| Agent | Role |
|-------|------|
| **Startup / Competitor Analysis Agent** | Positioning, launch strategy, strengths, weaknesses |
| **Market Sentiment Analysis Agent** | Positive/negative perception drivers across social & review platforms |
| **Performance Metrics Agent** | Public KPIs, adoption signals, press traction |

Analyses run in two stages — evidence bullets first, then a streamed, structured
Markdown report (tables, recommendations, source URLs) rendered live in the UI.

## Requirements

- Python 3.10+
- Node.js 20+
- API keys in `.env`:
  ```ini
  OPENAI_API_KEY=sk-...
  FIRECRAWL_API_KEY=fc-...
  ```

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
| `/api/health` | GET | Service status, model, agents, readiness |
| `/api/analyze` | POST | Run an analysis; streams SSE events (`status`, `delta`, `done`, `error`) |

```bash
curl -N -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"company":"OpenAI","analysis_type":"competitor"}'
```

`analysis_type` ∈ `competitor` | `sentiment` | `metrics`
