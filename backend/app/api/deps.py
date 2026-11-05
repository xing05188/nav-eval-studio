"""公共依赖：数据库会话、当前用户、角色校验、审计写入。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable

from fastapi import Depends, Query, Request
from sqlalchemy.orm import Session

from ..core.response import FORBIDDEN, UNAUTHORIZED, AppError
from ..core.security import decode_token
from ..db.session import get_db
from ..models import AppUser, AuditLog


def now_str() -> str:
    """本地时区时间字符串，用于界面展示与审计记录。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _load_user(db: Session, token: str) -> AppUser:
    payload = decode_token(token)
    user = db.get(AppUser, int(payload.get("uid", 0)))
    if user is None:
        raise AppError(UNAUTHORIZED, "用户不存在")
    if not user.enabled:
        raise AppError(FORBIDDEN, "账号已禁用")
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> AppUser:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        raise AppError(UNAUTHORIZED, "未登录或缺少访问令牌")
    token = header[7:].strip()
    payload = decode_token(token)
    user = db.get(AppUser, int(payload.get("uid", 0)))
    if user is None:
        raise AppError(UNAUTHORIZED, "用户不存在")
    if not user.enabled:
        raise AppError(FORBIDDEN, "账号已禁用")
    return user


def get_user_allow_query_token(
    request: Request,
    token: str | None = Query(default=None, include_in_schema=False),
    db: Session = Depends(get_db),
) -> AppUser:
    """图片等无法携带请求头的场景，允许通过 ?token= 传递令牌。"""
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return _load_user(db, header[7:].strip())
    if token:
        return _load_user(db, token)
    raise AppError(UNAUTHORIZED, "未登录或缺少访问令牌")


def require_roles(*roles: str) -> Callable[..., AppUser]:
    """生成角色依赖，示例：Depends(require_roles("admin"))。"""

    def _dependency(user: AppUser = Depends(get_current_user)) -> AppUser:
        if roles and user.role not in roles:
            raise AppError(FORBIDDEN, f"需要角色：{'/'.join(roles)}")
        return user

    return _dependency


def write_audit(
    db: Session,
    user: AppUser | None,
    action: str,
    target_type: str = "",
    target_id: str | int = "",
    detail: dict[str, Any] | None = None,
    ip: str = "",
) -> None:
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            username=user.username if user else "",
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
            client_ip=ip,
            created_at=now_str(),
        )
    )
    db.flush()
