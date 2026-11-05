"""系统状态、GPU 探测与设置管理。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.response import PARAM_INVALID, AppError, ok
from ..db.session import get_db
from ..models import AppUser, Dataset, EvalTask, ModelProfile, Setting
from ..schemas.system import SettingsUpdate
from .deps import client_ip, get_current_user, now_str, require_roles, write_audit

router = APIRouter(tags=["system"])

EDITABLE_KEYS = {
    "max_parallel_tasks",
    "artifact_keep_days",
    "replay_frame_interval",
    "demo_mode",
    "gpu_ids",
}

NUMERIC_RULES = {
    "max_parallel_tasks": (1, 8),
    "artifact_keep_days": (1, 3650),
    "replay_frame_interval": (1, 10),
}


def _normalize_setting(key: str, value: str) -> str:
    raw = (value or "").strip()
    if key in NUMERIC_RULES:
        low, high = NUMERIC_RULES[key]
        try:
            number = int(raw)
        except ValueError as exc:
            raise AppError(PARAM_INVALID, f"{key} 必须是整数") from exc
        if not low <= number <= high:
            raise AppError(PARAM_INVALID, f"{key} 需在 {low}-{high} 之间")
        return str(number)
    if key == "demo_mode":
        if raw not in ("0", "1"):
            raise AppError(PARAM_INVALID, "demo_mode 只能为 0 或 1")
        return raw
    if key == "gpu_ids":
        if len(raw) > 64:
            raise AppError(PARAM_INVALID, "GPU 列表长度不能超过 64")
        parts = [part.strip() for part in raw.split(",") if part.strip()]
        if any(not part.isdigit() for part in parts):
            raise AppError(PARAM_INVALID, "GPU 列表应为逗号分隔的数字，例如 0,1")
        return ",".join(dict.fromkeys(parts))
    return raw


def _dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def _gpu_info() -> dict:
    if shutil.which("nvidia-smi") is None:
        return {"available": False, "reason": "未检测到 nvidia-smi", "items": []}
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return {"available": False, "reason": str(exc), "items": []}

    if completed.returncode != 0:
        return {"available": False, "reason": completed.stderr.strip(), "items": []}

    items = []
    for line in completed.stdout.strip().splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 5:
            continue
        items.append(
            {
                "index": int(parts[0]) if parts[0].isdigit() else parts[0],
                "name": parts[1],
                "memory_total_mb": int(float(parts[2])),
                "memory_used_mb": int(float(parts[3])),
                "utilization": int(float(parts[4])),
            }
        )
    return {"available": bool(items), "reason": "", "items": items}


@router.get("/system/status")
def system_status(
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    work_dir = settings.storage.work_dir
    disk = shutil.disk_usage(work_dir if work_dir.exists() else settings.root)

    def count(model, *conditions) -> int:
        stmt = select(func.count()).select_from(model)
        for condition in conditions:
            stmt = stmt.where(condition)
        return db.scalar(stmt) or 0

    return ok(
        {
            "version": "1.0.0",
            "work_dir": str(work_dir),
            "db_size_mb": round(settings.storage.db_path.stat().st_size / 1048576, 2)
            if settings.storage.db_path.exists()
            else 0,
            "storage_used_mb": round(_dir_size(work_dir) / 1048576, 2),
            "disk_total_gb": round(disk.total / 1073741824, 1),
            "disk_free_gb": round(disk.free / 1073741824, 1),
            "counts": {
                "datasets": count(Dataset),
                "models": count(ModelProfile),
                "episodes": db.scalar(select(func.sum(Dataset.episode_count))) or 0,
                "tasks": count(EvalTask),
                "queued": count(EvalTask, EvalTask.status == "queued"),
                "running": count(EvalTask, EvalTask.status.in_(("preparing", "running"))),
                "paused": count(EvalTask, EvalTask.status == "paused"),
                "failed": count(EvalTask, EvalTask.status == "failed"),
            },
            "gpu": _gpu_info(),
        }
    )


@router.get("/system/gpus")
def list_gpus(_: AppUser = Depends(get_current_user)):
    return ok(_gpu_info())


@router.get("/settings")
def read_settings(
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(Setting).order_by(Setting.key)).all()
    return ok([{"key": row.key, "value": row.value, "updated_at": row.updated_at} for row in rows])


@router.put("/settings")
def update_settings(
    payload: SettingsUpdate,
    request: Request,
    user: AppUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    updated: list[str] = []
    normalized: dict[str, str] = {}
    for item in payload.items:
        if item.key not in EDITABLE_KEYS:
            raise AppError(PARAM_INVALID, f"不支持的配置项：{item.key}")
        value = _normalize_setting(item.key, item.value)
        row = db.get(Setting, item.key)
        if row is None:
            row = Setting(key=item.key, value=value, updated_at=now_str())
            db.add(row)
        else:
            row.value = value
            row.updated_at = now_str()
        normalized[item.key] = value
        updated.append(item.key)

    settings = get_settings()
    if "max_parallel_tasks" in normalized:
        from ..services.scheduler import get_scheduler

        get_scheduler().set_max_parallel(int(normalized["max_parallel_tasks"]))
    if "gpu_ids" in normalized:
        settings.scheduler.gpu_ids = [
            part for part in normalized["gpu_ids"].split(",") if part
        ]

    write_audit(db, user, "setting.update", "setting", ",".join(updated), normalized, client_ip(request))
    return ok({"updated": updated, "values": normalized})
