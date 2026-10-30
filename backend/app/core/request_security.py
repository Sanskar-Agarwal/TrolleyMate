"""CSRF checks and database-backed request throttles for the SQLite deployment."""
import hashlib
import hmac
import math
import time
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from sqlalchemy import case, create_engine, delete
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import sessionmaker
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import get_settings
from app.core.db import engine
from app.domain.authentication import RateLimitWindow

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
# A separate shared SQLite file prevents an in-flight basket transaction from
# blocking cancellation/status requests merely to update a rate counter.
_limit_url = engine.url.set(database=f"{engine.url.database}.limits")
limit_engine = create_engine(_limit_url, connect_args={"check_same_thread": False, "timeout": 10})
LimitSession = sessionmaker(bind=limit_engine)


def init_limits() -> None:
    RateLimitWindow.__table__.create(limit_engine, checkfirst=True)


def reset_limits() -> None:
    init_limits()
    with LimitSession() as db:
        db.execute(delete(RateLimitWindow))
        db.commit()


def enforce_limit(bucket: str, identity: str, limit: int, seconds: int) -> None:
    now = time.time()
    key = hmac.new(get_settings().secret_key.encode(), f"{bucket}:{identity}".encode(), hashlib.sha256).hexdigest()
    with LimitSession() as db:
        db.execute(delete(RateLimitWindow).where(RateLimitWindow.expires_at <= now))
        statement = insert(RateLimitWindow).values(key=key, count=1, expires_at=now + seconds)
        statement = statement.on_conflict_do_update(index_elements=[RateLimitWindow.key], set_={
            "count": case((RateLimitWindow.expires_at <= now, 1), else_=RateLimitWindow.count + 1),
            "expires_at": case((RateLimitWindow.expires_at <= now, now + seconds), else_=RateLimitWindow.expires_at),
        }).returning(RateLimitWindow.count, RateLimitWindow.expires_at)
        count, expires = db.execute(statement).one()
        db.commit()
    if count > limit:
        wait = max(1, math.ceil(expires - now))
        raise HTTPException(429, f"Too many requests. Try again in {wait} seconds.", headers={"Retry-After": str(wait)})


def check_request(request: Request) -> None:
    settings = get_settings()
    if request.method in UNSAFE:
        # No cookie authentication is accepted. The custom header also protects
        # unauthenticated login/register from cross-origin HTML form submissions.
        if request.headers.get("x-trolleymate-request") != "1":
            raise HTTPException(403, "Request verification failed. Refresh the app and try again.")
        origin = request.headers.get("origin")
        if not origin and request.headers.get("referer"):
            ref = urlsplit(request.headers["referer"])
            origin = f"{ref.scheme}://{ref.netloc}"
        allowed = {f"{request.url.scheme}://{request.url.netloc}", *settings.cors_origin_list}
        if origin is not None and origin not in allowed:
            raise HTTPException(403, "Cross-origin request rejected.")
        if request.headers.get("sec-fetch-site") == "cross-site" and origin not in settings.cors_origin_list:
            raise HTTPException(403, "Cross-site request rejected.")
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type and content_type != "application/json":
            raise HTTPException(415, "API writes require application/json.")
    # Trust only the ASGI client address. Proxy forwarding is configured at the
    # server boundary, never taken directly from arbitrary X-Forwarded-For input.
    ip = request.client.host if request.client else "unknown"
    enforce_limit("api-ip", ip, settings.api_requests_per_minute, 60)
    if request.url.path in {"/api/auth/login", "/api/auth/register"} and request.method == "POST":
        enforce_limit("auth-ip", ip, settings.auth_attempts_per_minute, 60)
    if request.url.path == "/api/auth/register" and request.method == "POST":
        enforce_limit("register-ip", ip, settings.registrations_per_hour, 3600)


class RequestSecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path.startswith("/api/") and request.method != "OPTIONS":
            if request.url.path != "/api/health":
                try:
                    await run_in_threadpool(check_request, request)
                except HTTPException as exc:
                    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code,
                                        headers={"Cache-Control": "no-store", **(exc.headers or {})})
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
        return await call_next(request)
