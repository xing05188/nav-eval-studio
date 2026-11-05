"""用户管理（管理员）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.response import CONFLICT, FORBIDDEN, NOT_FOUND, AppError, ok
from ..core.security import hash_password
from ..db.session import get_db
from ..models import AppUser
from ..schemas.auth import UserCreate, UserOut, UserUpdate
from .deps import client_ip, now_str, require_roles, write_audit

router = APIRouter(prefix="/users", tags=["users"])


@router.get("")
def list_users(
    _: AppUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    users = db.scalars(select(AppUser).order_by(AppUser.id)).all()
    return ok([UserOut.model_validate(user).model_dump() for user in users])


@router.post("")
def create_user(
    payload: UserCreate,
    request: Request,
    user: AppUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    exists = db.scalar(select(AppUser).where(AppUser.username == payload.username))
    if exists:
        raise AppError(CONFLICT, "用户名已存在")

    password_hash, salt = hash_password(payload.password)
    created = AppUser(
        username=payload.username,
        display_name=payload.display_name or payload.username,
        password_hash=password_hash,
        password_salt=salt,
        role=payload.role,
        enabled=1,
        created_at=now_str(),
    )
    db.add(created)
    db.flush()
    write_audit(db, user, "user.create", "user", created.id,
                {"username": created.username, "role": created.role}, client_ip(request))
    return ok(UserOut.model_validate(created).model_dump())


@router.patch("/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    user: AppUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    target = db.get(AppUser, user_id)
    if target is None:
        raise AppError(NOT_FOUND, "用户不存在")

    if target.id == user.id and (
        payload.enabled is False or (payload.role is not None and payload.role != "admin")
    ):
        raise AppError(FORBIDDEN, "不能禁用或降级当前登录账号")

    changes: dict[str, object] = {}
    if payload.display_name is not None:
        target.display_name = payload.display_name
        changes["display_name"] = payload.display_name
    if payload.role is not None:
        target.role = payload.role
        changes["role"] = payload.role
    if payload.enabled is not None:
        target.enabled = 1 if payload.enabled else 0
        changes["enabled"] = payload.enabled
    if payload.password:
        password_hash, salt = hash_password(payload.password)
        target.password_hash = password_hash
        target.password_salt = salt
        changes["password"] = "reset"

    write_audit(db, user, "user.update", "user", target.id, changes, client_ip(request))
    return ok(UserOut.model_validate(target).model_dump())


@router.get("/count")
def user_count(
    _: AppUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    total = db.scalar(select(func.count()).select_from(AppUser)) or 0
    return ok({"total": total})
