"""结果分析接口：对比矩阵、消融、显著性检验、长时曲线与失败归因。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..core.response import PARAM_INVALID, AppError, ok
from ..db.session import get_db
from ..models import AppUser
from ..schemas.analysis import BootstrapRequest
from ..services import analysis_service
from .deps import get_current_user

router = APIRouter(prefix="/analysis", tags=["analysis"])

MAX_TASKS = 10


def _parse_task_ids(raw: str) -> list[int]:
    task_ids: list[int] = []
    for part in (raw or "").replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            task_ids.append(int(part))
        except ValueError as exc:
            raise AppError(PARAM_INVALID, f"任务编号不合法：{part}") from exc
    task_ids = list(dict.fromkeys(task_ids))
    if not task_ids:
        raise AppError(PARAM_INVALID, "请至少选择一个任务")
    if len(task_ids) > MAX_TASKS:
        raise AppError(PARAM_INVALID, f"单次最多对比 {MAX_TASKS} 个任务")
    return task_ids


@router.get("/tasks")
def candidate_tasks(
    limit: int = Query(default=200, ge=1, le=500),
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """已有指标结果的任务列表，供前端选择。"""
    return ok({"items": analysis_service.list_candidates(db, limit=limit)})


@router.get("/compare")
def compare(
    task_ids: str = Query(..., description="逗号分隔的任务编号，例如 12,13,14"),
    baseline_id: int | None = Query(default=None, description="基线任务编号，缺省取第一个"),
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(analysis_service.compare(db, _parse_task_ids(task_ids), baseline_id=baseline_id))


@router.get("/ablation")
def ablation(
    task_ids: str = Query(..., description="逗号分隔的任务编号"),
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(analysis_service.ablation(db, _parse_task_ids(task_ids)))


@router.post("/bootstrap")
def bootstrap(
    payload: BootstrapRequest,
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(
        analysis_service.paired_bootstrap(
            db,
            payload.task_a,
            payload.task_b,
            iterations=payload.iterations,
            seed=payload.seed,
        )
    )


@router.get("/longhorizon")
def long_horizon(
    task_id: int = Query(..., gt=0),
    buckets: int = Query(default=5, ge=2, le=10),
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(analysis_service.long_horizon(db, task_id, buckets=buckets))


@router.get("/failures")
def failures(
    task_id: int = Query(..., gt=0),
    limit: int = Query(default=20, ge=1, le=200),
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(analysis_service.failures(db, task_id, limit=limit))
