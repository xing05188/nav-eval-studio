"""登录、登出、当前用户与口令修改。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.response import UNAUTHORIZED, AppError, ok
from ..core.security import create_token, hash_password, verify_password
from ..db.session import get_db
from ..models import AppUser
from ..schemas.auth import LoginRequest, LoginResponse, PasswordChange, UserOut
from .deps import client_ip, get_current_user, now_str, write_audit

router = APIRouter(prefix="/auth", tags=["auth"])

# 用户不存在时也执行一次哈希，避免通过响应时间枚举账号
_DUMMY_HASH, _DUMMY_SALT = hash_password("naveval-dummy-password")


@router.post("/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    settings = get_settings()
    user = db.scalar(select(AppUser).where(AppUser.username == payload.username))
    ip = client_ip(request)

    if user is None:
        verify_password(payload.password, _DUMMY_HASH, _DUMMY_SALT)
        write_audit(db, None, "login.failed", "user", payload.username,
                    {"reason": "not_found"}, ip)
        raise AppError(UNAUTHORIZED, "用户名或口令错误")

    if not verify_password(payload.password, user.password_hash, user.password_salt):
        write_audit(db, user, "login.failed", "user", user.id, {"reason": "bad_password"}, ip)
        raise AppError(UNAUTHORIZED, "用户名或口令错误")

    if not user.enabled:
        write_audit(db, user, "login.failed", "user", user.id, {"reason": "disabled"}, ip)
        raise AppError(UNAUTHORIZED, "账号已禁用，请联系管理员")

    user.last_login_at = now_str()
    write_audit(db, user, "login", "user", user.id, {}, ip)

    token = create_token(user.id, user.username, user.role, settings.security.token_ttl_hours)
    db.commit()

    return ok(
        LoginResponse(
            access_token=token,
            expires_in=settings.security.token_ttl_hours * 3600,
            user=UserOut.model_validate(user),
        ).model_dump()
    )


@router.post("/logout")
def logout(
    request: Request,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    write_audit(db, user, "logout", "user", user.id, {}, client_ip(request))
    return ok({"logged_out": True})


@router.get("/me")
def me(user: AppUser = Depends(get_current_user)):
    return ok(UserOut.model_validate(user).model_dump())


@router.post("/password")
def change_password(
    payload: PasswordChange,
    request: Request,
    user: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.old_password, user.password_hash, user.password_salt):
        raise AppError(UNAUTHORIZED, "原口令不正确")
    if payload.old_password == payload.new_password:
        raise AppError(1001, "新口令不能与原口令相同")

    password_hash, salt = hash_password(payload.new_password)
    user.password_hash = password_hash
    user.password_salt = salt
    write_audit(db, user, "password.change", "user", user.id, {}, client_ip(request))
    return ok({"updated": True})
