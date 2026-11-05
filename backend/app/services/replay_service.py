"""回放数据服务。

将任务结果还原为可交互的回放视图：逐帧元数据、参考路径、动作与记忆状态。
Mock 适配器会落盘逐帧 jsonl；缺少 RGB 帧图时按帧元数据生成示意帧，保证离线可演示。
"""

from __future__ import annotations

import html
import json
import math
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.paths import ensure_within
from ..core.response import NOT_FOUND, PARAM_INVALID, AppError
from ..models import Dataset, Episode, EvalTask, TaskEpisode

MAX_FRAMES = 600

ACTION_LABELS = {
    "forward": "前进",
    "left": "左转",
    "right": "右转",
    "stop": "停止",
    "turn_left": "左转",
    "turn_right": "右转",
}

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def _loads(text: str | None, default: Any) -> Any:
    try:
        value = json.loads(text or "")
    except (json.JSONDecodeError, TypeError):
        return default
    return value if isinstance(value, type(default)) else default


def _float_list(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[float] = []
    for item in value:
        try:
            result.append(float(item))
        except (TypeError, ValueError):
            continue
    return result


def _get_row(db: Session, task_id: int, row_id: int) -> tuple[EvalTask, TaskEpisode, Episode]:
    task = db.get(EvalTask, task_id)
    if task is None:
        raise AppError(NOT_FOUND, "评测任务不存在")
    row = db.get(TaskEpisode, row_id)
    if row is None or row.task_id != task_id:
        raise AppError(NOT_FOUND, "回放记录不存在")
    episode = db.get(Episode, row.episode_id)
    if episode is None:
        raise AppError(NOT_FOUND, "Episode 数据不存在")
    return task, row, episode


def _run_dir(task_id: int) -> Path:
    return get_settings().runs_dir / f"task-{task_id:06d}"


def _frames_file(task_id: int, row: TaskEpisode, episode_key: str) -> Path | None:
    settings = get_settings()
    candidates: list[Path] = []
    if row.traj_path:
        path = Path(row.traj_path)
        if not path.is_absolute():
            path = _run_dir(task_id) / path
        candidates.append(path)
    candidates.append(_run_dir(task_id) / "frames" / f"{episode_key}.jsonl")

    for path in candidates:
        try:
            target = ensure_within(settings.storage.work_dir, path)
        except AppError:
            continue
        if target.is_file():
            return target
    return None


def _read_frames(task_id: int, row: TaskEpisode, episode_key: str) -> list[dict[str, Any]]:
    target = _frames_file(task_id, row, episode_key)
    if target is None:
        return []

    frames: list[dict[str, Any]] = []
    try:
        with target.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(raw, dict):
                    continue
                pose = _float_list(raw.get("pose"))
                if len(pose) < 3:
                    continue
                before = int(raw.get("tokens_before_prune") or 0)
                after = int(raw.get("tokens_after_prune") or before)
                frames.append(
                    {
                        "idx": int(raw.get("idx", len(frames))),
                        "t": float(raw.get("t") or 0.0),
                        "pose": pose[:3],
                        "yaw": float(raw.get("yaw") or 0.0),
                        "action": str(raw.get("action") or "forward"),
                        "latency_ms": round(float(raw.get("latency_ms") or 0.0), 2),
                        "window_len": int(raw.get("window_len") or 0),
                        "slow_update": bool(raw.get("slow_update")),
                        "tokens_before_prune": before,
                        "tokens_after_prune": after,
                        "ctx_len": int(raw.get("ctx_len") or after),
                    }
                )
    except OSError:
        return []

    frames.sort(key=lambda item: item["idx"])
    return frames[:MAX_FRAMES]


def _reference_path(episode: Episode, start: list[float], goal: list[float]) -> list[list[float]]:
    meta = _loads(episode.meta_json, {})
    raw = meta.get("reference_path") if isinstance(meta, dict) else None
    points: list[list[float]] = []
    if isinstance(raw, list):
        for item in raw:
            values = _float_list(item)
            if len(values) >= 3:
                points.append([round(values[0], 3), round(values[2], 3)])
    if points:
        return points
    if start and goal:
        return [[round(start[0], 3), round(start[2], 3)], [round(goal[0], 3), round(goal[2], 3)]]
    return []


def _instruction_spans(text: str) -> list[dict[str, Any]]:
    return [
        {"start": match.start(), "end": match.end(), "text": match.group()}
        for match in re.finditer(r"\S+", text or "")
    ]


def _speed_series(frames: list[dict[str, Any]]) -> list[list[float]]:
    series: list[list[float]] = []
    for index, frame in enumerate(frames):
        speed = 0.0
        if index > 0:
            prev = frames[index - 1]
            dt = frame["t"] - prev["t"]
            if dt > 0:
                dx = frame["pose"][0] - prev["pose"][0]
                dz = frame["pose"][2] - prev["pose"][2]
                speed = math.hypot(dx, dz) / dt
        series.append([frame["t"], round(speed, 3)])
    return series


def _mask_path(task_id: int, episode_key: str) -> Path | None:
    run_dir = _run_dir(task_id)
    candidates = [
        run_dir / "frames" / f"{episode_key}_mask.png",
        run_dir / "masks" / f"{episode_key}.png",
        run_dir / "raw" / "masks" / f"{episode_key}.png",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def _frame_file(task_id: int, episode_key: str, frame_index: int) -> Path | None:
    run_dir = _run_dir(task_id)
    stems = [
        run_dir / "frames",
        run_dir / "frames" / episode_key,
        run_dir / "raw" / "frames",
        run_dir / "raw" / episode_key,
    ]
    names = [
        f"{episode_key}_{frame_index}",
        f"{episode_key}_{frame_index:05d}",
        f"{frame_index}",
        f"{frame_index:05d}",
        f"rgb_{frame_index}",
        f"rgb_{frame_index:05d}",
    ]
    for directory in stems:
        for name in names:
            for suffix in IMAGE_SUFFIXES:
                candidate = directory / f"{name}{suffix}"
                if candidate.is_file():
                    return candidate
    return None


def episode_replay(db: Session, task_id: int, row_id: int) -> dict[str, Any]:
    task, row, episode = _get_row(db, task_id, row_id)
    dataset = db.get(Dataset, task.dataset_id)
    config = _loads(task.config_json, {})
    start = _float_list(_loads(episode.start_pose_json, []))
    goal = _float_list(_loads(episode.goal_pose_json, []))
    frames = _read_frames(task_id, row, episode.episode_id)

    trajectory = [[round(frame["pose"][0], 3), round(frame["pose"][2], 3)] for frame in frames]
    reference = _reference_path(episode, start, goal)
    mask_path = _mask_path(task_id, episode.episode_id)

    xs = [point[0] for point in trajectory] + [point[0] for point in reference]
    zs = [point[1] for point in trajectory] + [point[1] for point in reference]
    if len(start) >= 3:
        xs.append(start[0])
        zs.append(start[2])
    if len(goal) >= 3:
        xs.append(goal[0])
        zs.append(goal[2])
    bounds = {
        "min_x": round(min(xs), 3) if xs else 0.0,
        "max_x": round(max(xs), 3) if xs else 1.0,
        "min_z": round(min(zs), 3) if zs else 0.0,
        "max_z": round(max(zs), 3) if zs else 1.0,
    }

    slow_updates = [frame["idx"] for frame in frames if frame["slow_update"]]
    pruned = [
        frame["idx"]
        for frame in frames
        if frame["tokens_after_prune"] < frame["tokens_before_prune"]
    ]

    return {
        "task": {"id": task.id, "name": task.name, "dataset": dataset.name if dataset else ""},
        "row": {
            "id": row.id,
            "episode_key": episode.episode_id,
            "scene_id": episode.scene_id,
            "status": row.status,
            "success": bool(row.success),
            "spl": round(row.spl, 4),
            "ne": round(row.ne, 3),
            "ndtw": round(row.ndtw, 4),
            "tl": round(row.tl, 3),
            "steps": row.steps,
            "latency_avg_ms": round(row.latency_avg_ms, 1),
            "gpu_mem_peak_mb": row.gpu_mem_peak_mb,
            "failure_reason": row.manual_reason or row.failure_reason,
        },
        "episode": {
            "episode_key": episode.episode_id,
            "scene_id": episode.scene_id,
            "instruction": episode.instruction,
            "instruction_spans": _instruction_spans(episode.instruction),
            "instruction_len": episode.instruction_len,
            "start_pose": start,
            "goal_pose": goal,
            "traj_len": round(episode.traj_len, 3),
        },
        "config": {
            "modality": config.get("modality", ""),
            "memory_policy": config.get("memory_policy", ""),
            "history_len": int(config.get("history_len") or 0),
            "slow_update_interval": int(config.get("slow_update_interval") or 0),
        },
        "frames": frames,
        "summary": {
            "frames": len(frames),
            "slow_updates": len(slow_updates),
            "pruned_frames": len(pruned),
            "max_ctx_len": max((frame["ctx_len"] for frame in frames), default=0),
        },
        "geometry": {
            "trajectory": trajectory,
            "reference": reference,
            "start": [round(start[0], 3), round(start[2], 3)] if len(start) >= 3 else None,
            "goal": [round(goal[0], 3), round(goal[2], 3)] if len(goal) >= 3 else None,
            "speed_series": _speed_series(frames),
            "bounds": bounds,
            "mask_url": f"/api/replay/{task_id}/{row_id}/mask" if mask_path else None,
            "mask_available": bool(mask_path),
            "pointcloud_available": False,
        },
        "memory": {
            "slow_update_indices": slow_updates,
            "pruned_indices": pruned,
            "window_series": [frame["window_len"] for frame in frames],
            "ctx_series": [frame["ctx_len"] for frame in frames],
            "tokens_before_series": [frame["tokens_before_prune"] for frame in frames],
            "tokens_after_series": [frame["tokens_after_prune"] for frame in frames],
        },
    }


def _placeholder_svg(
    task_id: int,
    row: TaskEpisode,
    episode: Episode,
    frame: dict[str, Any] | None,
    total: int,
) -> bytes:
    action = str(frame.get("action", "forward")) if frame else "forward"
    action_label = ACTION_LABELS.get(action, action)
    pose = frame.get("pose", [0.0, 0.0, 0.0]) if frame else [0.0, 0.0, 0.0]
    index = int(frame.get("idx", 0)) if frame else 0
    latency = float(frame.get("latency_ms", 0.0)) if frame else 0.0
    window = int(frame.get("window_len", 0)) if frame else 0
    tokens = int(frame.get("tokens_after_prune", 0)) if frame else 0
    instruction = html.escape((episode.instruction or "")[:110])
    accent = {"forward": "#4f9bff", "left": "#34d399", "right": "#fbbf24"}.get(action, "#94a3b8")
    arrow = {
        "forward": "M480 190 L540 290 L505 290 L505 350 L455 350 L455 290 L420 290 Z",
        "left": "M470 270 L350 210 L350 245 L290 245 L290 295 L350 295 L350 330 Z",
        "right": "M490 270 L610 210 L610 245 L670 245 L670 295 L610 295 L610 330 Z",
    }.get(action, "M480 190 L540 290 L505 290 L505 350 L455 350 L455 290 L420 290 Z")

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
<defs>
  <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#0b1220"/><stop offset="0.55" stop-color="#16263f"/><stop offset="1" stop-color="#1c3049"/>
  </linearGradient>
  <linearGradient id="floor" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#223651" stop-opacity="0.2"/><stop offset="1" stop-color="#0d1728" stop-opacity="0.95"/>
  </linearGradient>
</defs>
<rect width="960" height="540" fill="url(#sky)"/>
<rect y="300" width="960" height="240" fill="url(#floor)"/>
<g stroke="#3f5c7f" stroke-opacity="0.35" stroke-width="1">
  <path d="M0 300 H960"/>
  <path d="M0 330 H960"/><path d="M0 370 H960"/><path d="M0 420 H960"/><path d="M0 480 H960"/>
  <path d="M480 300 L380 540"/><path d="M480 300 L580 540"/>
  <path d="M480 300 L180 540"/><path d="M480 300 L780 540"/>
  <path d="M480 300 L40 540"/><path d="M480 300 L920 540"/>
</g>
<g fill="none" stroke="#2c4564" stroke-opacity="0.5">
  <rect x="120" y="210" width="150" height="110" rx="4"/>
  <rect x="690" y="190" width="180" height="130" rx="4"/>
  <path d="M150 320 V250 H270 V320"/><path d="M720 320 V230 H850 V320"/>
</g>
<circle cx="480" cy="300" r="150" fill="{accent}" fill-opacity="0.06"/>
<path d="{arrow}" fill="{accent}" fill-opacity="0.9"/>
<g font-family="Segoe UI, PingFang SC, sans-serif">
  <text x="36" y="48" fill="#e2e8f0" font-size="20" font-weight="600">{html.escape(episode.episode_id)}</text>
  <text x="36" y="76" fill="#8098b8" font-size="13">task #{task_id} · episode row #{row.id} · {html.escape(episode.scene_id)}</text>
  <text x="924" y="48" fill="{accent}" font-size="18" text-anchor="end" font-weight="600">{action_label}</text>
  <text x="924" y="74" fill="#8098b8" font-size="13" text-anchor="end">STEP {index + 1} / {max(total, 1)}</text>
  <text x="480" y="405" fill="#cbd8ea" font-size="24" text-anchor="middle" font-weight="600">{action_label}</text>
  <text x="480" y="436" fill="#7f96b5" font-size="13" text-anchor="middle">x {pose[0]:.2f} · y {pose[1] if len(pose) > 1 else 0:.2f} · z {pose[2] if len(pose) > 2 else 0:.2f}</text>
  <text x="480" y="462" fill="#5f7695" font-size="12" text-anchor="middle">LATENCY {latency:.1f} ms · WINDOW {window} · TOKENS {tokens}</text>
  <text x="36" y="500" fill="#8ba3c2" font-size="13">{instruction}</text>
  <text x="924" y="500" fill="#4d6584" font-size="11" text-anchor="end">模拟帧 · 无原始 RGB</text>
</g>
</svg>"""
    return svg.encode("utf-8")


def frame_asset(
    db: Session, task_id: int, row_id: int, frame_index: int
) -> tuple[bytes | Path, str]:
    if frame_index < 0:
        raise AppError(PARAM_INVALID, "帧序号不能为负数")
    task, row, episode = _get_row(db, task_id, row_id)
    frames = _read_frames(task_id, row, episode.episode_id)

    image = _frame_file(task_id, episode.episode_id, frame_index)
    if image is not None:
        suffix = image.suffix.lower()
        media = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(suffix, "application/octet-stream")
        return image, media

    frame = frames[frame_index] if 0 <= frame_index < len(frames) else None
    if frame is None and frames:
        raise AppError(NOT_FOUND, "帧序号超出范围")
    return _placeholder_svg(task_id, row, episode, frame, len(frames)), "image/svg+xml"


def mask_asset(db: Session, task_id: int, row_id: int) -> Path:
    _, row, episode = _get_row(db, task_id, row_id)
    path = _mask_path(task_id, episode.episode_id)
    if path is None:
        raise AppError(NOT_FOUND, "该 episode 没有可通行区域掩膜")
    return path
