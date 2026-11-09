"""仿真会话：进程内单例，同一时刻只允许一个引擎线程。

生命周期：`start()` → 后台线程里建场景（loading，5–20 s）→ ready → `stop()`。
HTTP 层永远拿到即时快照，不会因为建场景而阻塞页面。
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import PolicyConfig, SimConfig, get_settings
from ...core.response import INTERNAL_ERROR, NOT_FOUND, PARAM_INVALID, AppError
from ...models import EvalTask, ModelProfile
from . import constants as C
from .engine import SimEngine
from .episode import SimSpec, spec_from_episode
from .policy import PolicyError, PolicyRuntime
from .recording import FrameRecorder, Mp4Export, idle_export_state

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


# ---- 会话录制落盘（docs/09 #10）------------------------------------------
RECORD_KEEP_SESSIONS = 5      # 只留最近 5 局的帧图与 mp4
STALL_WARN_S = 8.0            # 画面超过这么久没有新帧就在日志里报一次


def _records_root() -> Path:
    return get_settings().storage.work_dir / "sim"


def _prune_records(root: Path, keep_dir: Path) -> None:
    """清掉旧会话目录：一局 10 分钟的帧图 + mp4 就是几百 MB，攒着很快把盘吃满。"""
    try:
        dirs = [item for item in root.iterdir() if item.is_dir() and item != keep_dir]
    except OSError:
        return
    dirs.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    for stale in dirs[max(0, RECORD_KEEP_SESSIONS - 1):]:
        shutil.rmtree(stale, ignore_errors=True)
        logger.debug("清理旧录制目录 %s", stale)


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


def _ensure_gpu(gpu_id: int) -> int:
    """校验卡号存在；nvidia-smi 读不到（无卡/无驱动）时不拦，交给引擎报错。"""
    indices: list[int] = []
    for item in _gpu_items():
        try:
            indices.append(int(item.get("index")))
        except (TypeError, ValueError):
            continue
    if indices and int(gpu_id) not in indices:
        raise AppError(
            PARAM_INVALID,
            f"GPU{gpu_id} 不存在，可选：{', '.join(f'GPU{i}' for i in sorted(indices))}",
            http_status=400,
        )
    return int(gpu_id)


def _pick_gpu(preferred: int | None) -> int:
    """`preferred` 有值就用它；否则挑空闲显存最多的一张。"""
    if preferred is not None:
        return _ensure_gpu(int(preferred))
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
        self._policy_closing: PolicyRuntime | None = None   # 后台回收中的模型
        self._thread: threading.Thread | None = None
        self._spec: SimSpec | None = None
        self._session_id = ""
        self._recorder: FrameRecorder | None = None      # 当前会话的录制器
        self._last_record: dict | None = None            # 刚结束那局的录制信息（停会话后仍可导出）
        self._export: Mp4Export | None = None            # 最近一次 mp4 导出任务
        self._started_at = 0.0
        self._last_seen = time.time()
        # 画面停更检测（排查"卡死"用）：记一次时间点与一条告警，恢复后再复位
        self._last_frame_seq = -1
        self._stall_since = 0.0
        self._stall_warned = False
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
        target_gpu = _ensure_gpu(int(gpu_id) if gpu_id is not None else int(configured_ids[0]))

        session_id = uuid.uuid4().hex[:12]
        with self._guard:
            self._stop_locked(new_session=True)

            recorder = self._open_recorder(session_id, cfg)
            from .scene import resolve_robot_config

            engine = SimEngine(
                spec,
                gpu_id=target_gpu,
                tick_hz=cfg.tick_hz,
                render_hz=cfg.render_hz,
                stream_hz=cfg.stream_hz,
                jpeg_quality=cfg.jpeg_quality,
                pip=cfg.pip,
                recorder=recorder,
                robot=resolve_robot_config(cfg.robot_mesh),
                robot_scale=cfg.robot_scale,
                robot_yaw_deg=cfg.robot_yaw_deg,
            )
            engine.set_warning(_gpu_warning(target_gpu))
            thread = threading.Thread(target=engine.run, name=f"sim-engine-{spec.episode_id}", daemon=True)
            self._engine = engine
            self._thread = thread
            self._spec = spec
            self._recorder = recorder
            self._export = None
            self._last_record = None        # 新会话开始，上一局的录制不再作为导出源
            self._session_id = session_id
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
            "gpu_id": target_gpu,
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
                "geodesic": 0.0,
                "ne": 0.0,
                "shortest": 0.0,
                "spl": 0.0,
                "success": False,
                "oracle": False,
                "pip": False,
                "pip_available": False,
                "robot": False,
                "robot_available": False,
                "gpu_id": None,
                "clients": 0,
                "uptime_s": 0,
                "policy": policy,
                "recording": self.recording_state(),
            }
        snap = engine.snapshot()
        snap.update({
            "session_id": session_id,
            "episode": spec.as_dict(),
            "uptime_s": round(time.time() - self._started_at, 1),
            "policy": policy,
            "recording": self.recording_state(),
        })
        self._check_stall(snap)
        return snap

    def _check_stall(self, snap: dict) -> None:
        """画面停更超过 `STALL_WARN_S` 记一条告警，恢复时记一条 INFO。

        只是观测，不动引擎：真卡住时日志里至少有一个准确的时间点，
        而不是只有前端那句"画面已停止更新"。
        """
        if snap.get("status") != "ready":
            self._stall_since = 0.0
            self._stall_warned = False
            return
        seq = int(snap.get("frame_seq") or 0)
        now = time.time()
        if seq != self._last_frame_seq:
            if self._stall_since and now - self._stall_since >= STALL_WARN_S:
                logger.info("画面恢复更新，共停 %.1fs", now - self._stall_since)
            self._last_frame_seq = seq
            self._stall_since = 0.0
            self._stall_warned = False
            return
        if not self._stall_since:
            self._stall_since = now
            return
        gap = now - self._stall_since
        if gap >= STALL_WARN_S and not self._stall_warned:
            self._stall_warned = True
            logger.warning(
                "画面已 %.1fs 没有新帧：steps=%s fps=%s clients=%s，引擎线程可能卡在渲染里",
                gap, snap.get("steps"), snap.get("fps"), snap.get("clients"),
            )

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
        # 等下一帧回来再返回，操作更跟手；上限压到 0.3 s，引擎真卡住时请求也能及时放手
        engine.wait_frame(before, timeout=0.3)
        snap = engine.snapshot()
        return {
            "steps": snap["steps"],
            "distance": snap["distance"],
            "geodesic": snap["geodesic"],
            "spl": snap["spl"],
            "success": snap["success"],
            "oracle": snap["oracle"],
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

    def set_oracle(self, enabled: bool) -> dict:
        """开/关 oracle 驾驶。开的时候模型让位——两者都往同一队列塞动作，只能有一个在开。"""
        engine = self._engine
        if engine is None:
            raise AppError(PARAM_INVALID, "请先启动仿真会话，再跑 Oracle", http_status=400)
        if engine.status != "ready":
            raise AppError(PARAM_INVALID, "仿真未在运行，无法启动 Oracle 驾驶", http_status=409)
        if enabled and engine.snapshot().get("done"):
            raise AppError(PARAM_INVALID, "本局已结束，请先「回起点」再跑 Oracle", http_status=409)
        if not engine.request_oracle(enabled):
            raise AppError(PARAM_INVALID, "当前状态无法启动 Oracle 驾驶", http_status=409)
        if enabled:
            runtime = self._policy
            if runtime is not None and runtime.status in ("running", "ready"):
                runtime.pause("已切到 Oracle 驾驶")
        # 开关是丢给引擎线程处理的，等它真正生效再回包，前端按钮才不会"点了没反应"
        deadline = time.time() + 0.8
        while time.time() < deadline:
            if bool(engine.snapshot().get("oracle")) == bool(enabled):
                break
            time.sleep(0.03)
        return engine.snapshot()

    def set_pip(self, enabled: bool) -> dict:
        """开/关第三视角画中画；本局没建第二路相机时直接 409。"""
        engine = self._engine
        if engine is None:
            raise AppError(PARAM_INVALID, "请先启动仿真会话，再切换第三视角", http_status=400)
        if not engine.request_pip(bool(enabled)):
            raise AppError(
                PARAM_INVALID,
                "本局没有第三视角相机（sim.pip=false），需要重启会话",
                http_status=409,
            )
        # 命令丢给引擎线程处理，等它真正生效再回包，前端开关才不会"点了没反应"
        want = bool(enabled)
        deadline = time.time() + 0.8
        while time.time() < deadline:
            if bool(engine.snapshot().get("pip")) == want:
                break
            time.sleep(0.03)
        snap = engine.snapshot()
        return {"pip": bool(snap.get("pip")), "pip_available": bool(snap.get("pip_available"))}

    def set_robot(self, enabled: bool) -> dict:
        """显示/隐藏画中画里的机器狗；本局没加载模型时 409。"""
        engine = self._engine
        if engine is None:
            raise AppError(PARAM_INVALID, "请先启动仿真会话，再切换机器狗", http_status=400)
        if not engine.request_robot(bool(enabled)):
            raise AppError(
                PARAM_INVALID,
                "本局没有机器狗模型（sim.robot_mesh 为空或加载失败）",
                http_status=409,
            )
        want = bool(enabled)
        deadline = time.time() + 0.8
        while time.time() < deadline:
            if bool(engine.snapshot().get("robot")) == want:
                break
            time.sleep(0.03)
        snap = engine.snapshot()
        return {"robot": bool(snap.get("robot")), "robot_available": bool(snap.get("robot_available"))}

    # ---- 录制 / 导出 mp4（docs/09 #10）-------------------------------------
    def recording_state(self) -> dict:
        """当前这局（或刚结束那局）的录制进度 + 最近一次导出的状态。"""
        recorder = self._recorder
        if recorder is not None:
            info = recorder.snapshot()
            info["session_id"] = self._session_id
        elif self._last_record:
            info = {key: value for key, value in self._last_record.items() if key != "dir"}
        else:
            info = {
                "frames": 0, "seconds": 0.0, "fps": round(C.RECORD_FPS, 1),
                "dropped": 0, "max_frames": C.RECORD_MAX_FRAMES, "session_id": "",
            }
        export = self._export
        info["export"] = export.snapshot() if export is not None else idle_export_state()
        return info

    def export_video(self) -> dict:
        """把已落盘的帧异步编码成 mp4；重复点击复用同一个任务。"""
        directory, session_id, frames = self._frames_source()
        current = self._export
        if current is not None:
            snap = current.snapshot()
            if snap.get("status") == "encoding":
                return snap
            if snap.get("status") == "ready" and current.frames_dir == directory:
                return snap
        target = directory / f"sim-{session_id or 'session'}.mp4"
        export = Mp4Export(directory, target, fps=C.VIDEO_FPS)
        self._export = export
        logger.info("开始导出 mp4 session=%s 帧数=%s", session_id, frames)
        return export.start()

    def open_export(self) -> tuple[Path, str]:
        """导出完成的 mp4 路径；没导出完或文件丢了给中文错误。"""
        export = self._export
        if export is None or export.snapshot().get("status") != "ready":
            raise AppError(PARAM_INVALID, "mp4 还没有导出完成，请稍等", http_status=409)
        if not export.target.exists():
            raise AppError(NOT_FOUND, "mp4 文件已丢失，请重新导出", http_status=404)
        return export.target, export.target.name

    def _frames_source(self) -> tuple[Path, str, int]:
        """当前可导出的帧目录 → `(目录, session_id, 帧数)`。"""
        recorder = self._recorder
        if recorder is not None and recorder.frames > 0:
            return recorder.directory, self._session_id, recorder.frames
        last = self._last_record or {}
        directory = Path(last["dir"]) if last.get("dir") else None
        frames = int(last.get("frames") or 0)
        if directory is not None and frames > 0 and directory.exists():
            return directory, str(last.get("session_id") or ""), frames
        raise AppError(PARAM_INVALID, "还没有录到画面：先让仿真跑几秒再导出", http_status=400)

    def _open_recorder(self, session_id: str, cfg: SimConfig) -> FrameRecorder | None:
        """按配置开录制；目录不可用时只降级不报错（录制是附加能力）。"""
        if cfg.record_fps <= 0 or cfg.record_max_frames <= 0:
            return None
        directory = _records_root() / session_id
        try:
            directory.mkdir(parents=True, exist_ok=True)
            _prune_records(directory.parent, directory)
            return FrameRecorder(
                directory, fps=cfg.record_fps, max_frames=cfg.record_max_frames).start()
        except OSError:
            logger.warning("录制目录不可用，本局不落帧：%s", directory, exc_info=True)
            return None

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
        # 上一次 stop 是后台回收的，先等它把显存还回来，否则"刚停又开"会误判显存不足
        if not self._wait_policy_closed():
            logger.warning("上一份模型仍在释放，显存校验可能偏低")
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

    def _close_policy(self, *, async_reclaim: bool = True) -> None:
        """调用方必须已持有 `_guard`。

        释放 8.7 GB 权重要跑一次全量 `gc.collect()` + `empty_cache()`（实测 1–3 s），
        这段 GIL 被占住、画面会停顿几秒；所以默认丢到后台线程，让 HTTP 立刻返回，
        `start_policy` 再等它收尾（见 `_wait_policy_closed`）。
        """
        runtime, self._policy = self._policy, None
        if runtime is None:
            return
        if async_reclaim:
            # 上一份还在收就先等它落地，别把引用覆盖掉（否则 `_wait_policy_closed` 会提前放行）
            self._wait_policy_closed()
            self._policy_closing = runtime
            threading.Thread(target=self._reclaim, args=(runtime,),
                             name="policy-reclaim", daemon=True).start()
        else:
            self._reclaim(runtime)

    def _reclaim(self, runtime) -> None:
        try:
            runtime.close()
        except Exception:  # noqa: BLE001 关模型失败不能挡住会话停止
            logger.exception("关闭模型驾驶失败")
        finally:
            # 不拿 `_guard`：调用方（`_stop_locked`）可能正持着它，普通 Lock 不可重入
            if self._policy_closing is runtime:
                self._policy_closing = None

    def _wait_policy_closed(self, timeout: float = 8.0) -> bool:
        """等后台回收线程收完，避免"刚停又开"时撞上还没释放的显存。"""
        deadline = time.time() + timeout
        while self._policy_closing is not None and time.time() < deadline:
            time.sleep(0.1)
        return self._policy_closing is None

    def shutdown(self) -> None:
        self._shutdown.set()
        with self._guard:
            self._stop_locked(new_session=False)
        # 进程要退了，后台线程会被一起带走，这里同步等显存真正还回来
        self._wait_policy_closed()

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
        """只推 `frame_seq` 变化的新帧；多观众共享同一份 JPEG 字节。

        两个"别把名额占死"的细节（浏览器同域只有 6 条长连接）：
        - `touch_client` 只在**真的推出一帧**之后刷新心跳，客户端不再读就会自然过期；
        - 连续 `STREAM_IDLE_S` 没有新帧就主动断开，交给前端退避重连——
          否则"客户端已放弃、生成器还挂着"会把观看名额永久占死，新页面全部黑屏。
        """
        if engine is None or not ticket:
            return
        last_seq = -1
        last_push = time.time()
        try:
            while True:
                if await request.is_disconnected():
                    break
                if self._engine is not engine:
                    break
                data, seq = engine.latest_frame()
                if data is not None and seq != last_seq:
                    last_seq = seq
                    last_push = time.time()
                    engine.touch_client(ticket)
                    head = (
                        f"--{MJPEG_BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                        f"Content-Length: {len(data)}\r\n\r\n"
                    ).encode("ascii")
                    yield head + data + b"\r\n"
                else:
                    if time.time() - last_push > C.STREAM_IDLE_S:
                        logger.debug("观看连接 %s 超过 %.0fs 无新帧，主动断开",
                                     ticket, C.STREAM_IDLE_S)
                        break
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
        # 引擎线程退出前已经把录制队列写空，这里记一下，停会话之后仍能导出 mp4
        self._keep_recording(self._session_id)
        self._engine = None
        self._thread = None
        self._spec = None
        self._session_id = ""
        self._started_at = 0.0
        # 引擎没了，模型线程继续跑也只会空转，一并收掉（显存立即回落）
        self._close_policy()

    def _keep_recording(self, session_id: str) -> None:
        """把刚结束这局的录制信息留一份（含目录），供停止后再导出 mp4。"""
        recorder = self._recorder
        self._recorder = None
        if recorder is None:
            return
        if recorder.frames <= 0:
            return
        info = recorder.snapshot()
        info["dir"] = str(recorder.directory)
        info["session_id"] = session_id
        self._last_record = info

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
