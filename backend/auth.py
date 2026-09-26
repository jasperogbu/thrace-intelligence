"""Authentication for Thrace: bcrypt password hashing + JWT session tokens
+ Google OAuth 2.0 sign-in + password reset by emailed link.

Sessions are stateless JWTs signed with AUTH_SECRET (from .env; a dev default
is used when unset). The token is sent by the client as a Bearer header and
resolved by the `resolve_user` FastAPI dependency.

Password reset uses a single-use, time-limited token. Only its SHA-256 digest
is stored, so the database never holds a usable reset link. Delivery is over
SMTP when SMTP_HOST is configured; otherwise the link is returned in the API
response so the flow remains testable without a mail server. See `send_reset_email`.
"""
import hashlib
import logging
import os
import secrets
import smtplib
import time
from email.message import EmailMessage
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import store

AUTH_SECRET = os.getenv("AUTH_SECRET", "thrace-dev-secret-change-me")
TOKEN_TTL_HOURS = 24 * 14  # 2 weeks
_bearer = HTTPBearer(auto_error=False)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

# Frontend origin — the OAuth popup posts a message back to this origin.
# In production (Render) the app is served from the same origin as the API,
# so RENDER_EXTERNAL_URL wins; locally it defaults to the Vite dev server.
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "") or os.getenv(
    "RENDER_EXTERNAL_URL", "http://localhost:5173"
)

# Anti-forgery state per browser (single-slot; this app has one user per browser)
_oauth_state: str | None = None

_MIN_PASSWORD_LEN = 8


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _make_token(user_id: str) -> str:
    now = int(time.time())
    payload = {"sub": user_id, "iat": now, "exp": now + TOKEN_TTL_HOURS * 3600}
    return jwt.encode(payload, AUTH_SECRET, algorithm="HS256")


def register(email: str, name: str, password: str) -> dict:
    email = email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if len(password) < _MIN_PASSWORD_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {_MIN_PASSWORD_LEN} characters.",
        )
    if store.get_user_by_email(email):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    user = store.create_user(email, name.strip() or email.split("@")[0], hash_password(password))
    return {"user": user, "token": _make_token(user["id"])}


def login(email: str, password: str) -> dict:
    email = email.strip().lower()
    row = store.get_user_by_email(email)
    if not row or not verify_password(password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    user = {"id": row["id"], "email": row["email"], "name": row["name"]}
    return {"user": user, "token": _make_token(user["id"])}


def user_from_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, AUTH_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    user = store.get_user(payload.get("sub", ""))
    if not user:
        return None
    return {"id": user["id"], "email": user["email"], "name": user["name"]}


def resolve_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[dict]:
    """FastAPI dependency: the signed-in user, or None (anonymous)."""
    if credentials is None:
        return None
    return user_from_token(credentials.credentials)


def require_user(user: Optional[dict] = Depends(resolve_user)) -> dict:
    """FastAPI dependency: the signed-in user; 401 when anonymous."""
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to use this feature.")
    return user


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------
# 1 hour is long enough to find the email and short enough to limit the window
# in which a link sitting in an inbox is usable.
RESET_TTL_SECONDS = int(os.getenv("RESET_TOKEN_TTL_SECONDS", "3600"))
# Throttle: one request per address per 60s. Keyed on the address so it also
# covers unknown addresses without revealing whether they exist.
RESET_THROTTLE_SECONDS = int(os.getenv("RESET_THROTTLE_SECONDS", "60"))

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "") or SMTP_USER

# Deliberately identical whether or not the address exists, so the endpoint
# cannot be used to discover which emails have accounts.
_RESET_GENERIC_MSG = (
    "If that email has a Thrace account, a reset link is on its way."
)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _reset_link(token: str) -> str:
    """The user-facing reset URL, pointed at the frontend."""
    return f"{FRONTEND_ORIGIN.rstrip('/')}/auth?reset_token={token}"


def smtp_configured() -> bool:
    return bool(SMTP_HOST and SMTP_FROM)


