"""SQLite persistence for Thrace runs, chat exchanges and the watchlist.

Two backends:
- Local SQLite (development) at backend/data/thrace.db
- Turso (production, durable across Render restarts/redeploys) when
  TURSO_DATABASE_URL + TURSO_AUTH_TOKEN are set. Turso is SQLite wire-
  compatible but its Python driver lacks row_factory and the context-manager
  protocol, so _connect() normalises both behind the same interface.
"""
import os
import sqlite3
import threading
import time
import uuid

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "thrace.db")
TURSO_URL = os.getenv("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")
USE_TURSO = bool(TURSO_URL and TURSO_TOKEN)

_lock = threading.Lock()


def _connect():
    """Open a connection with a uniform interface across backends."""
    if USE_TURSO:
        import libsql_experimental as libsql

        raw = libsql.connect(TURSO_URL, auth_token=TURSO_TOKEN)
    else:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        raw = sqlite3.connect(DB_PATH, timeout=30)
        raw.row_factory = sqlite3.Row
    return _Conn(raw)


class _Conn:
    """Wrapper giving both drivers sqlite3-compatible behaviour."""

    def __init__(self, raw):
        self._raw = raw
        self.row_factory = None  # interface parity only

    def execute(self, sql, params=()):
        return self._raw.execute(sql, params)

    def executescript(self, sql):
        return self._raw.executescript(sql)

    def commit(self):
        return self._raw.commit()

    def rollback(self):
        return self._raw.rollback()

    def close(self):
        return self._raw.close()

    def __enter__(self):
        self._raw.execute("BEGIN")
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._raw.commit()
        else:
            self._raw.rollback()
        self._raw.close()
        return False


def _rows_to_dicts(cursor) -> list[dict]:
    """Materialise cursor rows as dicts (handles Row/tuple shapes)."""
    out = []
    cols = None
    for row in cursor.fetchall():
        if cols is None:
            try:
                cols = [d[0] for d in cursor.description]
            except (TypeError, IndexError):
                cols = [f"c{i}" for i in range(len(row))]
        out.append(dict(zip(cols, row)))
    return out


def _one_to_dict(cursor) -> dict | None:
    row = cursor.fetchone()
    if row is None:
        return None
    try:
        cols = [d[0] for d in cursor.description]
    except (TypeError, IndexError):
        cols = [f"c{i}" for i in range(len(row))]
    return dict(zip(cols, row))


def _conn():
    """Context manager yielding a uniform connection (commit on success)."""
    return _ConnCtx()


class _ConnCtx:
    def __enter__(self):
        self._c = _connect()
        return self._c

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self._c.commit()
            else:
                self._c.rollback()
        finally:
            self._c.close()
        return False


# Backwards-compatible alias used before the refactor — keep call sites
# simple: every helper below uses `with _lock, _conn() as c:` and calls
# c.execute(...) / _rows_to_dicts(...) / _one_to_dict(...).
_conn_ctx = _conn


