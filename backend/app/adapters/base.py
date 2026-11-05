"""适配器协议与运行上下文。

适配器只负责"跑一条 episode 并产出标准记录"，不写数据库；
调度器负责持久化、事件推送与状态迁移，便于替换推理后端。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator


@dataclass
class EpisodeRecord:
    episode_key: str
    scene_id: str = ""
    success: bool = False
    spl: float = 0.0
    ne: float = 0.0
    os: float = 0.0
    ndtw: float = 0.0
    tl: float = 0.0
    steps: int = 0
    latencies: list[float] = field(default_factory=list)
    gpu_mem_peak_mb: int = 0
    tokens_peak: int = 0
    ctx_len_peak: int = 0
    failure_reason: str = ""
    frames: list[dict[str, Any]] = field(default_factory=list)

    @property
    def latency_avg_ms(self) -> float:
        if not self.latencies:
            return 0.0
        return round(sum(self.latencies) / len(self.latencies), 2)

    @property
    def latency_p95_ms(self) -> float:
        if not self.latencies:
            return 0.0
        ordered = sorted(self.latencies)
        index = min(len(ordered) - 1, int(len(ordered) * 0.95))
        return round(ordered[index], 2)


@dataclass
class RunContext:
    task_id: int
    task_name: str
    run_dir: Path
    config: dict[str, Any]
    episodes: list[dict[str, Any]]
    model: dict[str, Any]
    dataset: dict[str, Any]
    log: Callable[[str], None]
    progress: Callable[[int, int, str], None]
    sample: Callable[[dict[str, Any]], None]
    cancel_event: threading.Event = field(default_factory=threading.Event)
    pause_event: threading.Event = field(default_factory=threading.Event)
    stopped: bool = False

    @property
    def frames_dir(self) -> Path:
        directory = self.run_dir / "frames"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def should_cancel(self) -> bool:
        return self.cancel_event.is_set()

    def wait_if_paused(self) -> None:
        while self.pause_event.is_set() and not self.cancel_event.is_set():
            threading.Event().wait(0.3)


class BaseAdapter:
    name = "base"
    allowed_inputs: set[str] = {"rgb"}

    def __init__(self, ctx: RunContext):
        self.ctx = ctx

    def prepare(self) -> None:
        """校验运行条件，失败时抛出 RuntimeError 并附带可读原因。"""

    def run(self) -> Iterator[EpisodeRecord]:
        raise NotImplementedError

    def stop(self) -> None:
        """终止底层进程（取消时调用），默认无操作。"""

    def finish(self) -> dict[str, Any]:
        return {}


def build_adapter(ctx: RunContext) -> BaseAdapter:
    family = str(ctx.model.get("family", "")).lower()
    if family == "streamvln":
        return StreamVLNAdapter(ctx)
    if family == "mock":
        return MockAdapter(ctx)
    entry = str(ctx.model.get("entry") or "")
    if entry.endswith("MockAdapter"):
        return MockAdapter(ctx)
    raise RuntimeError(f"暂不支持的模型家族：{family or '未配置'}")


# 延迟导入，避免循环引用
from .mock_adapter import MockAdapter  # noqa: E402
from .streamvln_adapter import StreamVLNAdapter  # noqa: E402
