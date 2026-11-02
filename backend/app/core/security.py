"""Salted, versioned password hashes and revocable opaque login sessions."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.authentication import LoginSession
from app.domain.household_profiles import User

_ITERATIONS = 600_000
_LEGACY_ITERATIONS = 120_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS).hex()
    return f"pbkdf2_sha256${_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        parts = stored.split("$")
        if len(parts) == 3 and parts[0] == "pbkdf2":
            _, salt, digest = parts
            iterations = _LEGACY_ITERATIONS
        elif len(parts) == 4 and parts[0] == "pbkdf2_sha256":
            _, count, salt, digest = parts
            iterations = int(count)
            if not 1 <= iterations <= 2_000_000:
                return False
        else:
            return False
        if len(salt) != 32 or len(digest) != 64:
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
        return hmac.compare_digest(candidate, digest)
    except (TypeError, ValueError):
        return False


def password_needs_upgrade(stored: str) -> bool:
    return not stored.startswith(f"pbkdf2_sha256${_ITERATIONS}$")


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User) -> str:
    settings, now = get_settings(), time.time()
    # Serialize concurrent logins for this account before enforcing the cap.
    # SQLite takes a write lock; row-locking databases lock this user's row.
    db.execute(update(User).where(User.id == user.id).values(id=User.id))
    db.execute(delete(LoginSession).where(
        (LoginSession.expires_at <= now) |
        (LoginSession.last_seen <= now - settings.session_idle_minutes * 60)
    ))
    sessions = list(db.scalars(select(LoginSession).where(LoginSession.user_id == user.id)
                               .order_by(LoginSession.created_at, LoginSession.token_hash)))
    for old in sessions[:max(0, len(sessions) - settings.max_active_sessions + 1)]:
        db.delete(old)
    token = secrets.token_urlsafe(32)
    db.add(LoginSession(token_hash=token_digest(token), user_id=user.id, created_at=now,
                        last_seen=now, expires_at=now + settings.token_ttl_hours * 3600))
    db.commit()
    return token


def resolve_session(db: Session, token: str) -> LoginSession | None:
    if not 40 <= len(token) <= 100:
        return None
    now = time.time()
    key = token_digest(token)
    existing = db.get(LoginSession, key)
    if existing is None or existing.expires_at <= now or existing.last_seen <= now - get_settings().session_idle_minutes * 60:
        return None
    # Coalesce activity writes to once a minute; frequent status/cancel requests
    # must not wait for a long-running shopping transaction's SQLite write lock.
    if now - existing.last_seen < 60:
        return existing
    # Atomic expiry check/touch: a concurrent logout cannot resurrect a session.
    result = db.execute(update(LoginSession).where(
        LoginSession.token_hash == key, LoginSession.expires_at > now,
        LoginSession.last_seen > now - get_settings().session_idle_minutes * 60,
    ).values(last_seen=now))
    db.commit()
    return db.get(LoginSession, key) if result.rowcount else None
