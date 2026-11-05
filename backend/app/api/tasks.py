"""评测任务接口：创建、查询、控制与实时事件。"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..core.events import BUS
from ..core.response import CONFLICT, NOT_FOUND, AppError, ok, page
from ..db.session import get_db
from ..models import AppUser, EvalTask
from ..schemas.task import TaskCreate
from ..services import scheduler as scheduler_module
from ..services import task_service
from .deps import (
    client_ip,
    get_current_user,
    get_user_allow_query_token,
    require_roles,
    write_audit,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])

WRITE_ROLES = require_roles("admin", "operator")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("")
def list_tasks(
    status: str | None = Query(default=None),
    dataset_id: int | None = Query(default=None),
    q: str | None = Query(default=None),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    page_no: int = Query(default=1, ge=1, alias="page"),
    page_size: int = Query(default=20, ge=1, le=100),
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items, total = task_service.list_tasks(
        db,
        status=status,
        dataset_id=dataset_id,
        q=q,
        page=page_no,
        page_size=page_size,
        order=order,
    )
    return ok(page(items, total, page_no, page_size))


@router.post("")
def create_task(
    payload: TaskCreate,
    request: Request,
    user: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    task = task_service.create_task(db, payload, user.id)
    write_audit(
        db, user, "task.create", "task", task.id,
        {"name": task.name, "episodes": task.progress_total}, client_ip(request),
    )
    db.commit()

    scheduler_module.get_scheduler().submit(task.id)
    return ok(task_service.task_detail(db, task))


@router.get("/{task_id}")
def get_task(
    task_id: int,
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = task_service.get_task(db, task_id)
    return ok(task_service.task_detail(db, task))


@router.get("/{task_id}/episodes")
def list_episodes(
    task_id: int,
    status: str | None = Query(default=None),
    reason: str | None = Query(default=None),
    q: str | None = Query(default=None),
    page_no: int = Query(default=1, ge=1, alias="page"),
    page_size: int = Query(default=20, ge=1, le=200),
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = task_service.get_task(db, task_id)
    items, total = task_service.list_task_episodes(
        db, task, status=status, reason=reason, q=q, page=page_no, page_size=page_size
    )
    return ok(page(items, total, page_no, page_size))


@router.get("/{task_id}/logs")
def get_logs(
    task_id: int,
    lines: int = Query(default=200, ge=1, le=2000),
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = task_service.get_task(db, task_id)
    content = task_service.log_tail(task, lines=lines)
    return ok({"lines": content, "total_lines": len(content)})


@router.get("/{task_id}/samples")
def get_samples(
    task_id: int,
    limit: int = Query(default=500, ge=1, le=2000),
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = task_service.get_task(db, task_id)
    return ok(task_service.samples(db, task, limit=limit))


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: int,
    request: Request,
    user: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    task_service.get_task(db, task_id)
    status = await scheduler_module.get_scheduler().cancel(task_id)
    write_audit(db, user, "task.cancel", "task", task_id, {"status": status}, client_ip(request))
    db.commit()
    return ok({"task_id": task_id, "status": status})


@router.post("/{task_id}/pause")
async def pause_task(
    task_id: int,
    request: Request,
    user: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    task_service.get_task(db, task_id)
    try:
        status = await scheduler_module.get_scheduler().pause(task_id)
    except RuntimeError as exc:
        raise AppError(CONFLICT, str(exc)) from exc
    write_audit(db, user, "task.pause", "task", task_id, {}, client_ip(request))
    db.commit()
    return ok({"task_id": task_id, "status": status})


@router.post("/{task_id}/resume")
async def resume_task(
    task_id: int,
    request: Request,
    user: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    task_service.get_task(db, task_id)
    try:
        status = await scheduler_module.get_scheduler().resume(task_id)
    except RuntimeError as exc:
        raise AppError(CONFLICT, str(exc)) from exc
    write_audit(db, user, "task.resume", "task", task_id, {}, client_ip(request))
    db.commit()
    return ok({"task_id": task_id, "status": status})


@router.post("/{task_id}/retry-failed")
def retry_failed(
    task_id: int,
    request: Request,
    user: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    task = task_service.get_task(db, task_id)
    if task.status in ("running", "preparing"):
        raise AppError(CONFLICT, "任务正在运行，请先取消或等待结束")

    reset = task_service.reset_failed_episodes(db, task)
    pending = task_service.pending_count(db, task)
    if reset == 0 and pending == 0:
        raise AppError(CONFLICT, "没有失败或未完成的 episode 需要重跑")

    task.status = "queued"
    task.error_msg = ""
    task.finished_at = None
    db.flush()
    task.progress_done = task.progress_total - task_service.pending_count(db, task)
    db.commit()

    write_audit(db, user, "task.retry", "task", task_id, {"reset": reset}, client_ip(request))
    db.commit()

    scheduler_module.get_scheduler().submit(task_id)
    return ok({"task_id": task_id, "status": "queued", "reset": reset})


@router.get("/{task_id}/events")
async def task_events(
    task_id: int,
    request: Request,
    _: AppUser = Depends(get_user_allow_query_token),
):
    from ..db.session import session_scope

    with session_scope() as db:
        task = db.get(EvalTask, task_id)
        if task is None:
            raise AppError(NOT_FOUND, "评测任务不存在")
        snapshot = {
            "status": task.status,
            "done": task.progress_done,
            "total": task.progress_total,
        }

    async def stream():
        queue = BUS.subscribe(task_id)
        try:
            yield _sse("state", snapshot)
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield _sse(message["event"], message["data"])
        finally:
            BUS.unsubscribe(task_id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
