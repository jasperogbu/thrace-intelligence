"""Authentication for Thrace: bcrypt password hashing + JWT session tokens
+ Google OAuth 2.0 sign-in.

Sessions are stateless JWTs signed with AUTH_SECRET (from .env; a dev default
is used when unset). The token is sent by the client as a Bearer header and
resolved by the `current_user` FastAPI dependency.
"""
import os
import secrets
import time
from typing import Optional
from urllib.parse import urlencode

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.responses import RedirectResponse
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
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")

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
