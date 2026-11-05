"""切分删除接口（查询与创建挂在数据集下）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..core.response import ok
from ..db.session import get_db
from ..models import AppUser
from ..services import split_service
from .deps import client_ip, require_roles, write_audit

router = APIRouter(prefix="/splits", tags=["splits"])


@router.delete("/{split_id}")
def delete_split(
    split_id: int,
    request: Request,
    user: AppUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    split = split_service.get_split(db, split_id)
    name = split.name
    split_service.delete_split(db, split)
    write_audit(db, user, "split.delete", "split", split_id, {"name": name}, client_ip(request))
    db.commit()
    return ok({"deleted": True})
