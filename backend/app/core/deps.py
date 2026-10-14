"""FastAPI dependencies: current user, role checks, and the per-request AgentContext."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.agents.context import AgentContext
from app.core.db import get_db
from app.core.security import decode_token
from app.domain import User
from app.llm import get_llm

_bearer = HTTPBearer(auto_error=False)


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)
) -> User:
    payload = decode_token(creds.credentials) if creds else None
    user = db.get(User, payload["sub"]) if payload else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    return user


def require_role(*roles: str) -> Callable[[User], User]:
    def check(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"This needs a {' or '.join(roles)} account.")
        return user

    return check


def agent_context(db: Session = Depends(get_db), user: User = Depends(current_user)) -> AgentContext:
    return AgentContext(db=db, llm=get_llm(), user=user)
