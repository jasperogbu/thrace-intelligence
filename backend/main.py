"""
Thrace backend API.

FastAPI server exposing the fast intelligence engine over HTTP with
Server-Sent Events (SSE) streaming, plus server-side persistence, an
autonomous scheduler (watchlist re-validation + in-app digests), opportunity
discovery and report Q&A.

Every interactive feature — Venture Intelligence, Company X-Ray and Discovery —
runs the same way: one streaming model call, then optional lightweight source
retrieval that never blocks the response.
"""
import json
import os
import queue
import threading
import time
from contextlib import asynccontextmanager
from typing import Callable, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel
from urllib.parse import urlencode

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import agents
import auth
import scheduler as sched
import store
from scheduler import scheduler

# Serve the built frontend in production (single-service deployment).
# NOTE: normpath is essential — the raw join contains "backend/../frontend"
# which would never match the normalized candidate path in the SPA fallback.
_FRONTEND_DIST = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init_db()
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(
    title="Thrace API",
    description="Autonomous Startup Intelligence Platform - multi-agent API",
    version="1.1.0",
    lifespan=lifespan,
)

_RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")
_allowed_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
if _RENDER_EXTERNAL_URL:
    _allowed_origins.append(_RENDER_EXTERNAL_URL.rstrip("/"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    company: str
    analysis_type: str = "competitor"


class VentureRequest(BaseModel):
    idea: str


class HealthResponse(BaseModel):
    status: str
    model: Optional[str] = None
    agents: Optional[list[str]] = None
    pipelines: Optional[list[str]] = None
    features: Optional[list[str]] = None
    ready: bool
    error: Optional[str] = None


AUTONOMOUS_FEATURES = [
    "persistence",
    "watchlist_revalidation",
    "in_app_digest",
    "opportunity_discovery",
    "report_qa",
    "streaming",
    "lightweight_sources",
]


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    status = agents.team_status()
    return HealthResponse(
        status="ok",
        model=status["model"],
        agents=status["agents"],
        pipelines=status["pipelines"],
        features=AUTONOMOUS_FEATURES,
        ready=status["ready"],
        error=status["error"],
    )


# Idle SSE streams are dropped by some proxies and browsers; a comment line
# every few seconds keeps the connection warm during long research phases.
_SSE_HEARTBEAT_SECONDS = 10


def _sse_stream(worker: Callable[[queue.Queue], None]) -> StreamingResponse:
    """Serve `worker` over SSE, keeping the stream alive while it works.

    `worker` runs on its own thread and publishes event dicts onto the queue it
    is handed. While the queue is idle the response emits SSE comment lines
    (ignored by the client) so a quiet research phase never looks like a dead
    connection.
    """

    def generate():
        q: queue.Queue = queue.Queue()
        thread = threading.Thread(target=worker, args=(q,), daemon=True)
        thread.start()
        last_beat = time.monotonic()
        try:
            while thread.is_alive() or not q.empty():
                try:
                    item = q.get(timeout=0.5)
                except queue.Empty:
                    if time.monotonic() - last_beat >= _SSE_HEARTBEAT_SECONDS:
                        last_beat = time.monotonic()
                        yield ": keep-alive\n\n"
                    continue
                last_beat = time.monotonic()
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
            detail="Thrace is not ready. Configure a model key (LLM_API_KEY, GEMINI_API_KEY or OPENAI_API_KEY) in .env",
        )

    def worker(q: queue.Queue):
        try:
            for event in agents.run_instant_xray(analysis_type, company):
                q.put(event)
            q.put({"type": "done"})
        except Exception as exc:  # noqa: BLE001
            q.put({"type": "error", "message": str(exc)})

    return _sse_stream(worker)


@app.post("/api/venture")
def venture(req: VentureRequest):
    """Generate a Venture Intelligence report for a business idea (SSE stream)."""
    idea = req.idea.strip()

    if not idea:
        raise HTTPException(status_code=400, detail="A business idea is required.")
    if len(idea) > 500:
        raise HTTPException(status_code=400, detail="Idea must be under 500 characters.")

    status = agents.team_status()
    if not status["ready"]:
        raise HTTPException(
            status_code=503,
            detail="Thrace is not ready. Configure a model key (LLM_API_KEY, GEMINI_API_KEY or OPENAI_API_KEY) in .env",
        )

    def worker(q: queue.Queue):
        try:
            for event in agents.run_instant_venture(idea):
                q.put(event)
            q.put({"type": "done"})
        except Exception as exc:  # noqa: BLE001
            q.put({"type": "error", "message": str(exc)})

    return _sse_stream(worker)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: str
    name: str = ""
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/api/auth/register")
def api_register(req: RegisterRequest):
    return auth.register(req.email, req.name, req.password)


@app.post("/api/auth/login")
def api_login(req: LoginRequest):
    return auth.login(req.email, req.password)


@app.get("/api/auth/me")
def api_me(user: dict | None = Depends(auth.resolve_user)):
    if user is None:
        return {"user": None}
    return {"user": user}


# --- Password reset ---------------------------------------------------------
class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    password: str


@app.post("/api/auth/forgot-password")
def api_forgot_password(req: ForgotPasswordRequest):
    """Start a password reset.

    The response is deliberately identical for known and unknown addresses, so
    it cannot be used to discover which emails have accounts. `dev_token` is
    present only when no SMTP server is configured, so the flow is demonstrable
    without a mail server.
    """
    return auth.request_password_reset(req.email)


@app.post("/api/auth/reset-password")
def api_reset_password(req: ResetPasswordRequest):
    """Complete a reset with a single-use token from the reset link."""
    return auth.reset_password(req.token, req.password)


# --- Google OAuth -----------------------------------------------------------
@app.get("/api/auth/google/url")
def google_auth_url(request: Request):
    """Return the Google consent-screen URL for a popup sign-in."""
    if not auth.google_configured():
        raise HTTPException(
            status_code=503,
            detail="Google sign-in is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )
    base = str(request.base_url).rstrip("/")
    params = {
        "client_id": auth.GOOGLE_CLIENT_ID,
        "redirect_uri": f"{base}/api/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        "state": auth.new_oauth_state(),
    }
    return {"url": f"{auth.GOOGLE_AUTH_URL}?{urlencode(params)}"}


@app.get("/api/auth/google/callback")
def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """Google redirects here; hand the session token to the opener via postMessage."""
    frontend = auth.FRONTEND_ORIGIN.rstrip("/")
    if error or not code:
        return RedirectResponse(f"{frontend}/auth?google_error=denied", status_code=302)
    if not auth.check_oauth_state(state):
        return RedirectResponse(f"{frontend}/auth?google_error=state", status_code=302)
    base = str(request.base_url).rstrip("/")
    try:
        google_user = auth.exchange_google_code(code, f"{base}/api/auth/google/callback")
        user = auth._upsert_google_user(google_user)
        token = auth._make_token(user["id"])
    except HTTPException as exc:
        return RedirectResponse(
            f"{frontend}/auth?google_error={urlencode(str(exc.detail))}", status_code=302
        )
    html = (
        "<!doctype html><html><body><script>"
        f"window.opener.postMessage({json.dumps({'type': 'thrace_google_auth', 'user': user, 'token': token})}, '{frontend}');"
        "window.close();"
        "</script></body></html>"
    )
    return HTMLResponse(html)


# ---------------------------------------------------------------------------
# Persistence sync + autonomous updates (user-scoped when signed in)
# ---------------------------------------------------------------------------
class SyncExchange(BaseModel):
    id: str
    query: str
    mode: str
    content: str = ""
    status: str = "done"
    timestamp: float


class SyncRequest(BaseModel):
    run: dict
    exchange: SyncExchange


@app.post("/api/runs/sync")
def sync_run(req: SyncRequest, user: dict | None = Depends(auth.resolve_user)):
    """Upsert a completed chat exchange from the client (fire-and-forget)."""
    user_id = user["id"] if user else None
    store.upsert_run(
        {
            "id": req.run.get("id"),
            "user_id": user_id,
            "query": req.run.get("query", ""),
            "mode": req.run.get("mode", "venture"),
            "pinned": req.run.get("pinned", False),
            "created_at": req.run.get("timestamp", time.time()) / 1000,
        }
    )
    store.upsert_exchange(
        {
            "id": req.exchange.id,
            "run_id": req.run.get("id"),
            "idx": int(req.run.get("exchangeCount", 0)),
            "kind": "user",
            "query": req.exchange.query,
            "mode": req.exchange.mode,
            "content": req.exchange.content,
            "status": req.exchange.status,
            "created_at": req.exchange.timestamp / 1000,
        }
    )
    return {"ok": True}


@app.get("/api/chats")
def list_chats(user: dict | None = Depends(auth.resolve_user)):
    """Full chat history for the signed-in user (empty for anonymous)."""
    user_id = user["id"] if user else None
    return {"chats": store.list_chats(user_id)}


@app.delete("/api/chats/{run_id}")
def delete_chat(run_id: str, user: dict | None = Depends(auth.resolve_user)):
    user_id = user["id"] if user else None
    store.delete_run(run_id, user_id)
    return {"ok": True, "deleted": run_id}


class PinRequest(BaseModel):
    pinned: bool


@app.patch("/api/chats/{run_id}/pin")
def set_chat_pin(run_id: str, req: PinRequest, user: dict = Depends(auth.require_user)):
    store.set_run_pin(run_id, req.pinned, user["id"])
    return {"ok": True, "pinned": req.pinned}


@app.get("/api/updates")
def updates(since: float = 0, user: dict | None = Depends(auth.resolve_user)):
    """Server-originated exchanges (monitor/digest) newer than `since` (epoch s)."""
    user_id = user["id"] if user else None
    return {"updates": store.server_updates_since(since, user_id)}


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------
class WatchRequest(BaseModel):
    run_id: str
    query: str
    mode: str
    interval_hours: Optional[float] = None


@app.get("/api/watchlist")
def get_watchlist(user: dict | None = Depends(auth.resolve_user)):
    user_id = user["id"] if user else None
    return {
        "watching": [
            {
                "run_id": w["run_id"],
                "query": w["query"],
                "mode": w["mode"],
                "interval_hours": w["interval_hours"],
                "last_run": w["last_run"],
            }
            for w in store.list_watch(user_id)
        ]
    }


@app.post("/api/watchlist")
def add_watch(req: WatchRequest, user: dict | None = Depends(auth.resolve_user)):
    user_id = user["id"] if user else None
    store.add_watch(req.run_id, req.query, req.mode, req.interval_hours, user_id)
    return {"ok": True, "watching": req.run_id}


@app.delete("/api/watchlist/{run_id}")
def remove_watch(run_id: str, user: dict | None = Depends(auth.resolve_user)):
    user_id = user["id"] if user else None
    store.remove_watch(run_id, user_id)
    return {"ok": True, "removed": run_id}


@app.post("/api/digest/run")
def run_digest_now():
    """Manually trigger one scheduler cycle (re-validations + digest)."""
    result = sched.scheduler.run_once()
    return {"ok": True, "result": result}


# ---------------------------------------------------------------------------
# Discover scan persistence (per-user, survives logout/login until cleared)
# ---------------------------------------------------------------------------
class DiscoverScanRequest(BaseModel):
    focus: str = ""
    log: str = ""
    ideas: list[dict] = []


@app.get("/api/discover/scan")
def get_discover_scan(user: dict = Depends(auth.require_user)):
    scan = store.get_discover_scan(user["id"])
    if not scan:
        return {"scan": None}
    import json as _json

    return {
        "scan": {
            "focus": scan["focus"],
            "log": scan["log"],
            "ideas": _json.loads(scan["ideas"] or "[]"),
            "updated_at": scan["updated_at"],
        }
    }


@app.post("/api/discover/scan")
def save_discover_scan(req: DiscoverScanRequest, user: dict = Depends(auth.require_user)):
    store.save_discover_scan(user["id"], req.focus, req.log, json.dumps(req.ideas))
    return {"ok": True}


@app.delete("/api/discover/scan")
def clear_discover_scan(user: dict = Depends(auth.require_user)):
    store.clear_discover_scan(user["id"])
    return {"ok": True}


# ---------------------------------------------------------------------------
# Opportunity discovery (SSE)
# ---------------------------------------------------------------------------
class DiscoverRequest(BaseModel):
    focus: str = ""


@app.post("/api/discover")
def discover(req: DiscoverRequest):
    focus = req.focus.strip()
    if len(focus) > 300:
        raise HTTPException(status_code=400, detail="Focus must be under 300 characters.")
    status = agents.team_status()
    if not status["ready"]:
        raise HTTPException(status_code=503, detail="Thrace is not ready.")

    def worker(q: queue.Queue):
        try:
            for event in agents.run_discovery(focus):
                q.put(event)
        except Exception as exc:  # noqa: BLE001
            q.put({"type": "error", "message": str(exc)})

    return _sse_stream(worker)


# ---------------------------------------------------------------------------
# Report Q&A (SSE)
# ---------------------------------------------------------------------------
class AskRequest(BaseModel):
    content: str
    question: str
    subject: str = ""


@app.post("/api/ask")
def ask(req: AskRequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="A question is required.")
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="No report content to query.")
    status = agents.team_status()
    if not status["ready"]:
        raise HTTPException(status_code=503, detail="Thrace is not ready.")

    def worker(q: queue.Queue):
        try:
            for event in agents.answer_question(req.content, question, req.subject):
                q.put(event)
        except Exception as exc:  # noqa: BLE001
            q.put({"type": "error", "message": str(exc)})

    return _sse_stream(worker)


# ---------------------------------------------------------------------------
# Frontend static hosting (production single-service deployment)
# ---------------------------------------------------------------------------
from fastapi.staticfiles import StaticFiles  # noqa: E402

if os.path.isdir(_FRONTEND_DIST):
    # Assets with hashed filenames — cache hard.
    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(_FRONTEND_DIST, "assets")),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """Serve the SPA: real files directly, everything else -> index.html."""
        candidate = os.path.normpath(os.path.join(_FRONTEND_DIST, full_path))
        if (
            full_path
            and candidate.startswith(_FRONTEND_DIST)
            and os.path.isfile(candidate)
        ):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_FRONTEND_DIST, "index.html"))