def init_db() -> None:
    with _lock, _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                mode TEXT NOT NULL,
                pinned INTEGER DEFAULT 0,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS exchanges (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                idx INTEGER NOT NULL,
                kind TEXT NOT NULL DEFAULT 'user',
                query TEXT,
                mode TEXT,
                content TEXT DEFAULT '',
                status TEXT DEFAULT 'done',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_exchanges_run ON exchanges(run_id);
            CREATE TABLE IF NOT EXISTS watchlist (
                run_id TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                mode TEXT NOT NULL,
                interval_hours REAL DEFAULT 168,
                last_run REAL DEFAULT 0,
                active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS discover_scans (
                user_id TEXT PRIMARY KEY,
                focus TEXT DEFAULT '',
                log TEXT DEFAULT '',
                ideas TEXT DEFAULT '[]',
                updated_at REAL NOT NULL
            );
            """
        )


def _migrate() -> None:
    """Lightweight column migrations for pre-existing databases."""
    with _lock, _conn() as c:
        cols = {r["name"] for r in _rows_to_dicts(c.execute("PRAGMA table_info(runs)"))}
        if "user_id" not in cols:
            c.execute("ALTER TABLE runs ADD COLUMN user_id TEXT")
        c.execute("CREATE INDEX IF NOT EXISTS idx_runs_user ON runs(user_id)")
        cols = {r["name"] for r in _rows_to_dicts(c.execute("PRAGMA table_info(watchlist)"))}
        if "user_id" not in cols:
            c.execute("ALTER TABLE watchlist ADD COLUMN user_id TEXT")
        c.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id)")


init_db()
_migrate()


def _exchange_row(ex: dict) -> tuple:
    return (
        ex.get("id") or str(uuid.uuid4()),
        ex["run_id"],
        int(ex.get("idx", 0)),
        ex.get("kind", "user"),
        ex.get("query", ""),
        ex.get("mode", "venture"),
        ex.get("content", ""),
        ex.get("status", "done"),
        float(ex.get("created_at", time.time())),
    )


def upsert_run(run: dict) -> None:
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO runs (id, user_id, query, mode, pinned, created_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET query=excluded.query, pinned=excluded.pinned, "
            "user_id=COALESCE(excluded.user_id, runs.user_id)",
            (
                run["id"],
                run.get("user_id"),
                run.get("query", ""),
                run.get("mode", "venture"),
                1 if run.get("pinned") else 0,
                float(run.get("created_at", time.time())),
            ),
        )


def upsert_exchange(ex: dict) -> None:
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO exchanges (id, run_id, idx, kind, query, mode, content, status, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "content=excluded.content, status=excluded.status",
            _exchange_row(ex),
        )


def get_run(run_id: str, user_id: str | None = None) -> dict | None:
    with _lock, _conn() as c:
        row = _one_to_dict(c.execute(
            "SELECT * FROM runs WHERE id=? AND (user_id IS ? OR user_id IS NULL)",
            (run_id, user_id),
        ))
        return dict(row) if row else None


def get_exchanges(run_id: str) -> list[dict]:
    with _lock, _conn() as c:
        rows = _rows_to_dicts(c.execute(
            "SELECT * FROM exchanges WHERE run_id=? ORDER BY idx, created_at",
            (run_id,),
        ))
        return [dict(r) for r in rows]


def list_runs(user_id: str | None = None, limit: int = 200) -> list[dict]:
    with _lock, _conn() as c:
        rows = _rows_to_dicts(c.execute(
            "SELECT * FROM runs WHERE user_id IS ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ))
        return [dict(r) for r in rows]


def list_chats(user_id: str | None) -> list[dict]:
    """Full chats (run + exchanges) for a user, newest first."""
    chats: list[dict] = []
    for run in list_runs(user_id):
        exchanges = get_exchanges(run["id"])
        if not exchanges:
            continue
        chats.append({**run, "exchanges": exchanges})
    return chats


def set_run_pin(run_id: str, pinned: bool, user_id: str) -> None:
    """Update a chat's pinned flag (scoped to the owner)."""
    with _lock, _conn() as c:
        row = _one_to_dict(c.execute(
            "SELECT id FROM runs WHERE id=? AND user_id=?", (run_id, user_id)
        ))
        if row is None:
            # chat not synced yet — ensure the row exists so the pin sticks
            c.execute(
                "INSERT INTO runs (id, user_id, query, mode, pinned, created_at) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET pinned=excluded.pinned",
                (run_id, user_id, "", "venture", 1 if pinned else 0, time.time()),
            )
        else:
            c.execute(
                "UPDATE runs SET pinned=? WHERE id=? AND user_id=?",
                (1 if pinned else 0, run_id, user_id),
            )


def delete_run(run_id: str, user_id: str | None = None) -> None:
    with _lock, _conn() as c:
        c.execute(
            "DELETE FROM exchanges WHERE run_id=?", (run_id,)
        )
        c.execute(
            "DELETE FROM watchlist WHERE run_id=?", (run_id,)
        )
        c.execute(
            "DELETE FROM runs WHERE id=? AND (user_id IS ? OR user_id IS NULL)",
            (run_id, user_id),
        )


def server_updates_since(since: float, user_id: str | None = None) -> list[dict]:
    """Server-originated exchanges (monitor/digest) newer than `since`.

    Returns the minimal shape the frontend needs to merge autonomous updates
    into its local chats: run info plus the new exchanges. Digests are global
    (user_id NULL); monitor updates are per-user.
    """
    with _lock, _conn() as c:
        rows = _rows_to_dicts(c.execute(
            "SELECT e.* FROM exchanges e JOIN runs r ON e.run_id = r.id "
            "WHERE e.created_at > ? AND e.kind != 'user' "
            "AND (r.user_id IS ? OR r.user_id IS NULL) "
            "ORDER BY e.created_at",
            (since, user_id),
        ))
        if not rows:
            return []
        out: dict[str, dict] = {}
        for r in rows:
            ex = dict(r)
            rid = ex["run_id"]
            if rid not in out:
                run = _one_to_dict(c.execute("SELECT * FROM runs WHERE id=?", (rid,)))
                out[rid] = {
                    "id": rid,
                    "query": run["query"] if run else ex.get("query", "Thrace update"),
                    "mode": (run["mode"] if run else ex.get("mode", "monitor")),
                    "created_at": run["created_at"] if run else ex["created_at"],
                    "exchanges": [],
                }
            out[rid]["exchanges"].append(ex)
        return list(out.values())


def add_watch(
    run_id: str,
    query: str,
    mode: str,
    interval_hours: float | None = None,
    user_id: str | None = None,
) -> None:
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO watchlist (run_id, user_id, query, mode, interval_hours, last_run, active) "
            "VALUES (?,?,?,?,?,?,1) ON CONFLICT(run_id) DO UPDATE SET "
            "query=excluded.query, mode=excluded.mode, active=1",
            (
                run_id,
                user_id,
                query,
                mode,
                interval_hours if interval_hours is not None else _default_interval(),
                time.time(),
            ),
        )


def remove_watch(run_id: str, user_id: str | None = None) -> None:
    with _lock, _conn() as c:
        c.execute(
            "DELETE FROM watchlist WHERE run_id=? AND (user_id IS ? OR user_id IS NULL)",
            (run_id, user_id),
        )


def list_watch(user_id: str | None = None) -> list[dict]:
    with _lock, _conn() as c:
        rows = _rows_to_dicts(c.execute(
            "SELECT * FROM watchlist WHERE active=1 AND (user_id IS ? OR user_id IS NULL)",
            (user_id,),
        ))
        return [dict(r) for r in rows]


def due_watches(now: float) -> list[dict]:
    with _lock, _conn() as c:
        rows = _rows_to_dicts(c.execute(
            "SELECT * FROM watchlist WHERE active=1 AND "
            "last_run + interval_hours * 3600 <= ?",
            (now,),
        ))
        return [dict(r) for r in rows]


def set_watch_checked(run_id: str, ts: float | None = None) -> None:
    with _lock, _conn() as c:
        c.execute(
            "UPDATE watchlist SET last_run=? WHERE run_id=?",
            (ts or time.time(), run_id),
        )


def last_report_for_run(run_id: str) -> str | None:
    """Latest report content in a run (user or autonomous)."""
    with _lock, _conn() as c:
        row = _one_to_dict(c.execute(
            "SELECT content FROM exchanges WHERE run_id=? AND content != '' "
            "ORDER BY idx DESC, created_at DESC LIMIT 1",
            (run_id,),
        ))
        return row["content"] if row else None


def next_exchange_idx(run_id: str) -> int:
    with _lock, _conn() as c:
        row = _one_to_dict(c.execute(
            "SELECT COALESCE(MAX(idx), -1) + 1 AS nxt FROM exchanges WHERE run_id=?",
            (run_id,),
        ))
        return int(row["nxt"] if row else 0)


def get_meta(key: str) -> str | None:
    with _lock, _conn() as c:
        row = _one_to_dict(c.execute("SELECT value FROM meta WHERE key=?", (key,)))
        return row["value"] if row else None


def set_meta(key: str, value: str) -> None:
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO meta (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
def create_user(email: str, name: str, password_hash: str) -> dict:
    user_id = str(uuid.uuid4())
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO users (id, email, name, password_hash, created_at) VALUES (?,?,?,?,?)",
            (user_id, email, name, password_hash, time.time()),
        )
    return {"id": user_id, "email": email, "name": name}


def get_user_by_email(email: str) -> dict | None:
    with _lock, _conn() as c:
        row = _one_to_dict(c.execute("SELECT * FROM users WHERE email=?", (email,)))
        return dict(row) if row else None


def get_user(user_id: str) -> dict | None:
    with _lock, _conn() as c:
        row = _one_to_dict(c.execute("SELECT * FROM users WHERE id=?", (user_id,)))
        return dict(row) if row else None


def update_user_name(user_id: str, name: str) -> None:
    with _lock, _conn() as c:
        c.execute("UPDATE users SET name=? WHERE id=?", (name, user_id))


# ---------------------------------------------------------------------------
# Discover scans (one persisted scan per user, survives logout/login)
# ---------------------------------------------------------------------------
def get_discover_scan(user_id: str) -> dict | None:
    with _lock, _conn() as c:
        row = _one_to_dict(c.execute(
            "SELECT * FROM discover_scans WHERE user_id=?", (user_id,)
        ))
        return dict(row) if row else None


def save_discover_scan(user_id: str, focus: str, log: str, ideas_json: str) -> None:
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO discover_scans (user_id, focus, log, ideas, updated_at) "
            "VALUES (?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
            "focus=excluded.focus, log=excluded.log, ideas=excluded.ideas, "
            "updated_at=excluded.updated_at",
            (user_id, focus, log, ideas_json, time.time()),
        )


def clear_discover_scan(user_id: str) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM discover_scans WHERE user_id=?", (user_id,))


def _default_interval() -> float:
    return float(os.getenv("REVAL_INTERVAL_HOURS", "168"))
