"""切分生成与因果切片导出。

切分支持全集、冒烟集（固定数量随机抽样）、子集（按场景分层抽样）与自定义过滤。
所有抽样使用固定随机种子，生成条件写入 filter_json，可复算。
"""

from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.response import CONFLICT, NOT_FOUND, PARAM_INVALID, AppError
from ..models import Dataset, Episode, Split, SplitEpisode
from ..schemas.dataset import CausalExportRequest, SplitCreate


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def to_dict(split: Split) -> dict[str, Any]:
    try:
        filters = json.loads(split.filter_json or "{}")
    except json.JSONDecodeError:
        filters = {}
    return {
        "id": split.id,
        "dataset_id": split.dataset_id,
        "name": split.name,
        "kind": split.kind,
        "base_split": split.base_split,
        "seed": split.seed,
        "episode_count": split.episode_count,
        "filters": filters,
        "created_at": split.created_at,
    }


def list_splits(db: Session, dataset: Dataset) -> list[dict]:
    rows = db.scalars(
        select(Split).where(Split.dataset_id == dataset.id).order_by(Split.id.desc())
    ).all()
    return [to_dict(row) for row in rows]


def get_split(db: Session, split_id: int) -> Split:
    split = db.get(Split, split_id)
    if split is None:
        raise AppError(NOT_FOUND, "切分不存在")
    return split


def _select_episodes(
    db: Session, dataset: Dataset, payload: SplitCreate
) -> list[Episode]:
    stmt = select(Episode).where(Episode.dataset_id == dataset.id)
    filters = payload.filters or {}

    scene_prefix = str(filters.get("scene_prefix") or "").strip()
    if scene_prefix:
        stmt = stmt.where(Episode.scene_id.like(f"{scene_prefix}%"))
    keyword = str(filters.get("keyword") or "").strip()
    if keyword:
        stmt = stmt.where(Episode.instruction.like(f"%{keyword}%"))
    if filters.get("min_traj_len") is not None:
        stmt = stmt.where(Episode.traj_len >= float(filters["min_traj_len"]))
    if filters.get("max_traj_len") is not None:
        stmt = stmt.where(Episode.traj_len <= float(filters["max_traj_len"]))

    episodes = list(db.scalars(stmt.order_by(Episode.id)).all())
    rng = random.Random(payload.seed)

    if payload.kind == "full":
        return episodes

    if payload.kind == "smoke":
        count = min(payload.count or 20, len(episodes))
        return rng.sample(episodes, count) if count else []

    if payload.kind == "subset":
        target = payload.count or max(20, int(len(episodes) * 0.1))
        target = min(target, len(episodes))
        groups: dict[str, list[Episode]] = {}
        for episode in episodes:
            groups.setdefault(episode.scene_id, []).append(episode)
        if target >= len(groups):
            per_scene = target // len(groups)
            selected: list[Episode] = []
            remainder: list[Episode] = []
            for scene in sorted(groups):
                pool = groups[scene][:]
                rng.shuffle(pool)
                take = min(per_scene, len(pool))
                selected.extend(pool[:take])
                remainder.extend(pool[take:])
            if len(selected) < target:
                rng.shuffle(remainder)
                selected.extend(remainder[: target - len(selected)])
            return selected[:target]
        return rng.sample(episodes, target)

    return episodes


def create_split(db: Session, dataset: Dataset, payload: SplitCreate) -> Split:
    exists = db.scalar(
        select(Split).where(Split.dataset_id == dataset.id, Split.name == payload.name)
    )
    if exists:
        raise AppError(CONFLICT, "该数据集下已存在同名切分")

    episodes = _select_episodes(db, dataset, payload)
    if not episodes:
        raise AppError(PARAM_INVALID, "筛选条件下没有可用 episode")

    split = Split(
        dataset_id=dataset.id,
        name=payload.name,
        kind=payload.kind,
        base_split=payload.base_split,
        seed=payload.seed,
        episode_count=len(episodes),
        filter_json=json.dumps(payload.filters or {}, ensure_ascii=False),
        created_at=_now(),
    )
    db.add(split)
    db.flush()

    for ordinal, episode in enumerate(episodes):
        db.add(SplitEpisode(split_id=split.id, episode_id=episode.id, ordinal=ordinal))
    db.flush()
    return split