def send_reset_email(to_email: str, token: str) -> bool:
    """Send the reset link over SMTP. Returns True if it was actually sent.

    Delivery failure is never surfaced to the caller as an error: the user gets
    the same generic confirmation either way, which both avoids leaking whether
    an account exists and stops a mail outage from blocking the flow.
    """
    if not smtp_configured():
        return False
    link = _reset_link(token)
    msg = EmailMessage()
    msg["Subject"] = "Reset your Thrace password"
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg.set_content(
        "Someone requested a password reset for your Thrace account.\n\n"
        f"Open this link within {RESET_TTL_SECONDS // 60} minutes to choose a "
        f"new password:\n\n{link}\n\n"
        "If you did not request this, you can ignore this email — your current "
        "password still works."
    )
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001
        logging.warning("[thrace] password reset email failed: %s", str(exc)[:200])
        return False


def request_password_reset(email: str) -> dict:
    """Start a password reset for `email`.

    Always returns the same generic message. Returns `dev_token` only when no
    SMTP server is configured, so the flow is usable without mail; that field
    is absent whenever real delivery is available.
    """
    email = email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")

    if store.password_reset_requested_recently(
        email, time.time() - RESET_THROTTLE_SECONDS
    ):
        # Throttled. Still generic, still no token.
        return {"message": _RESET_GENERIC_MSG}

    user = store.get_user_by_email(email)
    if not user:
        # Unknown address: do nothing, and reveal nothing.
        return {"message": _RESET_GENERIC_MSG}

    token = secrets.token_urlsafe(32)
    store.create_password_reset(
        user_id=user["id"],
        token_hash=_hash_token(token),
        expires_at=time.time() + RESET_TTL_SECONDS,
        created_at=time.time(),
    )
    sent = send_reset_email(email, token)
    result: dict = {"message": _RESET_GENERIC_MSG}
    if not smtp_configured():
        # Dev fallback: hand the link back so the feature is demonstrable
        # without a mail server. Never returned when SMTP is configured.
        result["dev_token"] = token
    elif not sent:
        result["delivered"] = False
    return result


def reset_password(token: str, new_password: str) -> dict:
    """Complete a reset: validate the token and set a new password."""
    token = (token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="This reset link is not valid.")
    if len(new_password) < _MIN_PASSWORD_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {_MIN_PASSWORD_LEN} characters.",
        )

    row = store.get_password_reset(_hash_token(token))
    if not row:
        # Covers unknown, expired and already-used tokens identically.
        raise HTTPException(
            status_code=400,
            detail="This reset link has expired or has already been used. "
            "Request a new one.",
        )

    # Single-use: consume before hashing so a failure mid-way cannot leave a
    # live token behind.
    store.consume_password_reset(_hash_token(token))
    store.update_user_password(row["user_id"], hash_password(new_password))
    return {"message": "Your password has been reset. You can sign in now."}


# ---------------------------------------------------------------------------
# Google OAuth 2.0
# ---------------------------------------------------------------------------
def google_configured() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def new_oauth_state() -> str:
    """Refresh and return the CSRF state for the next auth round-trip."""
    global _oauth_state
    _oauth_state = secrets.token_urlsafe(32)
    return _oauth_state


def check_oauth_state(state: str | None) -> bool:
    global _oauth_state
    ok = bool(_oauth_state and state and secrets.compare_digest(state, _oauth_state))
    _oauth_state = None  # single use
    return ok


def exchange_google_code(code: str, redirect_uri: str) -> dict:
    """Exchange the OAuth code for an access token, then fetch the profile."""
    import httpx

    with httpx.Client(timeout=15) as client:
        token_resp = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Google sign-in failed at token exchange.")
        access_token = token_resp.json().get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="Google sign-in returned no access token.")

        user_resp = client.get(
            GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
        )
        if user_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Could not read the Google profile.")
        google_user = user_resp.json()

    if not google_user.get("verified_email", True):
        raise HTTPException(status_code=400, detail="Google account email is not verified.")
    return google_user


def _upsert_google_user(google_user: dict) -> dict:
    """Create or update the local user record from a Google profile."""
    email = (google_user.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Google account has no email.")
    existing = store.get_user_by_email(email)
    if existing:
        if not existing.get("name") and google_user.get("name"):
            store.update_user_name(existing["id"], google_user["name"])
        return {"id": existing["id"], "email": existing["email"], "name": existing["name"] or google_user.get("name", "")}
    created = store.create_user(
        email,
        google_user.get("name") or email.split("@")[0],
        password_hash="!",  # OAuth accounts have no password
    )
    return created
