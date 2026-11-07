"""数据库里的 episode → 仿真配置（SimSpec）。

位姿解析是这里最容易出错的地方，实际的库内形状见 docs/07 §5：
- `start_pose_json` / `goal_pose_json` 都是 **一维 list `[x, y, z, yaw]`**（yaw 为弧度）；
  历史上备份库里有写成 dict 的样本，所以解析侧两种都兼容。
- `scene_id` 是短名（`zsNo4HB9uLZ`），真实文件在 `{scene_root}/mp3d/{scene_id}/{scene_id}.glb`。
- `meta_json.raw_scene_id` 是原始相对路径（`mp3d/zsNo4HB9uLZ/zsNo4HB9uLZ.glb`），优先用它拼。
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.response import NOT_FOUND, PARAM_INVALID, AppError
from ...models import Dataset, Episode
from . import constants as C


@dataclass
class SimSpec:
    """一局仿真的完整配置（与旧脚本 SimConfig 字段对齐，去掉了 split/自定义）。"""

    episode_id: int
    dataset_id: int
    dataset_name: str
    episode_code: str
    scene_id: str
    scene_path: str
    start_position: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    start_rotation: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 1.0])
    goal: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    radius: float = C.SUCCESS_DIST
    instruction: str = ""

    @property
    def scene_label(self) -> str:
        return os.path.basename(self.scene_path).replace(".glb", "")

    def as_dict(self) -> dict[str, Any]:
        """给前端的预览信息（不含本机绝对路径，避免泄露目录结构）。"""
        return {
            "episode_id": self.episode_id,
            "dataset_id": self.dataset_id,
            "dataset_name": self.dataset_name,
            "episode_code": self.episode_code,
            "scene": self.scene_label,
            "scene_id": self.scene_id,
            "instruction": self.instruction,
            "radius": round(self.radius, 2),
            "start": [round(float(v), 2) for v in self.start_position],
            "goal": [round(float(v), 2) for v in self.goal],
        }


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    return []


def parse_pose(raw: str, *, with_yaw: bool) -> tuple[list[float], float] | None:
    """把 pose_json 解析成 `([x, y, z], yaw)`；无法解析时返回 None。

    兼容三种写法：
    - `[x, y, z, yaw]`（平台写入的格式）
    - `[x, y, z]`
    - `{"position": [x, y, z], "rotation": [x, y, z, w]}` 或 `{"x":..,"y":..,"z":..,"yaw":..}`
    """
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    if not data:
        return None

    if isinstance(data, dict):
        if "position" in data:
            pos = [float(v) for v in _as_list(data["position"])[:3]]
            yaw = 0.0
            rot = _as_list(data.get("rotation") or [])
            if len(rot) >= 4:  # xyzw
                yaw = 2.0 * math.atan2(float(rot[1]), float(rot[3]))
            elif "yaw" in data:
                yaw = float(data["yaw"])
        else:
            try:
                pos = [float(data["x"]), float(data["y"]), float(data["z"])]
            except (KeyError, TypeError, ValueError):
                return None
            yaw = float(data.get("yaw", 0.0) or 0.0)
    else:
        seq = _as_list(data)
        if len(seq) < 3:
            return None
        try:
            pos = [float(seq[0]), float(seq[1]), float(seq[2])]
            yaw = float(seq[3]) if (with_yaw and len(seq) > 3) else 0.0
        except (TypeError, ValueError):
            return None
    if not all(math.isfinite(v) for v in pos) or not math.isfinite(yaw):
        return None
    return pos, yaw


def yaw_to_quaternion(yaw: float) -> list[float]:
    """绕 Y 轴的 yaw（弧度）→ scalar-last 四元数 `[x, y, z, w]`（R2R 写法）。"""
    half = float(yaw) / 2.0
    return [0.0, math.sin(half), 0.0, math.cos(half)]


def scene_candidates(scene_id: str, raw_scene_id: str, dataset_meta: dict) -> list[str]:
    """按优先级列出可能的场景绝对路径（存在的第一个就是答案）。"""
    settings = get_settings()
    roots: list[str] = []
    configured = settings.sim.scene_root
    if configured:
        roots.append(str(configured))
    meta_root = str(dataset_meta.get("scene_root") or "").strip()
    if meta_root:
        roots.append(meta_root)
    backup_root = str(dataset_meta.get("backup_root") or "").strip()
    if not backup_root:
        backup_root = str(settings.imports.backup_root)
    roots.append(os.path.join(backup_root, "data", "scene_datasets"))
    # 去掉后出现的重复项，保持优先级
    unique_roots: list[str] = []
    for root in roots:
        if root and root not in unique_roots:
            unique_roots.append(root)

    names: list[str] = []
    if raw_scene_id:
        names.append(raw_scene_id)
    names.append(os.path.join("mp3d", scene_id, f"{scene_id}.glb"))
    names.append(os.path.join(scene_id, f"{scene_id}.glb"))
    names.append(f"{scene_id}.glb")

    out: list[str] = []
    for root in unique_roots:
        for name in names:
            path = os.path.normpath(os.path.join(root, name))
            if path not in out:
                out.append(path)
    return out


def resolve_scene_path(scene_id: str, raw_scene_id: str, dataset_meta: dict) -> str:
    candidates = scene_candidates(scene_id, raw_scene_id, dataset_meta)
    for path in candidates:
        if os.path.isfile(path):
            return path
    hint = candidates[0] if candidates else scene_id
    raise AppError(
        NOT_FOUND,
        f"场景文件缺失：{scene_id}（已尝试 {len(candidates)} 个路径，例如 {hint}）。"
        "请确认场景数据集已下载，或在 config/default.yaml 的 sim.scene_root 指向正确目录。",
        http_status=404,
    )


def spec_from_episode(db: Session, episode_id: int) -> SimSpec:
    """读取 episode 行，构造可交给引擎的 SimSpec。"""
    episode = db.get(Episode, int(episode_id))
    if episode is None:
        raise AppError(NOT_FOUND, f"episode 不存在：{episode_id}", http_status=404)
    dataset = db.get(Dataset, int(episode.dataset_id))
    dataset_meta: dict = {}
    if dataset is not None:
        try:
            dataset_meta = json.loads(dataset.meta_json or "{}") or {}
        except (TypeError, ValueError):
            dataset_meta = {}

    episode_meta: dict = {}
    try:
        episode_meta = json.loads(episode.meta_json or "{}") or {}
    except (TypeError, ValueError):
        episode_meta = {}

    start = parse_pose(episode.start_pose_json, with_yaw=True)
    goal = parse_pose(episode.goal_pose_json, with_yaw=False)
    if start is None:
        raise AppError(
            PARAM_INVALID,
            f"episode {episode_id} 缺少可用的起点位姿（start_pose_json={episode.start_pose_json!r}）",
            http_status=400,
        )
    if goal is None:
        raise AppError(
            PARAM_INVALID,
            f"episode {episode_id} 缺少可用的终点位姿（goal_pose_json={episode.goal_pose_json!r}）",
            http_status=400,
        )

    start_position, start_yaw = start
    goal_position, _ = goal
    scene_id = str(episode.scene_id or "").strip()
    if not scene_id:
        raise AppError(PARAM_INVALID, f"episode {episode_id} 未登记场景 id", http_status=400)

    raw_scene_id = str(episode_meta.get("raw_scene_id") or "").strip()
    scene_path = resolve_scene_path(scene_id, raw_scene_id, dataset_meta)

    radius = episode_meta.get("goal_radius")
    try:
        radius = float(radius)
    except (TypeError, ValueError):
        radius = C.SUCCESS_DIST
    if not math.isfinite(radius) or radius <= 0:
        radius = C.SUCCESS_DIST

    return SimSpec(
        episode_id=int(episode.id),
        dataset_id=int(episode.dataset_id),
        dataset_name=dataset.name if dataset is not None else "",
        episode_code=str(episode.episode_id or episode.id),
        scene_id=scene_id,
        scene_path=scene_path,
        start_position=start_position,
        start_rotation=yaw_to_quaternion(start_yaw),
        goal=goal_position,
        radius=radius,
        instruction=str(episode.instruction or "").strip(),
    )
