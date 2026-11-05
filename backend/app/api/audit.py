"""操作审计查询。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.response import ok, page
from ..db.session import get_db
from ..models import AppUser, AuditLog
from .deps import require_roles

router = APIRouter(tags=["audit"])


@router.get("/audit")
def list_audit(
    page_no: int = Query(default=1, ge=1, alias="page"),
    page_size: int = Query(default=20, ge=1, le=200),
    action: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    _: AppUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    conditions = []
    if action:
        conditions.append(AuditLog.action.like(f"{action}%"))
    if target_type:
        conditions.append(AuditLog.target_type == target_type)

    total_stmt = select(func.count()).select_from(AuditLog)
    stmt = select(AuditLog)
    for condition in conditions:
        total_stmt = total_stmt.where(condition)
        stmt = stmt.where(condition)

    total = db.scalar(total_stmt) or 0
    rows = db.scalars(
        stmt.order_by(AuditLog.id.desc()).offset((page_no - 1) * page_size).limit(page_size)
    ).all()

    items = []
    for row in rows:
        try:
            detail = json.loads(row.detail_json or "{}")
        except json.JSONDecodeError:
            detail = {}
        items.append(
            {
                "id": row.id,
                "username": row.username,
                "action": row.action,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "detail": detail,
                "client_ip": row.client_ip,
                "created_at": row.created_at,
            }
        )
    return ok(page(items, total, page_no, page_size))
