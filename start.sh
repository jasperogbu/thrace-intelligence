#!/usr/bin/env bash
# Thrace - one-command launcher
# Starts the FastAPI backend + React frontend, then opens the app in your browser.

set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
URL="http://localhost:${FRONTEND_PORT}"

PYTHON_BIN="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  echo "ERROR: virtual environment not found at $ROOT/.venv"
  echo "Run:  python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt"
  exit 1
fi

if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "ERROR: frontend dependencies not installed."
  echo "Run:  (cd $ROOT/frontend && npm install)"
  exit 1
fi

echo ">> Starting Thrace backend  (http://localhost:${BACKEND_PORT})"
nohup "$PYTHON_BIN" -m uvicorn main:app --host 0.0.0.0 --port "$BACKEND_PORT" \
  --app-dir "$ROOT/backend" > /tmp/thrace_backend.log 2>&1 &

echo ">> Starting Thrace frontend (http://localhost:${FRONTEND_PORT})"
nohup npm run dev --prefix "$ROOT/frontend" > /tmp/thrace_frontend.log 2>&1 &

echo ">> Waiting for services to come up..."

for i in $(seq 1 30); do
  if curl -sf "http://localhost:${BACKEND_PORT}/api/health" >/dev/null 2>&1; then
    echo "   backend  OK"
    break
  fi
  [ "$i" -eq 30 ] && echo "   backend  did not start in time (see /tmp/thrace_backend.log)"
  sleep 1
done

for i in $(seq 1 30); do
  if curl -sf -o /dev/null "http://localhost:${FRONTEND_PORT}/" 2>&1; then
    echo "   frontend OK"
    break
  fi
  [ "$i" -eq 30 ] && echo "   frontend did not start in time (see /tmp/thrace_frontend.log)"
  sleep 1
done

echo ">> Opening $URL"
open "$URL" 2>/dev/null || true

echo ""
echo "Thrace is running."
echo "  Frontend: $URL"
echo "  Backend:  http://localhost:${BACKEND_PORT}/api/health"
echo "  Stop:     $ROOT/stop.sh"
