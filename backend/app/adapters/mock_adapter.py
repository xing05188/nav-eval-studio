"""离线演示适配器。

无需 GPU 与数据集帧，按"模态组合 × 记忆策略"的基准成功率生成可复现结果，
并提供逐帧元数据（位姿、动作、记忆窗口、token 裁剪），供回放与对比演示使用。
所有随机性来自 sha256(episode_key + seed)，同配置重跑结果一致。
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Iterator

from .base import BaseAdapter, EpisodeRecord

# 不同配置的基准成功率，用于让消融对比呈现合理差异
BASE_SUCCESS = {
    ("vision", "fixed_window"): 0.44,
    ("vision", "sliding_window"): 0.47,
    ("vision", "feature_cache"): 0.46,
    ("vision_geo", "spatial_prune"): 0.51,
    ("vision_geo_state", "spatial_prune"): 0.56,
    ("vision_geo_state", "feature_cache"): 0.53,
    ("vision_geo_state", "hybrid"): 0.575,
}

MODALITY_COST = {"vision": 0.0, "vision_geo": 55.0, "vision_geo_state": 72.0}
FAILURE_WEIGHTS = [("off_track", 0.30), ("early_stop", 0.30), ("timeout", 0.25), ("loop", 0.15)]
ACTIONS = ["forward", "forward", "forward", "left", "forward", "right", "forward"]


def _unit(*parts: Any) -> float:
    raw = "|".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


class MockAdapter(BaseAdapter):
    name = "mock"

    def prepare(self) -> None:
        if not self.ctx.episodes:
            raise RuntimeError("切分中没有 episode，无法生成演示结果")

    def run(self) -> Iterator[EpisodeRecord]:
        config = self.ctx.config
        modality = str(config.get("modality", "vision"))
        policy = str(config.get("memory_policy", "fixed_window"))
        seed = int(config.get("seed", 42))
        max_steps = int(config.get("max_steps", 500))
        history_len = int(config.get("history_len", 8))
        slow_interval = max(1, int(config.get("slow_update_interval", 4)))
        prune_ratio = float(config.get("prune_ratio", 0.0))
        delay = float(config.get("mock_delay", 0.08))

        base = BASE_SUCCESS.get((modality, policy), 0.45)
        extra_cost = MODALITY_COST.get(modality, 0.0)
        total = len(self.ctx.episodes)

        for index, episode in enumerate(self.ctx.episodes):
            if self.ctx.should_cancel():
                return
            self.ctx.wait_if_paused()
            self.ctx.progress(index, total, episode["episode_key"])

            record = self._make_record(
                episode,
                index=index,
                seed=seed,
                base=base,
                extra_cost=extra_cost,
                max_steps=max_steps,
                history_len=history_len,
                slow_interval=slow_interval,
                prune_ratio=prune_ratio,
            )
            self.ctx.log(
                f"[{index + 1}/{total}] {record.episode_key} "
                f"{'OK' if record.success else 'FAIL'} "
                f"SR={1 if record.success else 0} SPL={record.spl:.3f} "
                f"NE={record.ne:.2f} steps={record.steps}"
            )
            if delay > 0:
                time.sleep(delay)
            yield record

    def _make_record(
        self,
        episode: dict[str, Any],
        *,
        index: int,
        seed: int,
        base: float,
        extra_cost: float,
        max_steps: int,
        history_len: int,
        slow_interval: int,
        prune_ratio: float,
    ) -> EpisodeRecord:
        key = str(episode["episode_key"])
        traj_len = float(episode.get("traj_len") or 8.0)
        start_pose = episode.get("start_pose") or [0.0, 0.0, 0.0, 0.0]

        u1 = _unit(seed, key, "success")
        u2 = _unit(seed, key, "noise")
        success = u1 < _clamp(base + (u2 - 0.5) * 0.08)

        steps = int(_clamp(traj_len / 0.25 * (0.8 + 0.6 * _unit(seed, key, "steps")), 8, max_steps))
        if not success:
            steps = int(min(max_steps, steps * (1.2 + 0.6 * _unit(seed, key, "failsteps"))))

        spl = _clamp(0.55 + 0.42 * _unit(seed, key, "spl")) if success else 0.0
        ne = 1.2 + 2.4 * _unit(seed, key, "ne") if success else 4.5 + 7.5 * _unit(seed, key, "ne_fail")
        os_value = 0.58 + 0.14 * _unit(seed, key, "os")
        ndtw = (
            _clamp(0.45 + 0.38 * _unit(seed, key, "ndtw"))
            if success
            else _clamp(0.18 + 0.28 * _unit(seed, key, "ndtw_fail"))
        )
        tl = traj_len * (1 + 0.35 * _unit(seed, key, "tl")) if success else traj_len * (1 + 0.9 * _unit(seed, key, "tl_fail"))

        reason = ""
        if not success:
            pick = _unit(seed, key, "reason")
            cumulative = 0.0
            for name, weight in FAILURE_WEIGHTS:
                cumulative += weight
                if pick <= cumulative:
                    reason = name
                    break
            reason = reason or "unknown"

        base_latency = 360.0 + extra_cost + 40.0 * _unit(seed, key, "latency")
        latencies = [
            round(base_latency * (0.85 + 0.3 * _unit(seed, key, "lat", step)), 2)
            for step in range(min(steps, 60))
        ]
        gpu_mem = int(15800 + 1800 * _unit(seed, key, "gpu"))
        tokens_peak = int(6200 + 3200 * _unit(seed, key, "tokens"))
        ctx_peak = int(8192 + 8192 * _unit(seed, key, "ctx"))

        frames = self._make_frames(
            key=key,
            seed=seed,
            steps=steps,
            start_pose=start_pose,
            base_latency=base_latency,
            history_len=history_len,
            slow_interval=slow_interval,
            prune_ratio=prune_ratio,
            tokens_peak=tokens_peak,
        )

        return EpisodeRecord(
            episode_key=key,
            scene_id=str(episode.get("scene_id") or ""),
            success=success,
            spl=round(spl, 4),
            ne=round(ne, 3),
            os=round(os_value, 4),
            ndtw=round(ndtw, 4),
            tl=round(tl, 3),
            steps=steps,
            latencies=latencies,
            gpu_mem_peak_mb=gpu_mem,
            tokens_peak=tokens_peak,
            ctx_len_peak=ctx_peak,
            failure_reason=reason,
            frames=frames,
        )

    def _make_frames(
        self,
        *,
        key: str,
        seed: int,
        steps: int,
        start_pose: list[float],
        base_latency: float,
        history_len: int,
        slow_interval: int,
        prune_ratio: float,
        tokens_peak: int,
    ) -> list[dict[str, Any]]:
        """生成回放用逐帧元数据：位姿、动作、窗口长度与 token 裁剪。"""
        limit = min(steps, 80)
        x = float(start_pose[0]) if len(start_pose) > 0 else 0.0
        y = float(start_pose[1]) if len(start_pose) > 1 else 0.0
        z = float(start_pose[2]) if len(start_pose) > 2 else 0.0
        yaw = float(start_pose[3]) if len(start_pose) > 3 else 0.0

        frames: list[dict[str, Any]] = []
        for index in range(limit):
            action = ACTIONS[int(_unit(seed, key, "act", index) * len(ACTIONS)) % len(ACTIONS)]
            if action == "forward":
                x += 0.25 * (1 + 0.2 * (_unit(seed, key, "dx", index) - 0.5))
                z -= 0.25 * (1 + 0.2 * (_unit(seed, key, "dz", index) - 0.5))
            elif action == "left":
                yaw += 0.6
            else:
                yaw -= 0.6

            window_len = min(history_len, index + 1)
            slow_update = index > 0 and index % slow_interval == 0
            tokens_before = int(tokens_peak * (0.75 + 0.25 * _unit(seed, key, "tb", index)))
            tokens_after = int(tokens_before * (1 - prune_ratio)) if slow_update else tokens_before
            frames.append(
                {
                    "idx": index,
                    "t": round(index * 0.5, 2),
                    "pose": [round(x, 3), round(y, 3), round(z, 3)],
                    "yaw": round(yaw, 3),
                    "action": action,
                    "latency_ms": round(base_latency * (0.85 + 0.3 * _unit(seed, key, "l", index)), 2),
                    "window_len": window_len,
                    "slow_update": slow_update,
                    "tokens_before_prune": tokens_before,
                    "tokens_after_prune": tokens_after,
                    "ctx_len": tokens_after + window_len * 576,
                }
            )
        return frames
