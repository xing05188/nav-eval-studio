"""评测任务服务：创建、查询、指标聚合与日志读取。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.response import CAUSAL_VIOLATION, NOT_FOUND, PARAM_INVALID, AppError
from ..models import (
    Dataset,
    Episode,
    EvalTask,
    ModelProfile,
    ResourceSample,
    Split,
    SplitEpisode,
    TaskEpisode,
)
from ..schemas.task import TaskCreate
from . import template_service

REQUIRED_INPUTS = {
    "vision": {"rgb"},
    "vision_geo": {"rgb", "depth"},
    "vision_geo_state": {"rgb", "depth", "pose"},
}

TERMINAL_STATUS = ("succeeded", "failed", "canceled")


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _loads(text: str | None, default: Any) -> Any:
    try:
        return json.loads(text or "")
    except (json.JSONDecodeError, TypeError):
        return default


def task_run_dir(task_id: int) -> Path:
    directory = get_settings().runs_dir / f"task-{task_id:06d}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def to_brief(task: EvalTask, dataset_name: str = "", split_name: str = "", model_name: str = "") -> dict:
    return {
        "id": task.id,
        "name": task.name,
        "status": task.status,
        "dataset_id": task.dataset_id,
        "dataset_name": dataset_name,
        "split_id": task.split_id,
        "split_name": split_name,
        "model_profile_id": task.model_profile_id,
        "model_name": model_name,
        "progress_done": task.progress_done,
        "progress_total": task.progress_total,
        "metrics": _loads(task.metrics_json, {}),
        "error_msg": task.error_msg,
        "queued_at": task.queued_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "duration_s": task.duration_s,
        "note": task.note,
    }


def get_task(db: Session, task_id: int) -> EvalTask:
    task = db.get(EvalTask, task_id)
    if task is None:
        raise AppError(NOT_FOUND, "评测任务不存在")
    return task


def list_tasks(
    db: Session,
    status: str | None = None,
    dataset_id: int | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
    order: str = "desc",
) -> tuple[list[dict], int]:
    """按任务时间（queued_at）排序，默认最新在前；缺失时间的记录始终排在最后。"""
    conditions = []
    if status:
        conditions.append(EvalTask.status == status)
    if dataset_id:
        conditions.append(EvalTask.dataset_id == dataset_id)
    if q:
        conditions.append(EvalTask.name.like(f"%{q}%"))

    total = db.scalar(select(func.count()).select_from(EvalTask).where(*conditions)) or 0
    missing_time = case(
        (EvalTask.queued_at.is_(None), 1),
        (EvalTask.queued_at == "", 1),
        else_=0,
    )
    descending = order == "desc"
    time_order = EvalTask.queued_at.desc() if descending else EvalTask.queued_at.asc()
    id_order = EvalTask.id.desc() if descending else EvalTask.id.asc()
    rows = db.execute(
        select(EvalTask, Dataset.name, Split.name, ModelProfile.name)
        .join(Dataset, Dataset.id == EvalTask.dataset_id)
        .join(Split, Split.id == EvalTask.split_id)
        .join(ModelProfile, ModelProfile.id == EvalTask.model_profile_id)
        .where(*conditions)
        .order_by(missing_time, time_order, id_order)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return [to_brief(task, dn, sn, mn) for task, dn, sn, mn in rows], total


def _validate_inputs(model: ModelProfile, config: dict[str, Any]) -> None:
    modality = str(config.get("modality") or "vision")
    required = REQUIRED_INPUTS.get(modality, {"rgb"})
    allowed = {item for item in (model.allowed_inputs or "").split(",") if item}
    declared = set(config.get("allowed_inputs") or required)

    missing = required - allowed
    if missing:
        raise AppError(
            CAUSAL_VIOLATION,
            f"模型未声明所需的输入：{', '.join(sorted(missing))}，当前允许：{', '.join(sorted(allowed))}",
        )
    if not declared <= allowed:
        raise AppError(
            CAUSAL_VIOLATION,
            f"输入 {', '.join(sorted(declared - allowed))} 不在模型白名单内",
        )
    if "future" in " ".join(declared):
        raise AppError(CAUSAL_VIOLATION, "配置中出现未来观测输入，违反严格因果约束")


def create_task(db: Session, payload: TaskCreate, user_id: int | None) -> EvalTask:
    dataset = db.get(Dataset, payload.dataset_id)
    if dataset is None:
        raise AppError(NOT_FOUND, "数据集不存在")
    split = db.get(Split, payload.split_id)
    if split is None or split.dataset_id != payload.dataset_id:
        raise AppError(PARAM_INVALID, "切分不存在或不属于该数据集")
    model = db.get(ModelProfile, payload.model_profile_id)
    if model is None:
        raise AppError(NOT_FOUND, "模型档案不存在")

    template = None
    if payload.template_id:
        template = template_service.get_template(db, payload.template_id)

    base_config = _loads(model.default_config_json, {})
    config: dict[str, Any] = {
        "template_id": template.id if template else None,
        "modality": template.modality if template else "vision",
        "memory_policy": template.memory_policy if template else "fixed_window",
        "history_len": 8,
        "slow_update_interval": 4,
        "prune_ratio": 0.0,
        "max_steps": 500,
        "seed": 42,
        "eval_split": split.base_split or "val_unseen",
        "gpu_ids": payload.gpu_ids,
        "num_future_steps": 4,
    }
    if template:
        config.update(_loads(template.params_json, {}))
    config.update(base_config)
    config.update(payload.overrides or {})

    config["allowed_inputs"] = sorted(
        set(config.get("allowed_inputs") or REQUIRED_INPUTS.get(config["modality"], {"rgb"}))
    )
    _validate_inputs(model, config)

    episode_ids = [
        row[0]
        for row in db.execute(
            select(SplitEpisode.episode_id)
            .where(SplitEpisode.split_id == split.id)
            .order_by(SplitEpisode.ordinal)
        ).all()
    ]
    if not episode_ids:
        raise AppError(PARAM_INVALID, "切分中没有 episode，请先生成切分")

    task = EvalTask(
        name=payload.name,
        dataset_id=dataset.id,
        split_id=split.id,
        model_profile_id=model.id,
        config_json=json.dumps(config, ensure_ascii=False),
        status="queued",
        priority=payload.priority,
        progress_done=0,
        progress_total=len(episode_ids),
        metrics_json="{}",
        error_msg="",
        gpu_ids=payload.gpu_ids or "",
        created_by=user_id,
        queued_at=now_str(),
        note=payload.note,
    )
    db.add(task)
    db.flush()

    db.execute(
        TaskEpisode.__table__.insert(),
        [
            {
                "task_id": task.id,
                "episode_id": episode_id,
                "status": "pending",
                "success": 0,
                "updated_at": now_str(),
            }
            for episode_id in episode_ids
        ],
    )
    db.flush()
    return task


def task_detail(db: Session, task: EvalTask) -> dict[str, Any]:
    dataset = db.get(Dataset, task.dataset_id)
    split = db.get(Split, task.split_id)
    model = db.get(ModelProfile, task.model_profile_id)

    status_rows = db.execute(
        select(TaskEpisode.status, func.count())
        .where(TaskEpisode.task_id == task.id)
        .group_by(TaskEpisode.status)
    ).all()
    reason_rows = db.execute(
        select(TaskEpisode.failure_reason, func.count())
        .where(TaskEpisode.task_id == task.id, TaskEpisode.failure_reason != "")
        .group_by(TaskEpisode.failure_reason)
        .order_by(func.count().desc())
    ).all()

    data = to_brief(
        task,
        dataset.name if dataset else "",
        split.name if split else "",
        model.name if model else "",
    )
    data.update(
        {
            "config": _loads(task.config_json, {}),
            "counts": {status: count for status, count in status_rows},
            "reasons": [{"reason": reason, "count": count} for reason, count in reason_rows],
            "run_dir": str(task_run_dir(task.id)),
            "gpu_ids": task.gpu_ids,
        }
    )
    return data


def list_task_episodes(
    db: Session,
    task: EvalTask,
    status: str | None = None,
    reason: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    conditions = [TaskEpisode.task_id == task.id]
    if status:
        conditions.append(TaskEpisode.status == status)
    if reason:
        conditions.append(TaskEpisode.failure_reason == reason)

    stmt = (
        select(TaskEpisode, Episode)
        .join(Episode, Episode.id == TaskEpisode.episode_id)
        .where(*conditions)
        .order_by(Episode.id)
    )
    total_stmt = (
        select(func.count())
        .select_from(TaskEpisode)
        .join(Episode, Episode.id == TaskEpisode.episode_id)
        .where(*conditions)
    )
    if q:
        stmt = stmt.where(Episode.instruction.like(f"%{q}%"))
        total_stmt = total_stmt.where(Episode.instruction.like(f"%{q}%"))

    total = db.scalar(total_stmt) or 0
    rows = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).all()

    items = []
    for row, episode in rows:
        items.append(
            {
                "id": row.id,
                "episode_key": episode.episode_id,
                "scene_id": episode.scene_id,
                "instruction": episode.instruction,
                "status": row.status,
                "success": bool(row.success),
                "spl": round(row.spl, 4),
                "ne": round(row.ne, 3),
                "os": round(row.os, 4),
                "ndtw": round(row.ndtw, 4),
                "tl": round(row.tl, 3),
                "steps": row.steps,
                "latency_avg_ms": round(row.latency_avg_ms, 1),
                "gpu_mem_peak_mb": row.gpu_mem_peak_mb,
                "failure_reason": row.failure_reason,
                "manual_reason": row.manual_reason,
            }
        )
    return items, total


def aggregate_metrics(db: Session, task: EvalTask) -> dict[str, Any]:
    row = db.execute(
        select(
            func.count(),
            func.sum(TaskEpisode.success),
            func.avg(TaskEpisode.spl),
            func.avg(TaskEpisode.ne),
            func.avg(TaskEpisode.os),
            func.avg(TaskEpisode.ndtw),
            func.avg(TaskEpisode.tl),
            func.avg(TaskEpisode.latency_avg_ms),
            func.max(TaskEpisode.gpu_mem_peak_mb),
            func.max(TaskEpisode.tokens_peak),
        ).where(
            TaskEpisode.task_id == task.id,
            TaskEpisode.status.in_(("success", "failed")),
        )
    ).one()

    total = int(row[0] or 0)
    if total == 0:
        metrics: dict[str, Any] = {}
    else:
        metrics = {
            "episodes": total,
            "sr": round(float(row[1] or 0) / total, 4),
            "spl": round(float(row[2] or 0), 4),
            "ne": round(float(row[3] or 0), 3),
            "os": round(float(row[4] or 0), 4),
            "ndtw": round(float(row[5] or 0), 4),
            "tl": round(float(row[6] or 0), 3),
            "latency_avg_ms": round(float(row[7] or 0), 1),
            "gpu_mem_peak_mb": int(row[8] or 0),
            "tokens_peak": int(row[9] or 0),
        }
    task.metrics_json = json.dumps(metrics, ensure_ascii=False)
    return metrics


def reset_failed_episodes(db: Session, task: EvalTask) -> int:
    rows = db.scalars(
        select(TaskEpisode).where(
            TaskEpisode.task_id == task.id,
            TaskEpisode.status.in_(("failed", "error", "running")),
        )
    ).all()
    for row in rows:
        row.status = "pending"
        row.failure_reason = ""
        row.updated_at = now_str()
    db.flush()
    return len(rows)


def pending_count(db: Session, task: EvalTask) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(TaskEpisode)
            .where(TaskEpisode.task_id == task.id, TaskEpisode.status == "pending")
        )
        or 0
    )


def log_tail(task: EvalTask, lines: int = 200) -> list[str]:
    path = task_run_dir(task.id) / "run.log"
    if not path.exists():
        return []
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > 256 * 1024:
            handle.seek(-256 * 1024, 2)
        content = handle.read().decode("utf-8", errors="replace")
    return content.splitlines()[-lines:]


def samples(db: Session, task: EvalTask, limit: int = 500) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(ResourceSample)
        .where(ResourceSample.task_id == task.id)
        .order_by(ResourceSample.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "step": row.step,
            "ts": row.ts,
            "gpu_mem_mb": row.gpu_mem_mb,
            "latency_ms": round(row.latency_ms, 1),
            "tokens": row.tokens,
            "ctx_len": row.ctx_len,
        }
        for row in reversed(rows)
    ]


def mark_stale_tasks(db: Session) -> int:
    """服务重启后，把遗留的 running/preparing 任务标记为失败。

    备份库导入的外部评测由导入守护按结果文件同步状态，重启不应误判为中断。
    """
    rows = db.scalars(
        select(EvalTask).where(EvalTask.status.in_(("running", "preparing")))
    ).all()
    count = 0
    for task in rows:
        config = _loads(task.config_json, {})
        if isinstance(config, dict) and config.get("imported") and config.get("source_dir"):
            continue
        task.status = "failed"
        task.error_msg = "服务重启，任务中断"
        task.finished_at = now_str()
        count += 1
    db.flush()
    return count
