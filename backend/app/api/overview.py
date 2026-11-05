"""首页总览统计。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.response import ok
from ..db.session import get_db
from ..models import AppUser, Dataset, EvalTask, ModelProfile, TaskEpisode
from .deps import get_current_user

router = APIRouter(tags=["overview"])


@router.get("/overview")
def overview(
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    def count(model, *conditions) -> int:
        stmt = select(func.count()).select_from(model)
        for condition in conditions:
            stmt = stmt.where(condition)
        return db.scalar(stmt) or 0

    dataset_count = count(Dataset)
    model_count = count(ModelProfile)
    task_count = count(EvalTask)

    rows = db.execute(
        select(EvalTask, Dataset.name, ModelProfile.name)
        .join(Dataset, Dataset.id == EvalTask.dataset_id)
        .join(ModelProfile, ModelProfile.id == EvalTask.model_profile_id)
        .order_by(EvalTask.id.desc())
        .limit(8)
    ).all()

    recent = []
    for task, dataset_name, model_name in rows:
        try:
            metrics = json.loads(task.metrics_json or "{}")
        except json.JSONDecodeError:
            metrics = {}
        recent.append(
            {
                "id": task.id,
                "name": task.name,
                "status": task.status,
                "dataset": dataset_name,
                "model": model_name,
                "progress_done": task.progress_done,
                "progress_total": task.progress_total,
                "sr": metrics.get("sr"),
                "spl": metrics.get("spl"),
                "queued_at": task.queued_at,
                "duration_s": task.duration_s,
            }
        )

    finished = count(EvalTask, EvalTask.status.in_(("succeeded", "failed", "canceled")))
    success_tasks = count(EvalTask, EvalTask.status == "succeeded")

    return ok(
        {
            "counts": {
                "datasets": dataset_count,
                "models": model_count,
                "episodes": db.scalar(select(func.sum(Dataset.episode_count))) or 0,
                "tasks": task_count,
                "episode_results": count(TaskEpisode),
            },
            "queue": {
                "queued": count(EvalTask, EvalTask.status == "queued"),
                "running": count(EvalTask, EvalTask.status.in_(("preparing", "running"))),
                "paused": count(EvalTask, EvalTask.status == "paused"),
            },
            "finish_rate": round(success_tasks / finished, 4) if finished else None,
            "recent_tasks": recent,
        }
    )
