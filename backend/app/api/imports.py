"""历史评测产物与备份库自动导入接口。

绑定配置中的 `import.results_root` / `import.backup_root`（默认均为
/home/zjr/StreamVLN-kaggle-backup）。前端「备份库自动导入」页面先调
GET /import/backup 查看绑定目录、各类别候选数与自动导入状态，再用
POST /import/backup 预览（dry_run）或执行导入；PUT /import/backup/auto
可在运行时修改自动导入开关，无需重启服务。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ..core.response import ok, page
from ..db.session import get_db
from ..models import AppUser
from ..schemas.imports import BackupAutoConfig, BackupImportRequest, ResultImportRequest
from ..services import backup_import_service, import_service
from ..services.backup_auto_importer import get_auto_importer, update_auto_config
from .deps import client_ip, get_current_user, require_roles, write_audit

router = APIRouter(tags=["import"])

WRITE_ROLES = require_roles("admin", "operator")


@router.get("/import/sources")
def import_sources(_: AppUser = Depends(get_current_user)):
    return ok(import_service.describe())


@router.post("/import/results")
def import_results(
    payload: ResultImportRequest,
    request: Request,
    user: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    root = Path(payload.root_path).expanduser() if payload.root_path else None
    summary = import_service.import_results(
        db, str(root) if root else None, force=payload.force, dry_run=payload.dry_run
    )
    if not payload.dry_run:
        write_audit(
            db,
            user,
            "import.results",
            "task",
            "",
            {
                "root": summary["root"],
                "scanned": summary["scanned"],
                "created": summary["created"],
                "updated": summary["updated"],
                "skipped": summary["skipped"],
                "failed": summary["failed"],
            },
            client_ip(request),
        )
    db.commit()
    return ok(summary)


@router.get("/import/backup")
def backup_overview(
    root_path: str | None = Query(default=None),
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """绑定目录、各类别候选数量、库内统计与自动导入状态。"""
    data = backup_import_service.describe(db, root_path)
    data["auto"] = get_auto_importer().status()
    return ok(data)


@router.post("/import/backup")
def run_backup_import(
    payload: BackupImportRequest,
    request: Request,
    user: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    """扫描并执行备份库导入；dry_run=True 时只返回预览。"""
    summary = backup_import_service.run_import(
        db,
        payload.root_path,
        sections=payload.sections or None,
        dry_run=payload.dry_run,
        force=payload.force,
        scan_episodes=payload.scan_episodes,
        reason="manual",
    )
    if not payload.dry_run:
        write_audit(
            db,
            user,
            "import.backup",
            "backup",
            "",
            {
                "root": summary["root"],
                "sections": summary["sections"],
                "scanned": summary["scanned"],
                "created": summary["created"],
                "updated": summary["updated"],
                "skipped": summary["skipped"],
                "failed": summary["failed"],
                "force": payload.force,
            },
            client_ip(request),
        )
        db.commit()
    return ok(summary)


@router.put("/import/backup/auto")
def update_backup_auto(
    payload: BackupAutoConfig,
    request: Request,
    user: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    """运行时修改自动导入开关、间隔、根目录与导入类别。"""
    config = update_auto_config(db, payload)
    write_audit(
        db,
        user,
        "import.backup.auto",
        "backup",
        "",
        payload.model_dump(exclude_unset=True),
        client_ip(request),
    )
    db.commit()
    return ok(config)


@router.get("/import/backup/assets")
def list_backup_assets(
    section: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    page_no: int = Query(default=1, ge=1, alias="page"),
    page_size: int = Query(default=20, ge=1, le=200),
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """分页检索已索引的备份资料；大文件只登记路径，不复制内容。"""
    items, total = backup_import_service.list_assets(
        db,
        section=section,
        kind=kind,
        status=status,
        q=q,
        page=page_no,
        page_size=page_size,
    )
    return ok(page(items, total, page_no, page_size))
