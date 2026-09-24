#!/usr/bin/env bash
# Thrace - stop the backend + frontend servers.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ">> Stopping Thrace servers..."

pkill -f "uvicorn main:app" 2>/dev/null && echo "   backend stopped" || echo "   backend not running"
pkill -f "vite" 2>/dev/null && echo "   frontend stopped" || echo "   frontend not running"

echo "Done."
