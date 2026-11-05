"""评测任务调度器。

单进程内的异步调度：队列 + 并发额度 + GPU 互斥，任务体在独立线程中执行，
通过事件总线向 SSE 推送进度、资源采样与日志。每条 episode 完成即落库，
异常退出后可按已完成进度继续。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

from ..adapters import BaseAdapter, EpisodeRecord, RunContext, build_adapter
from ..core.config import Settings, get_settings
from ..core.events import BUS
from ..db.session import session_scope
from ..models import (
    Dataset,
    Episode,
    EvalTask,
    ModelProfile,
    ResourceSample,
    TaskEpisode,
)
from . import model_service, task_service

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._semaphore = asyncio.Semaphore(max(1, self.settings.scheduler.max_parallel_tasks))
        self._gpu_locks: dict[str, asyncio.Lock] = {}
        self._runtime: dict[int, dict[str, Any]] = {}
        self._dispatcher: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopping = False

    # ---------------------------------------------------------------- 生命周期

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        BUS.bind_loop(self._loop)

        with session_scope() as db:
            stale = task_service.mark_stale_tasks(db)
            queued = [
                task.id
                for task in db.scalars(
                    select(EvalTask).where(EvalTask.status == "queued").order_by(EvalTask.id)
                ).all()
            ]
        if stale:
            logger.warning("已将 %s 个中断任务标记为失败", stale)

        for task_id in queued:
            self._queue.put_nowait(task_id)
        if queued:
            logger.info("重新入队 %s 个待执行任务", len(queued))

        self._dispatcher = asyncio.create_task(self._dispatch())

    async def shutdown(self) -> None:
        self._stopping = True
        if self._dispatcher:
            self._dispatcher.cancel()
        for task_id, runtime in list(self._runtime.items()):
            runtime["ctx"].cancel_event.set()
            adapter = runtime.get("adapter")
            if adapter is not None:
                await asyncio.to_thread(adapter.stop)
            self._emit(task_id, "state", {"status": "canceled", "reason": "shutdown"})

    # ---------------------------------------------------------------- 入队

    def submit(self, task_id: int) -> None:
        """任意线程安全地入队。"""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._queue.put_nowait, task_id)
        else:
            self._queue.put_nowait(task_id)

    async def _dispatch(self) -> None:
        while not self._stopping:
            task_id = await self._queue.get()
            await self._semaphore.acquire()
            asyncio.create_task(self._run_wrapper(task_id))

    async def _run_wrapper(self, task_id: int) -> None:
        gpu_key = ""
        try:
            with session_scope() as db:
                task = db.get(EvalTask, task_id)
                gpu_key = (task.gpu_ids or "").split(",")[0].strip() if task else ""
        except Exception:  # noqa: BLE001 - 读取失败时按无 GPU 约束处理
            logger.exception("读取任务 GPU 配置失败 task=%s", task_id)

        lock = None
        if gpu_key:
            lock = self._gpu_locks.setdefault(gpu_key, asyncio.Lock())
            await lock.acquire()
        try:
            await asyncio.to_thread(self._run_task, task_id)
        except Exception:  # noqa: BLE001
            logger.exception("任务执行线程异常 task=%s", task_id)
        finally:
            if lock is not None:
                lock.release()
            self._semaphore.release()

    # ---------------------------------------------------------------- 执行

    def _run_task(self, task_id: int) -> None:
        with session_scope() as db:
            task = db.get(EvalTask, task_id)
            if task is None or task.status not in ("queued", "paused"):
                return

            task.status = "running"
            task.started_at = task.started_at or task_service.now_str()
            task.error_msg = ""
            config = json.loads(task.config_json or "{}")

            rows = db.execute(
                select(TaskEpisode, Episode)
                .join(Episode, Episode.id == TaskEpisode.episode_id)
                .where(TaskEpisode.task_id == task.id, TaskEpisode.status == "pending")
                .order_by(Episode.id)
            ).all()

            episodes = [
                {
                    "episode_key": episode.episode_id,
                    "scene_id": episode.scene_id,
                    "instruction": episode.instruction,
                    "traj_len": episode.traj_len,
                    "start_pose": json.loads(episode.start_pose_json or "[]"),
                }
                for _, episode in rows
            ]
            row_ids = {episode.episode_id: row.id for row, episode in rows}

            dataset = db.get(Dataset, task.dataset_id)
            model = db.get(ModelProfile, task.model_profile_id)
            dataset_info = {
                "id": dataset.id,
                "name": dataset.name,
                "root_path": dataset.root_path,
                "kind": dataset.kind,
            }
            model_info = model_service.to_dict(model) if model else {}

        if not episodes:
            self._finalize(task_id, error="没有待执行的 episode")
            return

        run_dir = task_service.task_run_dir(task_id)
        (run_dir / "config.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log_path = run_dir / "run.log"

        def append_log(text: str) -> None:
            stamp = datetime.now().strftime("%H:%M:%S")
            line = f"[{stamp}] {text}"
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            self._emit(task_id, "log", {"level": "info", "text": text})

        ctx = RunContext(
            task_id=task_id,
            task_name="",
            run_dir=run_dir,
            config=config,
            episodes=episodes,
            model=model_info,
            dataset=dataset_info,
            log=append_log,
            progress=lambda done, total, key: None,
            sample=lambda payload: None,
        )

        self._runtime[task_id] = {"ctx": ctx, "adapter": None}
        self._emit(task_id, "state", {"status": "running", "total": len(episodes)})
        append_log(f"开始执行，待评测 {len(episodes)} 条 episode")

        adapter: BaseAdapter | None = None
        processed = 0
        started = time.time()
        error: str | None = None

        try:
            adapter = build_adapter(ctx)
            self._runtime[task_id]["adapter"] = adapter
            adapter.prepare()

            allowed_keys = set(row_ids)
            for record in adapter.run():
                if ctx.should_cancel():
                    break

                if record.episode_key not in allowed_keys:
                    append_log(f"忽略切分外的结果：{record.episode_key}")
                    continue

                self._persist(task_id, row_ids[record.episode_key], record, run_dir, ctx)
                processed += 1
                self._emit(
                    task_id,
                    "progress",
                    {
                        "done": processed,
                        "total": len(episodes),
                        "episode": record.episode_key,
                        "success": record.success,
                        "spl": record.spl,
                    },
                )
                self._emit(
                    task_id,
                    "sample",
                    {
                        "step": processed,
                        "gpu_mem_mb": record.gpu_mem_peak_mb,
                        "latency_ms": record.latency_avg_ms,
                        "tokens": record.tokens_peak,
                        "ctx_len": record.ctx_len_peak,
                    },
                )

                if ctx.pause_event.is_set():
                    self._set_status(task_id, "paused")
                    self._emit(task_id, "state", {"status": "paused"})
                    append_log("任务已暂停，等待恢复")
                    while ctx.pause_event.is_set() and not ctx.should_cancel():
                        time.sleep(0.3)
                    if ctx.should_cancel():
                        break
                    self._set_status(task_id, "running")
                    self._emit(task_id, "state", {"status": "running"})
                    append_log("任务已恢复")

            adapter.finish()
        except Exception as exc:  # noqa: BLE001 - 需要把失败原因回传界面
            error = str(exc)
            logger.exception("任务执行失败 task=%s", task_id)
            append_log(f"执行失败：{error}")
        finally:
            if ctx.should_cancel() and adapter is not None:
                try:
                    adapter.stop()
                except Exception:  # noqa: BLE001 - 清理阶段忽略
                    logger.exception("终止适配器失败 task=%s", task_id)
            self._runtime.pop(task_id, None)

        if ctx.should_cancel():
            append_log("任务已取消")
            self._finalize(task_id, canceled=True)
        elif error:
            self._finalize(task_id, error=error)
        else:
            append_log(f"执行完成，共处理 {processed} 条，用时 {time.time() - started:.1f}s")
            self._finalize(task_id)

    def _persist(
        self,
        task_id: int,
        row_id: int,
        record: EpisodeRecord,
        run_dir: Path,
        ctx: RunContext,
    ) -> None:
        frames_path = ""
        if record.frames:
            directory = run_dir / "frames"
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / f"{record.episode_key}.jsonl"
            with target.open("w", encoding="utf-8") as handle:
                for frame in record.frames:
                    handle.write(json.dumps(frame, ensure_ascii=False) + "\n")
            frames_path = str(target)

        with session_scope() as db:
            db.execute(
                update(TaskEpisode)
                .where(TaskEpisode.id == row_id)
                .values(
                    status="success" if record.success else "failed",
                    success=1 if record.success else 0,
                    spl=record.spl,
                    ne=record.ne,
                    os=record.os,
                    ndtw=record.ndtw,
                    tl=record.tl,
                    steps=record.steps,
                    latency_avg_ms=record.latency_avg_ms,
                    latency_p95_ms=record.latency_p95_ms,
                    gpu_mem_peak_mb=record.gpu_mem_peak_mb,
                    tokens_peak=record.tokens_peak,
                    ctx_len_peak=record.ctx_len_peak,
                    failure_reason=record.failure_reason,
                    traj_path=frames_path,
                    updated_at=task_service.now_str(),
                )
            )
            task = db.get(EvalTask, task_id)
            progress = 0
            if task is not None:
                task.progress_done = (task.progress_done or 0) + 1
                progress = task.progress_done

            db.add(
                ResourceSample(
                    task_id=task_id,
                    ts=task_service.now_str(),
                    step=progress,
                    gpu_mem_mb=record.gpu_mem_peak_mb,
                    latency_ms=record.latency_avg_ms,
                    tokens=record.tokens_peak,
                    ctx_len=record.ctx_len_peak,
                )
            )

    def _finalize(self, task_id: int, error: str | None = None, canceled: bool = False) -> None:
        with session_scope() as db:
            task = db.get(EvalTask, task_id)
            if task is None:
                return
            metrics = task_service.aggregate_metrics(db, task)
            if canceled:
                task.status = "canceled"
            elif error:
                task.status = "failed"
                task.error_msg = error[:1000]
            else:
                task.status = "succeeded"
            task.finished_at = task_service.now_str()
            if task.started_at:
                try:
                    start = datetime.strptime(task.started_at, "%Y-%m-%d %H:%M:%S")
                    end = datetime.strptime(task.finished_at, "%Y-%m-%d %H:%M:%S")
                    task.duration_s = round((end - start).total_seconds(), 1)
                except ValueError:
                    task.duration_s = None

        self._emit(task_id, "state", {"status": task.status if task else ""})
        self._emit(task_id, "done", {"status": task.status if task else "", "metrics": metrics})
        logger.info("任务结束 task=%s status=%s metrics=%s", task_id, task.status if task else "-", metrics)

    def _set_status(self, task_id: int, status: str) -> None:
        with session_scope() as db:
            task = db.get(EvalTask, task_id)
            if task is not None:
                task.status = status

    @staticmethod
    def _emit(task_id: int, event: str, data: dict[str, Any]) -> None:
        BUS.publish_threadsafe(task_id, event, data)

    # ---------------------------------------------------------------- 控制

    def set_max_parallel(self, value: int) -> None:
        """运行期调整并发额度，新提交的任务立即使用新的信号量。"""
        limit = max(1, min(int(value), 8))
        self.settings.scheduler.max_parallel_tasks = limit
        self._semaphore = asyncio.Semaphore(limit)
        logger.info("并发额度已调整为 %s", limit)

    async def pause(self, task_id: int) -> str:
        runtime = self._runtime.get(task_id)
        if runtime is None:
            raise RuntimeError("任务当前未在运行，无法暂停")
        runtime["ctx"].pause_event.set()
        return "pausing"

    async def resume(self, task_id: int) -> str:
        runtime = self._runtime.get(task_id)
        if runtime is None:
            with session_scope() as db:
                task = task_service.get_task(db, task_id)
                if task.status != "paused":
                    raise RuntimeError("任务不在暂停状态")
                task.status = "queued"
            self.submit(task_id)
            return "queued"
        runtime["ctx"].pause_event.clear()
        return "running"

    async def cancel(self, task_id: int) -> str:
        with session_scope() as db:
            task = task_service.get_task(db, task_id)
            if task.status in task_service.TERMINAL_STATUS:
                return task.status

        runtime = self._runtime.get(task_id)
        if runtime is None:
            with session_scope() as db:
                task = task_service.get_task(db, task_id)
                task.status = "canceled"
                task.finished_at = task_service.now_str()
            self._emit(task_id, "state", {"status": "canceled"})
            return "canceled"

        runtime["ctx"].cancel_event.set()
        adapter = runtime.get("adapter")
        if adapter is not None:
            await asyncio.to_thread(adapter.stop)
        return "canceling"


_scheduler: Scheduler | None = None


def get_scheduler() -> Scheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler
