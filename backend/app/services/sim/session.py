"""仿真会话：进程内单例，同一时刻只允许一个引擎线程。

生命周期：`start()` → 后台线程里建场景（loading，5–20 s）→ ready → `stop()`。
HTTP 层永远拿到即时快照，不会因为建场景而阻塞页面。
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import threading
import time
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import PolicyConfig, SimConfig, get_settings
from ...core.response import INTERNAL_ERROR, NOT_FOUND, PARAM_INVALID, AppError
from ...models import EvalTask, ModelProfile
from . import constants as C
from .engine import SimEngine
from .episode import SimSpec, spec_from_episode
from .policy import PolicyError, PolicyRuntime

logger = logging.getLogger(__name__)

MJPEG_BOUNDARY = "frame"


def _sim_cfg() -> SimConfig:
    return get_settings().sim


def _policy_cfg() -> PolicyConfig:
    return get_settings().policy


def _gpu_items() -> list[dict]:
    """读一次 nvidia-smi（复用系统页的解析逻辑，延迟导入避免模块加载顺序问题）。"""
    try:
        from ...api.system import _gpu_info

        return list((_gpu_info() or {}).get("items") or [])
    except Exception:  # noqa: BLE001 拿不到 GPU 信息不影响仿真
        logger.debug("读取 GPU 信息失败", exc_info=True)
        return []


def _gpu_warning(gpu_id: int) -> str | None:
    """显存低于阈值时给一条中文提醒；只提醒，不阻止启动（用户已定）。"""
    threshold = float(_sim_cfg().free_mem_warn_mb or C.FREE_MEM_WARN_MB)
    for item in _gpu_items():
        try:
            if int(item.get("index", -1)) != int(gpu_id):
                continue
            total = float(item.get("memory_total_mb") or 0)
            used = float(item.get("memory_used_mb") or 0)
        except (TypeError, ValueError):
            continue
        free = max(0.0, total - used)
        if total and free < threshold:
            return (f"GPU{gpu_id} 剩余显存仅 {free / 1024:.1f} GB"
                    f"（阈值 {threshold / 1024:.1f} GB），仿真可能与其他任务争抢显存")
        return None
    return None


def _habitat_available() -> bool:
    """只探测模块是否存在，不真的 import 原生扩展。"""
    return importlib.util.find_spec("habitat_sim") is not None


# ---- 模型驾驶：显存校验 / 档案解析 ---------------------------------------
def _gpu_free_mb(gpu_id: int) -> int | None:
    for item in _gpu_items():
        try:
            if int(item.get("index", -1)) != int(gpu_id):
                continue
            total = float(item.get("memory_total_mb") or 0)
            used = float(item.get("memory_used_mb") or 0)
        except (TypeError, ValueError):
            continue
        return int(max(0.0, total - used))
    return None


def _pick_gpu(preferred: int | None) -> int:
    """`preferred` 有值就用它；否则挑空闲显存最多的一张。"""
    if preferred is not None:
        return int(preferred)
    items = _gpu_items()
    best, best_free = 0, -1.0
    for item in items:
        try:
            index = int(item.get("index", 0))
            free = float(item.get("memory_total_mb") or 0) - float(item.get("memory_used_mb") or 0)
        except (TypeError, ValueError):
            continue
        if free > best_free:
            best, best_free = index, free
    return best


def _busy_task_names(db: Session, gpu_id: int) -> list[str]:
    """正在跑、且占着这张卡的任务名（只用于提示，不阻止启动）。"""
    rows = db.scalars(select(EvalTask).where(EvalTask.status == "running")).all()
    hits: list[str] = []
    for row in rows:
        used = [p.strip() for p in str(row.gpu_ids or "").split(",") if p.strip()]
        if str(gpu_id) in used:
            hits.append(row.name or f"#{row.id}")
    return hits


def _resolve_profile(db: Session, model_id: int | None, name: str = "") -> ModelProfile:
    if model_id is not None:
        profile = db.get(ModelProfile, int(model_id))
        if profile is None:
            raise AppError(NOT_FOUND, f"模型档案不存在：{model_id}", http_status=404)
        if (profile.family or "") != "streamvln":
            raise AppError(
                PARAM_INVALID,
                f"模型「{profile.name}」不是 StreamVLN 系列（family={profile.family}），"
                "暂不支持交互式推理",
                http_status=400,
            )
        return profile
    stmt = select(ModelProfile).order_by(ModelProfile.id)
    if name:
        stmt = stmt.where(ModelProfile.name == name)
    for profile in db.scalars(stmt).all():
        if (profile.family or "") == "streamvln":
            return profile
    raise AppError(
        PARAM_INVALID,
        "没有可用的 StreamVLN 模型档案，请先在「模型」页登记（family=streamvln）",
        http_status=400,
    )


class SimSession:
    def __init__(self) -> None:
        self._engine: SimEngine | None = None
        self._policy: PolicyRuntime | None = None
        self._thread: threading.Thread | None = None
        self._spec: SimSpec | None = None
        self._session_id = ""
        self._started_at = 0.0
        self._last_seen = time.time()
        self._shutdown = threading.Event()
        self._guard = threading.Lock()
        self._watchdog = threading.Thread(target=self._watch, name="sim-idle-watch", daemon=True)
        self._watchdog.start()

    # ---- 会话生命周期 -----------------------------------------------------
    def start(self, db: Session, episode_id: int, gpu_id: int | None = None) -> dict:
        if not _habitat_available():
            raise AppError(
                INTERNAL_ERROR,
                "仿真组件不可用：当前 Python 环境未安装 habitat_sim 0.2.4。"
                "请用 streamvln-kb 环境启动平台（/home/zjr/miniconda3/envs/streamvln-kb/bin/python run.py）。",
                http_status=500,
            )
        spec = spec_from_episode(db, episode_id)

        cfg = _sim_cfg()
        configured_ids = cfg.gpu_ids or [0]
        target_gpu = int(gpu_id) if gpu_id is not None else configured_ids[0]

        with self._guard:
            self._stop_locked(new_session=True)

            engine = SimEngine(
                spec,
                gpu_id=target_gpu,
                tick_hz=cfg.tick_hz,
                render_hz=cfg.render_hz,
                stream_hz=cfg.stream_hz,
                jpeg_quality=cfg.jpeg_quality,
            )
            engine.set_warning(_gpu_warning(target_gpu))
            thread = threading.Thread(target=engine.run, name=f"sim-engine-{spec.episode_id}", daemon=True)
            self._engine = engine
            self._thread = thread
            self._spec = spec
            self._session_id = uuid.uuid4().hex[:12]
            self._started_at = time.time()
            self._last_seen = time.time()
            thread.start()

        logger.info(
            "创建仿真会话 session=%s episode=%s 场景=%s gpu=%s",
            self._session_id, spec.episode_id, spec.scene_label, target_gpu,
        )
        return {
            "session_id": self._session_id,
            "status": "loading",
            "episode": spec.as_dict(),
            "warning": engine.snapshot().get("warning"),
        }

    def state(self) -> dict:
        self._last_seen = time.time()
        engine, spec, session_id = self._engine, self._spec, self._session_id
        policy = self._policy_snapshot()
        if engine is None or spec is None:
            return {
                "status": "idle",
                "session_id": "",
                "episode": None,
                "steps": 0,
                "distance": 0.0,
                "done": False,
                "pose": {"x": 0.0, "z": 0.0, "yaw_deg": 0.0},
                "trail": [],
                "warning": None,
                "frame_seq": 0,
                "pending": 0,
                "last_action_source": "manual",
                "uptime_s": 0,
                "policy": policy,
            }
        snap = engine.snapshot()
        snap.update({
            "session_id": session_id,
            "episode": spec.as_dict(),
            "uptime_s": round(time.time() - self._started_at, 1),
            "policy": policy,
        })
        return snap

    def _policy_snapshot(self) -> dict:
        """没有模型时给一份"关闭"快照，前端不必判空。"""
        policy = self._policy
        if policy is None:
            return {
                "status": "off", "model": "", "gpu_id": None, "paused": False,
                "message": "", "last_latency_ms": 0, "avg_latency_ms": 0,
                "infer_count": 0, "actions_done": 0, "inferring_s": 0.0,
                "load_seconds": 0.0,
            }
        return policy.snapshot()

    def act(self, action: str) -> dict:
        self._last_seen = time.time()
        engine, spec = self._engine, self._spec
        if engine is None or spec is None:
            raise AppError(PARAM_INVALID, "当前没有运行中的仿真会话，请先启动仿真", http_status=400)
        status = engine.status
        if status == "loading":
            raise AppError(PARAM_INVALID, "场景还在加载中，请稍候再操作", http_status=409)
        if status == "error":
            raise AppError(PARAM_INVALID, engine.snapshot().get("message") or "仿真出错，请重新启动", http_status=409)
        if status != "ready":
            raise AppError(PARAM_INVALID, "仿真已停止，请重新启动会话", http_status=409)

        before = engine.snapshot()["frame_seq"]
        if not engine.request_action(action):
            raise AppError(PARAM_INVALID, f"不支持的动作：{action}", http_status=400)
        self._on_manual(action)                    # 人接管 → 模型让位（docs/08 D6）
        engine.wait_frame(before, timeout=0.6)     # 让反馈带上前一帧的结果，操作更跟手
        snap = engine.snapshot()
        return {
            "steps": snap["steps"],
            "distance": snap["distance"],
            "done": snap["done"],
            "status": snap["status"],
            "message": snap["message"],
            "frame_seq": snap["frame_seq"],
        }

    def stop(self, session_id: str | None = None) -> dict:
        with self._guard:
            # "current" 表示「不关心 id，停掉现有会话」（前端切页/兜底时用）
            if session_id and session_id != "current" and self._session_id and session_id != self._session_id:
                raise AppError(NOT_FOUND, "会话不存在或已结束", http_status=404)
            had = self._engine is not None
            self._stop_locked(new_session=False)
        return {"status": "stopped", "session_id": "", "stopped": bool(had)}

    # ---- 模型驾驶（docs/08 §6）--------------------------------------------
    def start_policy(self, db: Session, model_id: int | None = None,
                     gpu_id: int | None = None) -> dict:
        """启用模型驾驶：立即返回 `loading`，加载在推理线程里做（13 s 左右）。"""
        cfg = _policy_cfg()
        if not cfg.enabled:
            raise AppError(PARAM_INVALID, "模型驾驶已在配置中关闭（policy.enabled=false）",
                           http_status=400)
        engine = self._engine
        if engine is None:
            raise AppError(PARAM_INVALID, "请先启动仿真会话，再启用模型驾驶", http_status=400)
        status = engine.status
        if status == "loading":
            raise AppError(PARAM_INVALID, "场景还在加载中，请就绪后再启用模型", http_status=409)
        if status != "ready":
            raise AppError(PARAM_INVALID, "仿真未在运行，无法启用模型驾驶", http_status=409)

        profile = _resolve_profile(db, model_id, cfg.model_profile)
        target = _pick_gpu(cfg.gpu_id if gpu_id is None else gpu_id)
        need = int(cfg.min_free_mem_mb or 0)
        free = _gpu_free_mb(target)
        if free is not None and need and free < need:
            raise AppError(
                PARAM_INVALID,
                f"GPU{target} 剩余显存 {free / 1024:.1f} GB，低于模型驾驶所需的 {need / 1024:.1f} GB"
                "（8bit 权重实测 8.7 GB，另需 KV/激活余量）。请先释放显存，或换一张空闲的卡。",
                http_status=400,
            )

        runtime = PolicyRuntime(
            engine=engine,
            model_name=profile.name,
            code_path=profile.code_path or "",
            weights_path=profile.weights_path or "",
            gpu_id=target,
            num_frames=cfg.num_frames,
            num_history=cfg.num_history,
            num_future_steps=cfg.num_future_steps,
            infer_timeout_s=cfg.infer_timeout_s,
            habitat_config=os.path.join(profile.code_path or "", "config", "vln_r2r.yaml"),
        )
        busy = _busy_task_names(db, target)
        with self._guard:
            self._close_policy()               # 上一份残留（off/error）先收掉
            self._policy = runtime
        runtime.start()
        logger.info("启用模型驾驶 model=%s gpu=%s free=%sMB", profile.name, target, free)
        return {
            "status": runtime.status,
            "policy": runtime.snapshot(),
            "warning": (f"GPU{target} 上还有评测任务在跑（{'、'.join(busy)}），"
                        f"可能与模型争抢显存" if busy else None),
        }

    def stop_policy(self) -> dict:
        with self._guard:
            had = self._policy is not None
            self._close_policy()
        return {"status": "off", "stopped": bool(had)}

    def set_policy_paused(self, paused: bool) -> dict:
        runtime = self._policy
        if runtime is None:
            raise AppError(PARAM_INVALID, "模型驾驶未启用", http_status=400)
        if paused:
            runtime.pause("用户暂停模型驾驶")
            self._engine_pending_clear()
        else:
            if runtime.status == "error":
                raise AppError(
                    PARAM_INVALID,
                    f"模型已出错，请先停止后重新启用：{runtime.snapshot().get('message')}",
                    http_status=409,
                )
            if runtime.status == "off":
                raise AppError(PARAM_INVALID, "模型驾驶已停止，请重新启用", http_status=409)
            runtime.resume()
        return {"status": runtime.status, "policy": runtime.snapshot()}

    def _on_manual(self, action: str) -> None:
        """人在驾驶 → 模型暂停（队列已由引擎清空，KV 由推理线程复位）。"""
        runtime = self._policy
        if runtime is None:
            return
        if runtime.status in ("running", "ready"):
            runtime.pause("已复位，模型暂停" if action == C.ACTION_RESET else "已接管，模型暂停")

    def _engine_pending_clear(self) -> None:
        engine = self._engine
        if engine is not None:
            engine.clear_pending()

    def _close_policy(self) -> None:
        """调用方必须已持有 `_guard`。"""
        runtime, self._policy = self._policy, None
        if runtime is None:
            return
        try:
            runtime.close()
        except Exception:  # noqa: BLE001 关模型失败不能挡住会话停止
            logger.exception("关闭模型驾驶失败")

    def shutdown(self) -> None:
        self._shutdown.set()
        with self._guard:
            self._stop_locked(new_session=False)

    # ---- MJPEG ------------------------------------------------------------
    def open_stream(self) -> tuple[object, str] | None:
        """在返回 StreamingResponse **之前**占一个观看名额，超限时由路由层回 429。

        放在生成器里查会有两个问题：响应头已经发出去，没法再改状态码；
        而生成器被取消时计数也不保证回收。
        """
        engine = self._engine
        if engine is None:
            return None
        limit = int(_sim_cfg().max_clients or C.MAX_CLIENTS)
        ticket = engine.try_add_client(limit)
        if ticket is None:
            raise AppError(
                PARAM_INVALID,
                f"同时观看人数已达上限（{limit}），请关闭其他页面后重试",
                http_status=429,
            )
        return engine, ticket

    async def iter_mjpeg(self, request, engine=None, ticket: str = ""):
        """只推 `frame_seq` 变化的新帧；多观众共享同一份 JPEG 字节。"""
        if engine is None or not ticket:
            return
        last_seq = -1
        try:
            while True:
                if await request.is_disconnected():
                    break
                if self._engine is not engine:
                    break
                engine.touch_client(ticket)
                data, seq = engine.latest_frame()
                if data is not None and seq != last_seq:
                    last_seq = seq
                    head = (
                        f"--{MJPEG_BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                        f"Content-Length: {len(data)}\r\n\r\n"
                    ).encode("ascii")
                    yield head + data + b"\r\n"
                else:
                    await asyncio.sleep(0.01)
                if engine.status in ("error", "stopped"):
                    break
        finally:
            engine.remove_client(ticket)

    # ---- 内部 -------------------------------------------------------------
    def _stop_locked(self, *, new_session: bool) -> None:
        engine, thread = self._engine, self._thread
        if engine is None:
            return
        status = engine.status
        if status == "loading" and new_session:
            # 场景正在建：新旧两个 Simulator 抢同一个 GL context 会直接崩，直接拒绝更安全
            raise AppError(
                PARAM_INVALID,
                "上一个会话仍在加载场景，请等待它就绪后再切换，或先点「停止仿真」",
                http_status=409,
            )
        engine.request_stop()
        if thread is not None and thread.is_alive():
            thread.join(timeout=8.0)
            if thread.is_alive():
                logger.warning("仿真线程未在 8s 内退出，可能仍持有 GL context，session=%s", self._session_id)
        self._engine = None
        self._thread = None
        self._spec = None
        self._session_id = ""
        self._started_at = 0.0
        # 引擎没了，模型线程继续跑也只会空转，一并收掉（显存立即回落）
        self._close_policy()

    def _watch(self) -> None:
        """空闲超时兜底：页面关掉后别让仿真长期占卡。"""
        while not self._shutdown.wait(30.0):
            engine = self._engine
            if engine is None:
                continue
            timeout = float(_sim_cfg().idle_timeout_s or 0)
            if timeout <= 0:
                continue
            if time.time() - self._last_seen <= timeout:
                continue
            logger.info("仿真会话空闲超过 %.0fs，自动停止", timeout)
            try:
                self.stop()
            except Exception:  # noqa: BLE001 兜底线程不能再抛
                logger.exception("空闲自动停止失败")


sim_session = SimSession()

__all__ = ["SimSession", "sim_session"]
