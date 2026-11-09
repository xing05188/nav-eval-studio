"""仿真引擎：独占 habitat_sim 的单个线程。

线程边界（见 docs/07 §3.1）：
- HTTP 线程只做三件事：往 `_cmd` 丢命令、读 `snapshot()`、取最新 JPEG 字节；
- 本线程独占 `sim` 的全部调用（渲染 / 动作 / 复位 / 关闭），因此不需要给 habitat 加锁。

设计取向是「异常绝不逃逸」：任何失败都收敛成 `status="error"` + 中文文案，
让 Web 层能把原因翻译给用户，而不是 500 或者整个服务挂掉。
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import constants as C
from .episode import SimSpec

logger = logging.getLogger(__name__)


def _quat_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """四元数乘法，格式统一为 [x, y, z, w]（habitat 的约定）。"""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ])


@dataclass
class Book:
    """单局账本。

    `distance` 是**欧氏**直线（与 habitat `distance_to_goal` 同口径，也是 6.57 m 基线的口径）；
    `geodesic` 是 navmesh 上的**测地**距离，NE / SPL 必须用这个，否则穿墙时会给出乐观读数。
    """

    steps: int = 0
    distance: float = 0.0
    geodesic: float = 0.0
    shortest: float = 0.0        # SPL 分母：官方 geodesic_distance，缺失则现算
    spl: float = 0.0
    success: bool = False
    done: bool = False
    stop_called: bool = False
    path_length: float = 0.0
    trail: list = field(default_factory=list)


class SimEngine:
    def __init__(
        self,
        spec: SimSpec,
        *,
        gpu_id: int = 0,
        tick_hz: float = 4.0,
        render_hz: float = C.RENDER_HZ,
        stream_hz: float = C.STREAM_HZ,
        jpeg_quality: int = C.JPEG_QUALITY,
        pip: bool = True,
        recorder=None,
        robot: str | None = None,
        robot_scale: float = 1.0,
        robot_yaw_deg: float = 0.0,
    ) -> None:
        self.spec = spec
        self.gpu_id = int(gpu_id)
        self.tick = 1.0 / max(1.0, float(tick_hz))
        self.render_period = 1.0 / max(1.0, float(render_hz))
        self.stream_period = 1.0 / max(1.0, float(stream_hz))
        self.jpeg_quality = int(jpeg_quality)

        # 第三视角（docs/09 #9）：`_pip` 只控制画中画叠不叠，传感器在 `pip=True` 时已经建好，
        # 所以运行中开关不省渲染开销——省开销要在配置里关掉（`sim.pip: false`）。
        self._pip = bool(pip)
        self._pip_available = False
        # 录制落盘（docs/09 #10）：由会话创建好后交进来，只调用 `push(jpeg)`
        self.recorder = recorder

        # 机器狗（docs/09 #9 延伸）：静态网格跟着 agent 位姿摆，不参与物理。
        # `_robot_on` 只控制显示；隐藏是把模型挪到地平线以下（引擎没暴露 visible 开关）。
        self._robot_cfg = robot
        self._robot_scale = float(robot_scale)
        self._robot_yaw = float(robot_yaw_deg)
        self._robot = None
        self._robot_on = True

        self.sim = None
        self.agent = None
        self.mapper = None

        self.book = Book()
        self.gait = 0.0
        self._last_pos: np.ndarray | None = None
        self._warn: str | None = None

        self._lock = threading.Condition()
        self._status = "loading"
        self._message = "正在加载场景…"
        self._latest_jpeg: bytes | None = None
        self._head_rgb: np.ndarray | None = None
        self._frame_seq = 0
        self._clients: dict[str, float] = {}
        self._pose = {"x": float(spec.start_position[0]),
                      "z": float(spec.start_position[2]), "yaw_deg": 0.0}
        self._trail_snap: list[list[float]] = []
        self._fps = 0.0
        self._frame_times: deque[float] = deque(maxlen=120)

        self._cmd: queue.Queue = queue.Queue()
        self._stop_flag = threading.Event()
        self._force_render = True

        # 模型动作队列：推理线程放、引擎线程按 4 Hz 取（见 docs/08 §5）
        self._pending: deque[str] = deque()
        self._next_tick = 0.0
        self._last_source = "manual"

        # oracle 驾驶：沿 navmesh 最短路径自动走，复用同一套 4 Hz 节拍
        self._oracle = False
        self._oracle_static: list | None = None
        self._geo_broken = False      # pathfinder 不可用后不再每步重试
        self._unreachable = False     # 目标跨岛时只警告一次

    # ---- 以下方法由 HTTP 线程调用 -----------------------------------------
    def set_warning(self, warning: str | None) -> None:
        with self._lock:
            self._warn = warning

    def try_add_client(self, limit: int) -> str | None:
        """登记一个观看者。

        满了**踢最老的**而不是拒绝：MJPEG 长连接被浏览器取消时，服务端未必立刻感知，
        老实拒绝会让用户刷新几次之后永久拿到 429（页面黑屏、没有任何提示）。
        新连接永远能进来，最坏情况是某个僵尸体被挤掉。
        """
        with self._lock:
            self._prune_clients()
            if limit and len(self._clients) >= limit:
                oldest = min(self._clients.items(), key=lambda kv: kv[1])[0]
                self._clients.pop(oldest, None)
                logger.debug("观看人数已满，挤掉最老的连接 %s", oldest)
            ticket = uuid.uuid4().hex[:8]
            self._clients[ticket] = time.time()
            return ticket

    def touch_client(self, ticket: str) -> None:
        with self._lock:
            if ticket in self._clients:
                self._clients[ticket] = time.time()

    def remove_client(self, ticket: str) -> None:
        with self._lock:
            self._clients.pop(ticket, None)

    def _prune_clients(self) -> None:
        """浏览器直接关标签页时 finally 不一定跑，超过 60 s 没心跳的连接按僵尸清掉。"""
        now = time.time()
        for key, seen in list(self._clients.items()):
            if now - seen > C.CLIENT_STALE_S:
                self._clients.pop(key, None)
                logger.debug("清理僵尸观看连接 %s", key)

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    @property
    def clients(self) -> int:
        with self._lock:
            self._prune_clients()
            return len(self._clients)

    def request_action(self, action: str) -> bool:
        """投递一个动作；返回是否被接受（loading/error/已停止时拒绝）。"""
        with self._lock:
            if self._status != "ready":
                return False
        if action == C.ACTION_RESET:
            self._cmd.put(("reset", None))
            return True
        code = C.ACTION_CODES.get(action)
        if code is None:
            return False
        # 手动优先级最高：先作废模型排队的动作，避免"按了还在往前走"
        self.clear_pending()
        self._oracle = False              # 人一按方向键就退出 oracle 驾驶
        with self._lock:
            self._last_source = "manual"
        self._cmd.put(("act", code))
        return True

    # ---- 模型动作队列（推理线程调用）--------------------------------------
    def submit_model_actions(self, actions: list[str]) -> int:
        """把模型产出的一批动作入队，返回实际入队数量。

        队列超过 `PENDING_MAX` 时丢最旧的：宁可少走两步，也不要让人接管后
        还要等队列排空。局部结束后不再收，避免读数在"已结束"之后继续漂。
        """
        with self._lock:
            if self._status != "ready" or self.book.done:
                return 0
            accepted = 0
            for name in actions:
                if name not in C.ACTION_CODES:
                    continue
                while len(self._pending) >= C.PENDING_MAX:
                    self._pending.popleft()
                self._pending.append(name)
                accepted += 1
            if accepted:
                self._last_source = "model"
            # 溢出的部分被丢掉了，返回的是真正留在队列里的数量
            return min(accepted, len(self._pending))

    def clear_pending(self) -> int:
        """清空模型动作队列，返回丢弃的数量。"""
        with self._lock:
            dropped = len(self._pending)
            self._pending.clear()
            return dropped

    # ---- oracle 驾驶（沿 navmesh 最短路径自动走）---------------------------
    def request_oracle(self, enabled: bool) -> bool:
        """开/关 oracle 驾驶；返回是否被接受（未就绪或已结束时拒绝开启）。"""
        if enabled:
            with self._lock:
                if self._status != "ready" or self.book.done:
                    return False
            self.clear_pending()          # oracle 与模型不能同时往队列里塞动作
        self._cmd.put(("oracle", bool(enabled)))
        return True

    def _set_oracle(self, enabled: bool) -> None:
        """只在引擎线程里调用。"""
        if enabled and self.book.done:
            enabled = False
        self._oracle = enabled
        self._next_tick = 0.0
        if enabled:
            self.clear_pending()
        with self._lock:
            if enabled:
                self._last_source = "oracle"
                self._message = "Oracle 驾驶中：沿最短路径朝目标走，按任意方向键即可接管"
            elif self._last_source == "oracle" and not self.book.done:
                self._last_source = "manual"
                self._message = "已退出 Oracle 驾驶"

    def _oracle_path_from(self, pos) -> list[list[float]]:
        """从 `pos` 到目标的最短路径点列（世界坐标）；不可达返回空。"""
        points, _distance = self._shortest_path(pos)
        return points

    def _oracle_static_path(self) -> list[list[float]]:
        """俯视图用的那条参考线：开局位置到目标，算一次缓存住。"""
        if self._oracle_static is None:
            base = self._last_pos if self._last_pos is not None else self.spec.start_position
            self._oracle_static = self._oracle_path_from(base)
        return self._oracle_static

    def _oracle_step(self) -> bool:
        """走一步 oracle；返回是否执行了动作。"""
        if self.book.done:
            self._oracle = False
            return False
        act = self._oracle_action()
        if act == C.ACT_STOP:
            self._oracle = False
            self._apply(act)              # 交给 _apply 统一写"已停止"文案与 done
            return True
        with self._lock:
            self._last_source = "oracle"
        self._apply(act)
        return True

    def _oracle_action(self) -> int:
        """贪心跟随：先对准路径点，对准了才前进——正好是离散动作空间（15°/0.25 m）。

        habitat 官方的 `ShortestPathFollower` 要 `Env.get_agent_state()`，我们只有
        `Simulator`，且它内部用 25° 转向，与这里的 15° 对不上，所以按同样思路自己走。
        """
        pos = np.asarray(self.agent.get_state().position, dtype=np.float64)
        goal = np.asarray(self.spec.goal, dtype=np.float64)
        if float(np.linalg.norm(pos[[0, 2]] - goal[[0, 2]])) <= max(self.spec.radius * 0.5, 0.3):
            return C.ACT_STOP
        path = self._oracle_path_from(pos)
        if len(path) < 2:
            return C.ACT_STOP
        target = None
        for point in path:
            dx = float(point[0]) - float(pos[0])
            dz = float(point[2]) - float(pos[2])
            if (dx * dx + dz * dz) ** 0.5 > C.FORWARD_STEP * 1.2:
                target = (dx, dz)
                break
        if target is None:
            return C.ACT_STOP
        dx, dz = target
        # 前方向量 = (-sinθ, -cosθ)（实测：yaw=150° 前进时 Δx=-0.125, Δz=+0.217）
        bearing = math.atan2(-dx, -dz)
        diff = (bearing - self._yaw() + math.pi) % (2 * math.pi) - math.pi
        if abs(diff) > math.radians(C.TURN_DEG * 0.55):
            return C.ACT_LEFT if diff > 0 else C.ACT_RIGHT
        return C.ACT_FORWARD

    def request_pip(self, enabled: bool) -> bool:
        """开/关画中画；没有第二路相机时返回 False（配置里 sim.pip=false）。"""
        if not self._pip_available:
            return False
        self._cmd.put(("pip", bool(enabled)))
        return True

    def _set_pip(self, enabled: bool) -> None:
        """只在引擎线程里调用。"""
        self._pip = bool(enabled) and self._pip_available

    def request_robot(self, enabled: bool) -> bool:
        """显示/隐藏机器狗；这局没加载模型时返回 False。"""
        if self._robot is None:
            return False
        self._cmd.put(("robot", bool(enabled)))
        return True

    def _set_robot(self, enabled: bool) -> None:
        """只在引擎线程里调用。"""
        self._robot_on = bool(enabled)
        self._sync_robot()

    def _sync_robot(self) -> None:
        """把狗摆到 agent 位姿（隐藏时挪到地平线以下）。

        静态网格是刚性的：狗与 agent 之间没有相对运动，所以每帧抄一次位姿就够，
        不用做插值，也不参与物理。
        """
        if self._robot is None:
            return
        from _magnum import Quaternion, Vector3
        from habitat_sim.utils import common as sim_utils

        state = self.agent.get_state()
        x, y, z = (float(v) for v in state.position)
        if not self._robot_on:
            y = C.ROBOT_HIDDEN_Y
        self._robot.translation = Vector3(x, y, z)

        rot = state.rotation
        if hasattr(rot, "x"):            # np.quaternion
            quat = np.array([rot.x, rot.y, rot.z, rot.w], dtype=np.float64)
        else:
            quat = np.asarray(rot, dtype=np.float64).reshape(4)
        if abs(self._robot_yaw) > 1e-3:
            half = math.radians(self._robot_yaw) / 2.0
            quat = _quat_mul(np.array([0.0, math.sin(half), 0.0, math.cos(half)]), quat)
        self._robot.rotation = Quaternion(Vector3(*quat[:3]), float(quat[3]))

    def request_stop(self) -> None:
        self._stop_flag.set()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "status": self._status,
                "message": self._message,
                "warning": self._warn,
                "gpu_id": self.gpu_id,
                "steps": self.book.steps,
                # 保留 4 位：前端按 2 位展示，读数才能与旧 CLI 基线（6.57 m）逐位对上
                "distance": round(self.book.distance, 4),
                "done": self.book.done,
                "pose": dict(self._pose),
                "trail": [list(p) for p in self._trail_snap],
                "frame_seq": self._frame_seq,
                "radius": self.spec.radius,
                "fps": round(self._fps, 1),
                # 当前挂在 MJPEG 上的观看连接数：排查"连接被占满"时看这个，不用猜
                "clients": len(self._clients),
                # 模型驾驶相关：前端用它显示"队列水位"和动作来源
                "pending": len(self._pending),
                "last_action_source": self._last_source,
                # 导航指标：distance 欧氏（对齐 habitat 口径），geodesic/ne/spl 走 navmesh
                "geodesic": round(self.book.geodesic, 4),
                "ne": round(self.book.geodesic, 4),
                "shortest": round(self.book.shortest, 4),
                "spl": round(self.book.spl, 4),
                "success": bool(self.book.success),
                "oracle": bool(self._oracle),
                # 第三视角：`pip` 是当前是否在叠画中画，`pip_available` 表示这局有没有建第二路相机
                "pip": bool(self._pip),
                "pip_available": bool(self._pip_available),
                "robot": bool(self._robot is not None and self._robot_on),
                "robot_available": self._robot is not None,
            }

    def wait_frame(self, after_seq: int, timeout: float = 0.4) -> tuple[bytes | None, int]:
        """等 `frame_seq > after_seq`；超时返回当前帧（调用方自行判断新旧）。"""
        deadline = time.time() + timeout
        with self._lock:
            while self._frame_seq <= after_seq and self._status in ("loading", "ready"):
                remain = deadline - time.time()
                if remain <= 0:
                    break
                self._lock.wait(remain)
            return self._latest_jpeg, self._frame_seq

    def latest_frame(self) -> tuple[bytes | None, int]:
        with self._lock:
            return self._latest_jpeg, self._frame_seq

    def latest_rgb(self) -> tuple[np.ndarray | None, int]:
        """最新一帧第一视角 RGB（uint8，640×480×3），给模型吃。

        注意与 `latest_frame()` 的区别：后者是"头视角 + 俯视图"拼好的 JPEG（1120 宽），
        直接喂模型会和评测输入尺寸不一致，所以单独留一份原始头视角。
        """
        with self._lock:
            return self._head_rgb, self._frame_seq

    # ---- 以下方法只在引擎线程执行 -----------------------------------------
    def run(self) -> None:
        try:
            self._open()
        except BaseException as exc:  # noqa: BLE001 建场景失败要翻译成人话
            logger.exception("仿真启动失败 episode=%s", self.spec.episode_id)
            self._fail(self._explain(exc))
            self._close_sim()
            return

        try:
            self._loop()
        except BaseException as exc:  # noqa: BLE001 渲染期异常同样不能逃逸
            logger.exception("仿真运行异常 episode=%s", self.spec.episode_id)
            self._fail(f"仿真运行异常：{type(exc).__name__}: {exc}")
        finally:
            self._close_sim()
            self._close_recorder()      # 把队列里剩下的帧写完，导出时才能拿到完整序列
            with self._lock:
                if self._status != "error":
                    self._status = "stopped"
                    self._message = "仿真已停止"
                self._lock.notify_all()

    def _open(self) -> None:
        from .scene import add_robot, build_sim
        from .topdown import TopDownMap

        t0 = time.time()
        self.sim = build_sim(self.spec.scene_path, self.gpu_id, pip=self._pip)
        self.agent = self.sim.get_agent(0)
        self.mapper = TopDownMap(self.sim)
        if self._robot_cfg:
            try:
                self._robot = add_robot(self.sim, Path(self._robot_cfg), self._robot_scale)
            except Exception:  # noqa: BLE001 狗只是显示项，加载失败不能拖垮会话
                logger.exception("机器狗加载失败，本局不显示")
                self._robot = None
        self._reset()
        self._render()
        logger.info(
            "仿真就绪 episode=%s 场景=%s 用时 %.1fs",
            self.spec.episode_id, self.spec.scene_label, time.time() - t0,
        )
        with self._lock:
            self._status = "ready"
            self._message = ""
            self._lock.notify_all()

    def _loop(self) -> None:
        next_render = 0.0
        while not self._stop_flag.is_set():
            self._drain()
            if self._stop_flag.is_set():
                break
            if self._consume_model_action():
                self._force_render = True
            elif self._oracle and time.time() >= self._next_tick:
                self._next_tick = time.time() + self.tick
                if self._oracle_step():
                    self._force_render = True
            now = time.time()
            if self._force_render or now >= next_render:
                self._force_render = False
                t0 = time.time()
                self._render()
                period = self.stream_period if self.clients else self.render_period
                # 渲染比预算还慢时让出 CPU，别把队列堵成串行
                next_render = now + max(period, time.time() - t0)
            time.sleep(0.004)

    def _consume_model_action(self) -> bool:
        """按 `self.tick`（4 Hz）从队列取一个模型动作执行；返回是否真的执行了。

        队列空就直接返回，不额外渲染——画面节拍仍由渲染循环决定，
        模型慢（1.8–7.7 s 一次 forward）时只会"走一下停一下"，不会卡住画面。
        """
        now = time.time()
        if now < self._next_tick:
            return False
        with self._lock:
            if not self._pending:
                return False
            name = self._pending.popleft()
        self._next_tick = now + self.tick
        code = C.ACTION_CODES.get(name)
        if code is None:
            logger.warning("模型给出了未知动作 %s，已丢弃", name)
            return False
        try:
            self._apply(code)
        except Exception as exc:  # noqa: BLE001 单个模型动作失败不能拖垮循环
            logger.exception("执行模型动作失败 %s", name)
            with self._lock:
                self._message = f"模型动作执行失败：{type(exc).__name__}: {exc}"
                self._pending.clear()
            return False
        return True

    def _drain(self) -> None:
        while True:
            try:
                kind, payload = self._cmd.get_nowait()
            except queue.Empty:
                return
            try:
                if kind == "act":
                    self._apply(int(payload))
                elif kind == "reset":
                    self._reset()
                elif kind == "oracle":
                    self._set_oracle(bool(payload))
                elif kind == "pip":
                    self._set_pip(bool(payload))
                elif kind == "robot":
                    self._set_robot(bool(payload))
                else:
                    logger.warning("未知控制命令 %s", kind)
            except Exception as exc:  # noqa: BLE001 单个命令失败不拖垮循环
                logger.exception("控制命令执行失败 %s", kind)
                self._message = f"操作失败：{type(exc).__name__}: {exc}"
            self._force_render = True

    def _reset(self) -> None:
        state = self.agent.get_state()
        pos = np.asarray(self.spec.start_position, dtype=np.float64)
        if not self.sim.pathfinder.is_navigable(pos):
            snapped = np.asarray(self.sim.pathfinder.snap_point(pos), dtype=np.float64)
            logger.warning("起点不可导航，吸附 %s -> %s", np.round(pos, 2), np.round(snapped, 2))
            self._warn = "起点不在可通行区域，已吸附到最近的导航点"
            pos = snapped
        state.position = pos
        rot = self.spec.start_rotation
        state.rotation = np.quaternion(rot[3], rot[0], rot[1], rot[2])
        self.agent.set_state(state)
        self._sync_robot()

        self.book = Book()
        self.book.trail.append([round(float(pos[0]), 3), round(float(pos[2]), 3)])
        self._last_pos = np.asarray(pos, dtype=np.float64)
        self.gait = 0.0
        self._oracle = False
        self._oracle_static = None
        with self._lock:
            self._pending.clear()
            self._next_tick = 0.0
        self._update_book()
        while True:
            try:
                self._cmd.get_nowait()
            except queue.Empty:
                break

    def _apply(self, act: int) -> None:
        if act == C.ACT_STOP:
            self.book.stop_called = True
            self.book.done = True
            self._update_book()
            with self._lock:
                self._message = ("已停止：在目标圈内，判定为到达"
                                 if self.book.distance <= self.spec.radius
                                 else "已停止：未进入目标圈，本局结束")
            return
        if self.book.done:
            # 停过的局不再接受动作，避免读数在"已结束"后继续漂移
            with self._lock:
                self._message = "本局已结束，点「回起点」重新开始"
            return
        self.agent.act(C.ACT_NAMES[act])
        self.book.steps += 1
        self.gait += 0.5 if act == C.ACT_FORWARD else 0.15
        if act == C.ACT_FORWARD:
            pos = np.asarray(self.agent.get_state().position, dtype=np.float64)
            self.book.trail.append([round(float(pos[0]), 3), round(float(pos[2]), 3)])
        self._update_book()

    def _update_book(self) -> None:
        pos = np.asarray(self.agent.get_state().position, dtype=np.float64)
        goal = np.asarray(self.spec.goal, dtype=np.float64)
        self.book.distance = float(np.linalg.norm(pos[[0, 2]] - goal[[0, 2]]))
        if self._last_pos is not None:
            self.book.path_length += float(np.linalg.norm(pos[[0, 2]] - self._last_pos[[0, 2]]))
        self._last_pos = pos
        if self.book.steps >= C.MAX_EPISODE_STEPS:
            self.book.done = True

        # 测地距离：欧氏直线会穿墙，NE / SPL 的官方口径都在 navmesh 上量
        self.book.geodesic = self._geodesic(pos)
        if self.book.shortest <= 0:
            self.book.shortest = self._shortest_length()
        self.book.success = self.book.distance <= self.spec.radius
        # SPL = S · L / max(l, L)，L 取官方 geodesic（缺失时用现算的测地长度）
        self.book.spl = (1.0 if self.book.success else 0.0) * self.book.shortest / max(
            self.book.path_length, self.book.shortest, 1e-6)
        self._pose = {
            "x": round(float(pos[0]), 3),
            "z": round(float(pos[2]), 3),
            "yaw_deg": round(float(np.degrees(self._yaw())), 1),
        }

    def _shortest_path(self, pos=None, goal=None):
        """navmesh 最短路径 → `(点列[[x,y,z]], 测地长度)`；不可达返回 `([], inf)`。

        这个 habitat_sim 版本只暴露 `find_path(ShortestPath)`，没有 `find_path(a, b)` 重载，
        所以走 `ShortestPath` 模块（`geodesic_distance` 跨岛时是 inf）。
        """
        import habitat_sim

        start = np.asarray(self._last_pos if pos is None else pos, dtype=np.float32).reshape(3)
        end = np.asarray(self.spec.goal if goal is None else goal, dtype=np.float32).reshape(3)
        sp = habitat_sim.ShortestPath()
        sp.requested_start = start
        sp.requested_end = end
        try:
            ok = bool(self.sim.pathfinder.find_path(sp))
        except Exception:  # noqa: BLE001 点位在 navmesh 外时可能抛
            logger.warning("pathfinder 不可用，测地距离退化为欧氏", exc_info=True)
            self._geo_broken = True
            return [], float("inf")
        if not ok:
            return [], float("inf")
        points = [[float(p[0]), float(p[1]), float(p[2])] for p in sp.points]
        return points, float(sp.geodesic_distance)

    def _geodesic(self, pos: np.ndarray) -> float:
        """`pos` 到目标的测地长度；不可达/接口不可用时退化为欧氏。"""
        goal = np.asarray(self.spec.goal, dtype=np.float64)
        euclid = float(np.linalg.norm(np.asarray(pos, dtype=np.float64)[[0, 2]] - goal[[0, 2]]))
        if self._geo_broken:
            return euclid
        _points, distance = self._shortest_path(pos)
        if not math.isfinite(distance) or distance <= 0:
            if not self._unreachable:
                self._unreachable = True
                logger.warning("目标在 navmesh 上不可达（跨岛？），测地距离退化为欧氏")
            return euclid
        return distance

    def _shortest_length(self) -> float:
        """SPL 分母：优先用数据集里官方的 `geodesic_distance`，没有就用 navmesh 现算。"""
        if self.spec.geodesic_distance:
            return float(self.spec.geodesic_distance)
        if self.book.geodesic > 0:
            return self.book.geodesic
        # 一个都拿不到时给 0，SPL 随之是 0（好过拿一个假分母算出漂亮的数字）
        return 0.0

    def _yaw(self) -> float:
        from .scene import yaw_of

        return yaw_of(self.agent.get_state().rotation)

    # ---- 渲染 -------------------------------------------------------------
    def _static_map(self):
        start = self.spec.start_position
        start_yaw = 2.0 * np.arctan2(self.spec.start_rotation[1], self.spec.start_rotation[3])
        goal = self.spec.goal
        key = (tuple(np.round(start, 3)), tuple(np.round(goal, 3)), round(self.spec.radius, 3))
        return self.mapper.static_layer(key, lambda: self._build_static_map(float(start_yaw)))

    def _build_static_map(self, start_yaw: float):
        """底图 + 两条参考线 + 起终点 + 图例。都是静态的，换局才重建。

        - 紫红虚线 = 人类示范轨迹（R2R 原始数据 `reference_path`）
        - 淡黄虚线 = navmesh 最短路径（oracle 该走的路线）
        青色实线（实际轨迹）每帧叠在它们上面，三条线一眼能看出"偏没偏、偏在哪"。
        """
        from .topdown import (
            COLOR_HUMAN,
            COLOR_ORACLE,
            draw_goal,
            draw_legend,
            draw_path,
            draw_scale_bar,
            draw_start,
        )

        canvas = self.mapper.base_canvas()
        legend = []
        human = self.spec.reference_path
        if human:
            draw_path(canvas, self.mapper, human, COLOR_HUMAN, width=2, dash=5)
            legend.append((COLOR_HUMAN, "human demo"))
        oracle = self._oracle_static_path()
        if oracle:
            draw_path(canvas, self.mapper, oracle, COLOR_ORACLE, width=2, dash=7)
            legend.append((COLOR_ORACLE, "oracle shortest"))
        draw_goal(canvas, self.mapper, self.spec.goal, self.spec.radius)
        draw_start(canvas, self.mapper, self.spec.start_position, start_yaw)
        draw_scale_bar(canvas, self.mapper)
        draw_legend(canvas, legend)
        return canvas

    def _render(self) -> bytes:
        """一张图里同时给第一视角和俯视图（左 RGB + 右俯视，旧脚本的 hstack 布局）。"""
        import cv2
        from .topdown import draw_dog_marker, draw_trail

        self._sync_robot()                 # 先把狗摆到当前位姿，再渲染
        obs = self.sim.get_sensor_observations()
        head = cv2.cvtColor(obs["head_rgb"][:, :, :3], cv2.COLOR_RGB2BGR)
        # 第二路相机存在才谈得上画中画；不叠的时候这帧渲染也省不掉（见 __init__ 注释）
        if C.PIP_UUID in obs:
            self._pip_available = True
            if self._pip:
                self._draw_pip(head, obs[C.PIP_UUID][:, :, :3])

        state = self.agent.get_state()
        yaw = float(2.0 * np.arctan2(state.rotation.y, state.rotation.w))
        pos = np.asarray(state.position, dtype=np.float64)

        canvas = self._static_map().copy()
        draw_trail(canvas, self.mapper, self.book.trail)
        px, py = self.mapper.to_px(float(pos[0]), float(pos[2]))
        draw_dog_marker(canvas, px, py, yaw, self.gait)

        self._draw_hud(head)
        frame = np.hstack([head, canvas])
        cv2.line(frame, (C.HEAD_W, 0), (C.HEAD_W, frame.shape[0]), (90, 90, 90), 1)

        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality])
        if not ok:
            raise RuntimeError("JPEG 编码失败")
        jpeg = buf.tobytes()
        if self.recorder is not None:
            self.recorder.push(jpeg)     # 只入队，抽样与写盘都在别的线程/别的时间片

        trail = self.book.trail
        if len(trail) > C.MAX_TRAIL_POINTS:      # 抽稀，别让快照无限膨胀
            trail = trail[::2] + trail[-1:]

        # 用最近 1 秒的帧数算帧率：比"上一个间隔的倒数"稳，不会被强制渲染的尖峰带偏
        now = time.time()
        self._frame_times.append(now)
        while self._frame_times and now - self._frame_times[0] > 1.0:
            self._frame_times.popleft()
        # 样本太少时不给数字（刚就绪的几帧间隔不均，算出来会虚高）
        if len(self._frame_times) >= 10:
            span = self._frame_times[-1] - self._frame_times[0]
            if span >= 0.5:
                self._fps = (len(self._frame_times) - 1) / span

        with self._lock:
            self._latest_jpeg = jpeg
            # 模型吃的是"未加工的头视角"，不是拼好的 JPEG；.copy() 保证不被下一帧覆写
            self._head_rgb = np.ascontiguousarray(obs["head_rgb"][:, :, :3]).copy()
            self._frame_seq += 1
            self._trail_snap = [list(p) for p in trail]
            self._lock.notify_all()
        return jpeg

    def _draw_pip(self, head, chase_rgb) -> None:
        """第三视角贴到第一视角右上角（HUD 在左下角，互不遮挡）。"""
        import cv2

        tile = cv2.cvtColor(chase_rgb, cv2.COLOR_RGB2BGR)
        limit_w = head.shape[1] - 2 * C.PIP_MARGIN
        limit_h = head.shape[0] - 2 * C.PIP_MARGIN
        if tile.shape[1] > limit_w or tile.shape[0] > limit_h:
            scale = min(limit_w / tile.shape[1], limit_h / tile.shape[0])
            tile = cv2.resize(tile, (int(tile.shape[1] * scale), int(tile.shape[0] * scale)))
        h, w = tile.shape[:2]
        x0 = max(C.PIP_MARGIN, head.shape[1] - w - C.PIP_MARGIN)
        y0 = C.PIP_MARGIN
        cv2.rectangle(head, (x0 - 2, y0 - 2), (x0 + w + 1, y0 + h + 1), (90, 90, 90), 1)
        head[y0:y0 + h, x0:x0 + w] = tile
        cv2.putText(head, C.PIP_LABEL, (x0 + 6, y0 + 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (235, 238, 245), 1, cv2.LINE_AA)

    def _draw_hud(self, head) -> None:
        """第一视角左下角的文字读数（只画英文，避免中文字体缺失时乱码）。"""
        import cv2

        status = "STOPPED" if self.book.done else "RUNNING"
        spl = f"SPL {self.book.spl:.2f}" if self.book.shortest > 0 else "SPL -"
        lines = [
            f"STEP {self.book.steps}/{C.MAX_EPISODE_STEPS}   DIST {self.book.distance:.2f}m"
            f"   GEO {self.book.geodesic:.2f}m   r={self.spec.radius:.1f}m   {status}",
            f"path {self.book.path_length:.2f}m   {spl}"
            f"   src={self._last_source}   q={len(self._pending)}",
        ]
        pad, line_h = 6, 16
        widths = [cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)[0][0] for t in lines]
        box_w = max(widths) + 2 * pad
        box_h = line_h * len(lines) + pad
        y0 = head.shape[0] - box_h - 8
        overlay = head.copy()
        cv2.rectangle(overlay, (8, y0), (8 + box_w, y0 + box_h), (12, 12, 14), -1)
        cv2.addWeighted(overlay, 0.62, head, 0.38, 0, head)
        for i, text in enumerate(lines):
            cv2.putText(head, text, (8 + pad, y0 + pad + line_h * (i + 1) - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (235, 238, 245), 1, cv2.LINE_AA)

    # ---- 关闭 / 异常 -------------------------------------------------------
    def _close_recorder(self) -> None:
        recorder, self.recorder = self.recorder, None
        if recorder is None:
            return
        try:
            recorder.close()
        except Exception:  # noqa: BLE001 录制收尾失败不影响会话停止
            logger.exception("关闭录制失败")

    def _close_sim(self) -> None:
        sim, self.sim = self.sim, None
        if sim is None:
            return
        self.agent = None
        self.mapper = None
        try:
            sim.close()
        except Exception:  # noqa: BLE001 关不掉也不能再抛
            logger.exception("关闭 Simulator 失败")

    def _fail(self, message: str) -> None:
        with self._lock:
            self._status = "error"
            self._message = message
            self._lock.notify_all()

    @staticmethod
    def _explain(exc: BaseException) -> str:
        name = type(exc).__name__
        text = str(exc)
        lowered = text.lower()
        if isinstance(exc, ImportError) or "habitat_sim" in lowered:
            return f"仿真组件不可用：{name}: {text}。请确认已在当前 Python 环境安装 habitat_sim。"
        if "cuda" in lowered or "gpu" in lowered or "memory" in lowered:
            return f"GPU 资源不足或不可用：{name}: {text}。请释放显存或换一张卡后重试。"
        if "scene" in lowered or "glb" in lowered or "no such file" in lowered:
            return f"场景加载失败：{name}: {text}。请确认场景文件完整。"
        return f"场景加载失败：{name}: {text}"
