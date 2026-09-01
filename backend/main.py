"""
JASPA backend API.

FastAPI server that exposes the multi-agent intelligence engine over HTTP with
Server-Sent Events (SSE) streaming.
"""
import json
import os
import queue
import threading
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import agents

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

app = FastAPI(
    title="JASPA API",
    description="Autonomous Startup Intelligence Platform - multi-agent API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    company: str
    analysis_type: str = "competitor"


class HealthResponse(BaseModel):
    status: str
    model: Optional[str] = None
    agents: Optional[list[str]] = None
    ready: bool
    error: Optional[str] = None


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    status = agents.team_status()
    return HealthResponse(
        status="ok",
        model=status["model"],
        agents=status["agents"],
        ready=status["ready"],
        error=status["error"],
    )


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    company = req.company.strip()
    analysis_type = req.analysis_type.strip().lower()

    if not company:
        raise HTTPException(status_code=400, detail="Company name is required.")
    if analysis_type not in agents.ANALYSIS_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"analysis_type must be one of {sorted(agents.ANALYSIS_TYPES)}",
        )

    status = agents.team_status()
    if not status["ready"]:
        raise HTTPException(
            status_code=503,
            detail="JASPA is not ready. Configure OPENAI_API_KEY and FIRECRAWL_API_KEY in .env",
        )

    def generate():
        q: queue.Queue = queue.Queue()

        def emit(event_type: str, data):
            q.put({"type": event_type, "data": data})

        def worker():
            try:
                emit("status", {"label": "Searching the web", "detail": f"Scanning live sources for {company}..."})
                bullets = agents.run_bullets(analysis_type, company)

                emit("status", {"label": "Synthesising insights", "detail": "Agents are reasoning over the gathered evidence..."})
                emit("stage_start", {"stage": "report"})

                for delta in agents.stream_report(analysis_type, company, bullets):
                    emit("delta", delta)

                emit("done", {})
            except Exception as exc:  # noqa: BLE001
                emit("error", {"message": str(exc)})

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        try:
            while thread.is_alive() or not q.empty():
                try:
                    item = q.get(timeout=0.5)
                except queue.Empty:
                    continue
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        finally:
            thread.join(timeout=2)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
