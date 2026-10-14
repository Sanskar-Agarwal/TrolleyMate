"""Sign-in. Owner: Platform & Governance."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import user_out
from app.core.db import get_db
from app.core.deps import current_user
from app.core.security import create_token, verify_password
from app.domain import User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect.")
    return {"token": create_token(user.id, user.role), "user": user_out(user)}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return user_out(user)


@router.get("/demo-accounts")
def demo_accounts(db: Session = Depends(get_db)) -> list[dict]:
    """Lets the sign-in page offer one-click demo logins (prototype only)."""
    users = db.scalars(select(User).where(User.email.like("%@trolleymate.demo")).order_by(User.id))
    return [{"email": u.email, "display_name": u.display_name, "role": u.role} for u in users]