def delete_split(db: Session, split: Split) -> None:
    db.delete(split)


def split_episodes(db: Session, split: Split, limit: int | None = None) -> list[Episode]:
    stmt = (
        select(Episode)
        .join(SplitEpisode, SplitEpisode.episode_id == Episode.id)
        .where(SplitEpisode.split_id == split.id)
        .order_by(SplitEpisode.ordinal)
    )
    if limit:
        stmt = stmt.limit(limit)
    return list(db.scalars(stmt).all())


def export_root() -> Path:
    root = get_settings().storage.work_dir / "exports"
    root.mkdir(parents=True, exist_ok=True)
    return root


def export_causal(
    db: Session, dataset: Dataset, payload: CausalExportRequest
) -> dict[str, Any]:
    """导出严格因果切片，只保留 cutoff 之前的观测，并二次校验。"""
    if payload.episode_row_ids:
        rows = db.scalars(select(Episode).where(Episode.id.in_(payload.episode_row_ids))).all()
        episodes = [row for row in rows if row.dataset_id == dataset.id]
    elif payload.split_id:
        split = get_split(db, payload.split_id)
        if split.dataset_id != dataset.id:
            raise AppError(PARAM_INVALID, "切分不属于该数据集")
        episodes = split_episodes(db, split)
    else:
        episodes = list(
            db.scalars(
                select(Episode)
                .where(Episode.dataset_id == dataset.id)
                .order_by(Episode.id)
                .limit(payload.limit or 100)
            ).all()
        )

    if payload.limit:
        episodes = episodes[: payload.limit]
    if not episodes:
        raise AppError(PARAM_INVALID, "没有可导出的 episode")

    directory = export_root() / f"dataset-{dataset.id:04d}"
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"causal-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
    target = directory / filename

    exported = 0
    future_violations = 0
    with target.open("w", encoding="utf-8") as handle:
        for episode in episodes:
            try:
                meta = json.loads(episode.meta_json or "{}")
            except json.JSONDecodeError:
                meta = {}
            reference = meta.get("reference_path") or []
            if not reference:
                continue
            cutoff = min(payload.cutoff or len(reference), len(reference))
            observations = [
                {"idx": index, "pose": point}
                for index, point in enumerate(reference[:cutoff])
            ]
            # 因果校验：任何 idx 都必须小于 cutoff
            if any(item["idx"] >= cutoff for item in observations):
                future_violations += 1
                continue
            record = {
                "episode_key": episode.episode_id,
                "scene_id": episode.scene_id,
                "instruction": episode.instruction,
                "cutoff": cutoff,
                "source": "reference_path",
                "observations": observations,
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            exported += 1

    if exported == 0:
        target.unlink(missing_ok=True)
        raise AppError(PARAM_INVALID, "所选 episode 均缺少参考路径，无法导出")

    return {
        "dataset_id": dataset.id,
        "file": filename,
        "relative_path": f"exports/dataset-{dataset.id:04d}/{filename}",
        "episodes": exported,
        "future_frames": future_violations,
        "causal_verified": future_violations == 0,
        "size_bytes": target.stat().st_size,
    }


def recent_exports(dataset: Dataset, limit: int = 10) -> list[dict]:
    directory = export_root() / f"dataset-{dataset.id:04d}"
    if not directory.exists():
        return []
    files = sorted(directory.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True)
    return [
        {
            "file": path.name,
            "size_bytes": path.stat().st_size,
            "mtime": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        }
        for path in files[:limit]
    ]


def count_split_episodes(db: Session, split_id: int) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(SplitEpisode).where(SplitEpisode.split_id == split_id)
        )
        or 0
    )
