"""报告接口：生成、列举与下载。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..core.response import ok
from ..db.session import get_db
from ..models import AppUser
from ..schemas.analysis import ReportCreate
from ..services import report_service
from .deps import client_ip, get_current_user, require_roles, write_audit

router = APIRouter(prefix="/reports", tags=["reports"])

WRITE_ROLES = require_roles("admin", "operator")


@router.post("")
def create_report(
    payload: ReportCreate,
    request: Request,
    user: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    artifact = report_service.generate(db, payload)
    write_audit(
        db,
        user,
        "report.generate",
        "report",
        artifact["id"],
        {
            "task_ids": artifact["task_ids"],
            "format": artifact["format"],
            "name": artifact["name"],
        },
        client_ip(request),
    )
    db.commit()
    return ok(artifact)


@router.get("")
def list_reports(
    task_id: int | None = Query(default=None, gt=0),
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok({"items": report_service.list_reports(db, task_id=task_id)})


@router.get("/{artifact_id}/download")
def download_report(
    artifact_id: int,
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    artifact, target = report_service.resolve(db, artifact_id)
    fmt = (artifact.name.rsplit(".", 1)[-1] or "md").lower()
    return FileResponse(
        target,
        media_type=report_service.MEDIA_TYPES.get(fmt, "application/octet-stream"),
        filename=artifact.name,
    )
