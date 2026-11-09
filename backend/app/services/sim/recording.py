"""会话录制与 mp4 导出（docs/09 #10）。

链路三段，谁也不挡谁：

1. 引擎线程渲染完一帧 → `FrameRecorder.push(jpeg)`：只做时间抽样 + `put_nowait`，
   队列满就丢帧（宁可少几帧，也不能让写盘拖慢渲染）；
2. 写盘线程把 JPEG 按 `000001.jpg` 递增落盘，`close()` 会把队列排空再退出；
3. 用户点导出 → `Mp4Export.start()` 在后台线程用 `cv2.VideoWriter`（mp4v）按
   `video_fps` 编码，进度写进 `snapshot()`，前端靠 `/api/sim/state` 轮询展示。

落盘用 JPEG 而不是原始 RGB：1120×480 的帧原始 1.6 MB，JPEG 只有 ~80 KB，
一局 10 分钟的录制从 5 GB 降到 150 MB 量级。
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path

from . import constants as C

logger = logging.getLogger(__name__)

# 写盘队列：满了就丢帧。JPEG 单帧 ~80 KB，32 帧 ≈ 2.5 MB，够扛一次磁盘抖动
WRITE_QUEUE_MAX = 32


class FrameRecorder:
    """把渲染帧按固定采样率落成 JPEG 序列。"""

    def __init__(
        self,
        directory: Path | str,
        *,
        fps: float = C.RECORD_FPS,
        max_frames: int = C.RECORD_MAX_FRAMES,
    ) -> None:
        self.directory = Path(directory)
        self.fps = max(1.0, float(fps))
        self.max_frames = max(1, int(max_frames))
        self.frames = 0
        self.dropped = 0

        self._queue: queue.Queue = queue.Queue(maxsize=WRITE_QUEUE_MAX)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._closed = False
        self._lock = threading.Lock()
        self._next_at = 0.0
        self._started_at = time.time()

    def start(self) -> "FrameRecorder":
        self.directory.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(
            target=self._write_loop, name="sim-recorder", daemon=True)
        self._thread.start()
        return self

    def push(self, jpeg: bytes | None) -> None:
        """引擎线程调用；返回前只做一次入队，绝不等磁盘。"""
        if self._closed or not jpeg:
            return
        now = time.time()
        with self._lock:
            if now < self._next_at:          # 引擎 15–20 fps，录制只要 10 fps
                return
            self._next_at = now + 1.0 / self.fps
            if self.frames + self._queue.qsize() >= self.max_frames:
                self.dropped += 1
                return
        try:
            self._queue.put_nowait(jpeg)
        except queue.Full:
            with self._lock:
                self.dropped += 1

    def _write_loop(self) -> None:
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                if self._stop.is_set():      # 队列已排空且收到停止信号
                    return
                time.sleep(0.05)
                continue
            index = self.frames + 1
            target = self.directory / f"{index:06d}.jpg"
            try:
                target.write_bytes(item)
            except OSError:
                logger.exception("写入录制帧失败 %s", target)
                continue
            self.frames = index

    def close(self) -> int:
        """停止采样并把队列写空；返回最终帧数。"""
        if self._closed:
            return self.frames
        self._closed = True
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=3.0)
            if thread.is_alive():
                logger.warning("录制写盘线程未在 3s 内退出，可能丢了几帧")
        return self.frames

    @property
    def seconds(self) -> float:
        return round(self.frames / self.fps, 1)

    def snapshot(self) -> dict:
        return {
            "frames": self.frames,
            "seconds": self.seconds,
            "fps": round(self.fps, 1),
            "dropped": self.dropped,
            "max_frames": self.max_frames,
        }


def idle_export_state() -> dict:
    return {
        "status": "idle",
        "frames": 0,
        "encoded": 0,
        "progress": 0.0,
        "filename": "",
        "size_bytes": 0,
        "seconds": 0.0,
        "message": "",
    }


class Mp4Export:
    """把一个目录下的 JPEG 序列异步编码成 mp4。

    `start()` 立刻返回，编码在后台线程跑；`snapshot()` 给前端轮询用。
    状态机：idle → encoding → ready / error。
    """

    def __init__(self, frames_dir: Path | str, target: Path | str,
                 *, fps: int = C.VIDEO_FPS) -> None:
        self.frames_dir = Path(frames_dir)
        self.target = Path(target)
        self.fps = max(1, int(fps))
        # 可重入：`start()` 的早退分支会在持锁时调 `snapshot()`，普通 Lock 会自锁
        self._lock = threading.RLock()
        self._files: list[Path] = []
        self._thread: threading.Thread | None = None
        self._state = idle_export_state()
        self._state["filename"] = self.target.name

    def start(self) -> dict:
        with self._lock:
            if self._state["status"] == "encoding":
                return self.snapshot()
            files = sorted(self.frames_dir.glob("*.jpg")) if self.frames_dir.exists() else []
            if not files:
                self._state.update(idle_export_state())
                self._state.update(
                    status="error", filename=self.target.name,
                    message="还没有录到画面，先让仿真跑几秒再导出",
                )
                return self.snapshot()
            self._files = files
            self._state.update(
                status="encoding", frames=len(files), encoded=0, progress=0.0,
                size_bytes=0, message="", filename=self.target.name,
                seconds=round(len(files) / float(self.fps), 1),
            )
        self._thread = threading.Thread(target=self._run, name="sim-export", daemon=True)
        self._thread.start()
        return self.snapshot()

    def _run(self) -> None:
        total = len(self._files)
        try:
            import cv2

            first = cv2.imread(str(self._files[0]))
            if first is None:
                raise RuntimeError("首帧无法解码")
            height, width = first.shape[:2]
            self.target.parent.mkdir(parents=True, exist_ok=True)
            # VideoWriter 只按扩展名选容器，先写 .part.mp4 再原子替换，
            # 避免前端在编码到一半时拿到半截文件
            partial = self.target.with_suffix(".part.mp4")
            writer = cv2.VideoWriter(
                str(partial), cv2.VideoWriter_fourcc(*"mp4v"), self.fps, (width, height))
            if not writer.isOpened():
                raise RuntimeError("OpenCV 打不开 mp4 编码器（缺 ffmpeg 支持）")
            try:
                for index, path in enumerate(self._files):
                    frame = first if index == 0 else cv2.imread(str(path))
                    if frame is None:
                        continue
                    if frame.shape[0] != height or frame.shape[1] != width:
                        frame = cv2.resize(frame, (width, height))
                    writer.write(frame)
                    if index % 10 == 0 or index == total - 1:
                        with self._lock:
                            self._state.update(
                                encoded=index + 1,
                                progress=round((index + 1) / float(total), 3),
                            )
            finally:
                writer.release()
            partial.replace(self.target)
            size = self.target.stat().st_size
            with self._lock:
                self._state.update(
                    status="ready", progress=1.0, encoded=total,
                    size_bytes=size, message="",
                )
            logger.info("导出 mp4 完成 %s（%d 帧 / %.1f MB）",
                        self.target.name, total, size / 1024 / 1024)
        except Exception as exc:  # noqa: BLE001 编码失败只影响导出，不能拖垮会话
            logger.exception("导出 mp4 失败")
            with self._lock:
                self._state.update(
                    status="error",
                    message=f"导出失败：{type(exc).__name__}: {exc}",
                )

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)
