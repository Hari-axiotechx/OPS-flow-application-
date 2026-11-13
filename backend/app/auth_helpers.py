import re
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from .models import User
from .security import verify_token
from .errors import ApiError

ROLES = ["Developer", "QA", "DevOps"]


@dataclass
class Ctx:
    email: Optional[str]
    user: Optional[User]


def authenticate(db: Session, token: Optional[str]) -> Ctx:
    if not token:
        return Ctx(email=None, user=None)
    payload = verify_token(token)
    if not payload:
        return Ctx(email=None, user=None)
    user = find_user_by_email(db, payload.get("email"))
    return Ctx(email=payload.get("email"), user=user)


def find_user_by_email(db: Session, email: Optional[str]) -> Optional[User]:
    if not email:
        return None
    return db.query(User).filter(func.lower(User.email) == email.lower()).first()


def normalize_mobile(mobile) -> str:
    digits = re.sub(r"\D", "", str(mobile or ""))
    if len(digits) == 12 and digits.startswith("91"):
        return digits[2:]
    return digits


def find_user_by_mobile(db: Session, mobile: str) -> Optional[User]:
    if not mobile:
        return None
    return db.query(User).filter(User.mobile == str(mobile).strip()).first()


def find_user_by_normalized_mobile(db: Session, mobile: str, exclude_id: Optional[str] = None) -> Optional[User]:
    target = normalize_mobile(mobile)
    if not target:
        return None
    q = db.query(User).filter(User.deleted.is_(False))
    if exclude_id:
        q = q.filter(User.id != exclude_id)
    for u in q.all():
        if normalize_mobile(u.mobile) == target:
            return u
    return None


def find_user_by_identifier(db: Session, identifier: str) -> Optional[User]:
    ident = str(identifier or "").strip()
    if not ident:
        return None
    if "@" in ident:
        return find_user_by_email(db, ident)
    return find_user_by_mobile(db, ident) or find_user_by_email(db, ident)


def require_auth(ctx: Ctx) -> User:
    if not ctx or not ctx.user:
        raise ApiError("Unauthorized: please log in.")
    if not ctx.user.active:
        raise ApiError("Your account is not active.")
    if ctx.user.status != "APPROVED":
        raise ApiError("Your account is not yet approved.")
    return ctx.user


def require_role(ctx: Ctx, roles: list[str]) -> User:
    user = require_auth(ctx)
    if user.role not in roles:
        raise ApiError(f"Forbidden: requires role {' or '.join(roles)}")
    return user


def is_admin(user: User) -> bool:
    return bool(user and user.role == "DevOps" and user.power)


def require_admin(ctx: Ctx) -> User:
    user = require_auth(ctx)
    if not is_admin(user):
        raise ApiError("Forbidden: DevOps Admin only.")
    return user
