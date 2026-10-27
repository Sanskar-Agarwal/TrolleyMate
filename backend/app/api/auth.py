"""Sign-in and shopper sign-up. Owner: Platform & Governance."""

import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import user_out
from app.core.db import get_db
from app.core.deps import current_user
from app.core.security import create_token, hash_password, verify_password
from app.domain import Household, HouseholdMember, User
from app.domain.enums import UserRole

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


class RegisterIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    email: str = Field(max_length=200)
    password: str = Field(min_length=8, max_length=200)
    household_name: str | None = Field(default=None, max_length=120)


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, db: Session = Depends(get_db)) -> dict:
    """Create a shopper account with a one-person household (1.2.13). Reviewer and founder
    accounts are never self-assigned; they're provisioned by the company."""
    email = body.email.strip().lower()
    name = body.display_name.strip()
    if not _EMAIL.match(email):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Enter a valid email address.")
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Enter your name.")
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with that email already exists. Sign in instead.")
    user = User(email=email, display_name=name, role=UserRole.shopper, password_hash=hash_password(body.password))
    household = Household(name=(body.household_name or "").strip() or f"{name.split()[0]}'s household", shopper=user)
    household.add_member(HouseholdMember(name=name.split()[0], age_group="adult"))
    db.add(user)
    db.commit()
    return {"token": create_token(user.id, user.role), "user": user_out(user)}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return user_out(user)


@router.get("/demo-accounts")
def demo_accounts(db: Session = Depends(get_db)) -> list[dict]:
    """Lets the sign-in page offer one-click demo logins (prototype only)."""
    users = db.scalars(select(User).where(User.email.like("%@trolleymate.demo")).order_by(User.id))
    return [{"email": u.email, "display_name": u.display_name, "role": u.role} for u in users]
