"""初始化种子数据。

只在对应表为空时写入，重复启动不会覆盖用户已修改的内容。
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.security import hash_password
from ..models import AppUser, ConfigTemplate, ModelProfile, Setting

DEFAULT_USERS = [
    ("admin", "管理员", "admin123", "admin"),
    ("operator", "算法工程师", "operator123", "operator"),
    ("viewer", "访客", "viewer123", "viewer"),
]

BUILTIN_TEMPLATES = [
    {
        "name": "仅视觉·固定窗口",
        "modality": "vision",
        "memory_policy": "fixed_window",
        "params": {"history_len": 8, "slow_update_interval": 4, "prune_ratio": 0.0},
        "description": "仅使用 RGB 观测，历史固定为最近 8 帧，作为最简基线。",
    },
    {
        "name": "仅视觉·滑动窗口",
        "modality": "vision",
        "memory_policy": "sliding_window",
        "params": {"history_len": 16, "slow_update_interval": 4, "prune_ratio": 0.0},
        "description": "RGB 观测配合滑动窗口上下文，窗口随推理推进滚动。",
    },
    {
        "name": "仅视觉·特征缓存",
        "modality": "vision",
        "memory_policy": "feature_cache",
        "params": {"history_len": 16, "slow_update_interval": 8, "prune_ratio": 0.2},
        "description": "RGB 观测配合特征缓存，压缩重复出现的视觉特征。",
    },
    {
        "name": "视觉+几何·空间裁剪",
        "modality": "vision_geo",
        "memory_policy": "spatial_prune",
        "params": {"history_len": 8, "slow_update_interval": 4, "prune_ratio": 0.35},
        "description": "在 RGB 基础上引入深度反投影得到的局部几何，按三维位置裁剪冗余 token。",
    },
    {
        "name": "视觉+几何+状态·空间裁剪",
        "modality": "vision_geo_state",
        "memory_policy": "spatial_prune",
        "params": {"history_len": 8, "slow_update_interval": 4, "prune_ratio": 0.35},
        "description": "完整多模态输入，叠加位姿与运动状态，配合空间裁剪的有界记忆。",
    },
    {
        "name": "视觉+几何+状态·特征缓存",
        "modality": "vision_geo_state",
        "memory_policy": "feature_cache",
        "params": {"history_len": 12, "slow_update_interval": 6, "prune_ratio": 0.25},
        "description": "完整多模态输入，以特征缓存替代空间裁剪，用于对照记忆机制差异。",
    },
    {
        "name": "视觉+几何+状态·混合记忆",
        "modality": "vision_geo_state",
        "memory_policy": "hybrid",
        "params": {"history_len": 8, "slow_update_interval": 4, "prune_ratio": 0.35, "long_term": True},
        "description": "短期滑动窗口与长期语义几何记忆并存，记忆规模有界。",
    },
]

DEFAULT_SETTINGS = {
    "max_parallel_tasks": "2",
    "artifact_keep_days": "90",
    "replay_frame_interval": "1",
    "demo_mode": "1",
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def seed_users(session: Session) -> int:
    existing = session.scalar(select(func.count()).select_from(AppUser)) or 0
    if existing:
        return 0
    created = 0
    for username, display_name, password, role in DEFAULT_USERS:
        password_hash, salt = hash_password(password)
        session.add(
            AppUser(
                username=username,
                display_name=display_name,
                password_hash=password_hash,
                password_salt=salt,
                role=role,
                enabled=1,
                created_at=_now(),
            )
        )
        created += 1
    return created


def seed_settings(session: Session, settings: Settings) -> int:
    defaults = dict(DEFAULT_SETTINGS)
    defaults["max_parallel_tasks"] = str(settings.scheduler.max_parallel_tasks)
    defaults["artifact_keep_days"] = str(settings.storage.artifact_keep_days)
    defaults["work_dir"] = str(settings.storage.work_dir)
    defaults["gpu_ids"] = ",".join(settings.scheduler.gpu_ids)
    created = 0
    for key, value in defaults.items():
        if session.get(Setting, key) is None:
            session.add(Setting(key=key, value=value, updated_at=_now()))
            created += 1
    return created


def seed_templates(session: Session) -> int:
    existing = session.scalar(select(func.count()).select_from(ConfigTemplate)) or 0
    if existing:
        return 0
    for item in BUILTIN_TEMPLATES:
        session.add(
            ConfigTemplate(
                name=item["name"],
                modality=item["modality"],
                memory_policy=item["memory_policy"],
                params_json=json.dumps(item["params"], ensure_ascii=False),
                description=item["description"],
                builtin=1,
                created_at=_now(),
            )
        )
    return len(BUILTIN_TEMPLATES)


def seed_models(session: Session, settings: Settings) -> int:
    existing = session.scalar(select(func.count()).select_from(ModelProfile)) or 0
    if existing:
        return 0
    profiles = (settings.models or {}).get("profiles", [])
    for item in profiles:
        session.add(
            ModelProfile(
                name=item["name"],
                family=item.get("family", "custom"),
                code_path=item.get("code_path", ""),
                weights_path=item.get("weights_path", ""),
                entry=item.get("entry", ""),
                default_config_json=json.dumps(item.get("default_config", {}), ensure_ascii=False),
                needs_gpu=1 if item.get("needs_gpu", True) else 0,
                allowed_inputs=",".join(item.get("allowed_inputs", ["rgb", "depth", "pose", "action"])),
                status="unknown",
                description=item.get("description", ""),
                created_at=_now(),
                updated_at=_now(),
            )
        )
    return len(profiles)


def seed_all(session: Session, settings: Settings) -> dict[str, int]:
    summary = {
        "users": seed_users(session),
        "settings": seed_settings(session, settings),
        "templates": seed_templates(session),
        "models": seed_models(session, settings),
    }
    session.commit()
    return summary
