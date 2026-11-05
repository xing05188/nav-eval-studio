"""数据质量校验。

检查指令完整性、参考路径有效性、场景资产存在性与观测目录可用性，
输出按严重级别分组的问题清单，供界面逐条定位到 episode。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Dataset, Episode

LEVEL_ORDER = {"error": 0, "warn": 1, "info": 2}

CHECK_LABELS = {
    "empty_instruction": "指令为空",
    "short_instruction": "指令过短",
    "missing_reference": "缺少参考路径",
    "zero_traj_len": "轨迹长度为零",
    "missing_scene_asset": "场景资产缺失",
    "missing_observations": "观测目录缺失",
}


def _issue(level: str, code: str, episode: Episode | None, message: str, hint: str = "") -> dict:
    return {
        "level": level,
        "code": code,
        "label": CHECK_LABELS.get(code, code),
        "episode_row_id": episode.id if episode else None,
        "episode_key": episode.episode_id if episode else None,
        "scene_id": episode.scene_id if episode else None,
        "message": message,
        "hint": hint,
    }


def _load_meta(episode: Episode) -> dict[str, Any]:
    try:
        return json.loads(episode.meta_json or "{}")
    except json.JSONDecodeError:
        return {}


def validate_dataset(db: Session, dataset: Dataset, max_issues: int = 300) -> dict[str, Any]:
    episodes = db.scalars(
        select(Episode).where(Episode.dataset_id == dataset.id).order_by(Episode.id)
    ).all()

    issues: list[dict] = []
    checked: set[str] = set()

    def add(level: str, code: str, episode: Episode, message: str, hint: str = "") -> None:
        if len(issues) >= max_issues:
            return
        key = f"{code}:{episode.id}"
        if key in checked:
            return
        checked.add(key)
        issues.append(_issue(level, code, episode, message, hint))

    for episode in episodes:
        meta = _load_meta(episode)
        reference = meta.get("reference_path") or []

        if not episode.instruction.strip():
            add("error", "empty_instruction", episode, "指令文本为空，无法用于评测")
        elif episode.instruction_len < 3:
            add("warn", "short_instruction", episode, f"指令仅 {episode.instruction_len} 个词")

        if not reference:
            add("warn", "missing_reference", episode, "元数据中没有参考路径，轨迹类指标不可用")

        if episode.traj_len <= 0:
            add("error", "zero_traj_len", episode, "参考路径长度为零，SPL 与 NE 无法计算")

        expected = meta.get("expected_sensors") or []
        obs_dir = Path(dataset.root_path).expanduser() / "observations" / episode.episode_id
        missing = [name for name in expected if not (obs_dir / name).exists()]
        if missing and not (obs_dir.exists()):
            add(
                "info",
                "missing_observations",
                episode,
                f"未找到观测目录（期望传感器：{', '.join(missing)}）",
                "如需回放多源观测，请在数据集目录下放置 observations/<episode_id>/",
            )

    # 场景资产检查（仅在配置了 scene_root 时执行）
    meta = json.loads(dataset.meta_json or "{}")
    scene_root = meta.get("scene_root") or ""
    scenes = sorted({episode.scene_id for episode in episodes})
    missing_scenes: list[str] = []
    if scene_root:
        base = Path(scene_root).expanduser()
        if not base.exists():
            issues.append(
                {
                    "level": "warn",
                    "code": "missing_scene_asset",
                    "label": CHECK_LABELS["missing_scene_asset"],
                    "episode_row_id": None,
                    "episode_key": None,
                    "scene_id": None,
                    "message": f"场景根目录不存在：{base}",
                    "hint": "在数据集详情中修改场景根目录，或忽略该项",
                }
            )
        else:
            for scene in scenes:
                if not any((base / scene).glob(f"{scene}.glb")) and not (base / scene).exists():
                    missing_scenes.append(scene)
            for scene in missing_scenes[:50]:
                issues.append(
                    {
                        "level": "error",
                        "code": "missing_scene_asset",
                        "label": CHECK_LABELS["missing_scene_asset"],
                        "episode_row_id": None,
                        "episode_key": None,
                        "scene_id": scene,
                        "message": f"场景 {scene} 在 {base} 下不存在",
                        "hint": "检查 HM3D / Matterport3D 资产是否已下载",
                    }
                )

    by_level = {"error": 0, "warn": 0, "info": 0}
    by_code: dict[str, int] = {}
    for item in issues:
        by_level[item["level"]] = by_level.get(item["level"], 0) + 1
        by_code[item["code"]] = by_code.get(item["code"], 0) + 1

    issues.sort(key=lambda item: (LEVEL_ORDER.get(item["level"], 9), item["code"]))

    passed = by_level["error"] == 0 and by_level["warn"] == 0
    return {
        "dataset_id": dataset.id,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_episodes": len(episodes),
        "scenes": len(scenes),
        "passed": passed,
        "summary": by_level,
        "by_code": by_code,
        "issues": issues,
        "truncated": len(issues) >= max_issues,
    }
