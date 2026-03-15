"""Authentication module — API key and session cookie auth."""

import hashlib
import hmac

from fastapi import Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from .config import settings


def _sign_key(key: str) -> str:
    """Sign an API key for cookie storage."""
    return hmac.new(
        settings.auth_cookie_secret.encode(), key.encode(), hashlib.sha256
    ).hexdigest()


def verify_key(key: str) -> bool:
    """Check if the key is in the configured auth keys."""
    return key in settings.auth_keys


def get_current_user(request: Request) -> str | None:
    """Extract authenticated user identifier. Returns None when auth is disabled."""
    if not settings.auth_keys:
        return None

    # Check API header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        key = auth_header[7:]
        if verify_key(key):
            return key[:8]

    # Check session cookie
    cookie = request.cookies.get(settings.auth_cookie_name, "")
    if cookie:
        for key in settings.auth_keys:
            if _sign_key(key) == cookie:
                return key[:8]

    return None


async def require_auth(request: Request):
    """FastAPI dependency that enforces authentication when auth keys are configured."""
    if not settings.auth_keys:
        return  # Auth disabled

    # Check API header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        key = auth_header[7:]
        if verify_key(key):
            return
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Check session cookie
    cookie = request.cookies.get(settings.auth_cookie_name, "")
    if cookie:
        for key in settings.auth_keys:
            if _sign_key(key) == cookie:
                return

    # Determine if API or UI request
    if request.url.path.startswith("/api/"):
        raise HTTPException(status_code=401, detail="Authentication required")

    # UI request — redirect to login
    raise HTTPException(
        status_code=303,
        headers={"Location": "/login"},
        detail="Redirect to login",
    )
