"""Shared database and server-owned role dependencies."""

from typing import Annotated
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db
from .models import User
from .services import token_hash

DB = Annotated[Session, Depends(get_db)]


def current_user(db: DB, authorization: Annotated[str | None, Header()] = None) -> User:
    """Resolve server-owned roles from bearer credentials, never caller role claims."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Sign in with a demo account")
    token = authorization[7:]
    if token.startswith("demo-") and (not settings.demo_auth or settings.app_env == "production"):
        raise HTTPException(401, "Demo accounts are disabled")
    user = db.scalar(select(User).where(User.token_hash == token_hash(token)))
    if not user:
        raise HTTPException(401, "Invalid session")
    return user


Principal = Annotated[User, Depends(current_user)]


def coordinator(user: Principal) -> User:
    """Enforce coordinator permissions at every operational API boundary."""
    if user.role != "coordinator":
        raise HTTPException(403, "Coordinator access required")
    return user


Coordinator = Annotated[User, Depends(coordinator)]
