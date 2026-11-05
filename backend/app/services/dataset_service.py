"""数据集服务：登记、扫描、检索与观测数据组织。

支持三种数据组织方式：
1. Habitat episode 列表（R2R-CE 的 `{"episodes": [...]}`）
2. RxR 的 guide + follower_gt 双文件（指令在 guide，轨迹在 *_gt）
3. JSONL，每行一个 episode
"""

from __future__ import annotations

import gzip
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.response import CONFLICT, NOT_FOUND, PARAM_INVALID, AppError
from ..models import Dataset, Episode, Split, SplitEpisode
from ..schemas.dataset import DatasetCreate, DatasetUpdate
from ..utils.geometry import as_point, path_length, pose_from, project_2d, bounds

SCENE_SUFFIXES = (".glb", ".navmesh", ".basis.glb")


# ---------------------------------------------------------------- 读取与解析


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_json(path: Path) -> Any:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _load_jsonl(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    rows: list[dict] = []
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def discover_files(root: Path, kind: str) -> list[Path]:
    """在目录中找出可解析的 episode 文件。"""
    if root.is_file():
        return [root]
    if not root.exists():
        return []

    candidates = sorted(
        {path for pattern in ("*.jsonl", "*.json", "*.json.gz") for path in root.glob(pattern)}
    )
    files: list[Path] = []
    for path in candidates:
        name = path.name.lower()
        if "_gt." in name:
            continue
        if kind == "rxr_ce" and "guide" not in name:
            continue
        files.append(path)
    return files


def extract_episodes(path: Path) -> list[dict]:
    """把不同格式统一成 episode 字典列表。"""
    if path.suffix == ".jsonl" or path.name.endswith(".jsonl.gz"):
        return _load_jsonl(path)

    try:
        data = _load_json(path)
    except json.JSONDecodeError:
        # 某些结果文件是 JSONL 但扩展名为 .json
        return _load_jsonl(path)

    if isinstance(data, dict) and isinstance(data.get("episodes"), list):
        return data["episodes"]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        # 形如 {episode_id: {"locations": [...], "instruction": ...}}
        items = []
        for key, value in data.items():
            if isinstance(value, dict):
                items.append({**value, "episode_id": value.get("episode_id", key)})
        return items
    return []


def _instruction_text(raw: Any) -> str:
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        for key in ("instruction_text", "text", "instruction"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    if isinstance(raw, list):
        parts = [_instruction_text(item) for item in raw]
        return " ".join(part for part in parts if part).strip()
    return ""


def _scene_short(scene_id: str) -> str:
    name = scene_id.strip()
    for suffix in SCENE_SUFFIXES:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.split("/")[-1] or name


def _reference_points(raw: Any) -> list[list[float]]:
    if not isinstance(raw, list):
        return []
    points: list[list[float]] = []
    for item in raw:
        if isinstance(item, dict):
            position = item.get("position") or item.get("translation")
        else:
            position = item
        point = as_point(position)
        if point:
            points.append(point)
    return points


def _goal_position(raw: Any) -> list[float]:
    goals = raw.get("goals") if isinstance(raw, dict) else None
    if isinstance(goals, list):
        for goal in goals:
            if isinstance(goal, dict):
                point = as_point(goal.get("position"))
                if point:
                    return point
    return []


def _round_points(points: Iterable[list[float]], limit: int = 400) -> list[list[float]]:
    return [[round(float(value), 3) for value in point[:3]] for point in list(points)[:limit]]


def normalize_episode(raw: dict, kind: str) -> dict[str, Any] | None:
    episode_key = raw.get("episode_id", raw.get("id", raw.get("trajectory_id")))
    if episode_key is None:
        return None

    scene_raw = str(raw.get("scene_id") or raw.get("scene") or "")
    reference = _reference_points(raw.get("reference_path") or raw.get("locations"))
    goal = _goal_position(raw) or (reference[-1] if reference else [])
    start = as_point(raw.get("start_position")) or (reference[0] if reference else [])

    info = raw.get("info") if isinstance(raw.get("info"), dict) else {}
    traj_len = path_length(reference)
    if not traj_len and isinstance(info.get("geodesic_distance"), (int, float)):
        traj_len = round(float(info["geodesic_distance"]), 3)

    instruction = _instruction_text(raw.get("instruction"))
    meta = {
        "trajectory_id": raw.get("trajectory_id"),
        "role": info.get("role"),
        "geodesic_distance": info.get("geodesic_distance"),
        "goal_radius": (raw.get("goals") or [{}])[0].get("radius")
        if isinstance(raw.get("goals"), list) and raw.get("goals")
        else None,
        "raw_scene_id": scene_raw,
        "raw_instruction": raw.get("instruction")
        if not isinstance(raw.get("instruction"), str)
        else None,
    }

    return {
        "episode_id": str(episode_key),
        "scene_id": _scene_short(scene_raw),
        "instruction": instruction,
        "instruction_len": len(instruction.split()),
        "traj_len": traj_len,
        "duration_s": 0.0,
        "start_pose_json": json.dumps(pose_from(start, raw.get("start_rotation"))),
        "goal_pose_json": json.dumps(pose_from(goal)),
        "has_depth": 0,
        "meta_json": json.dumps(meta, ensure_ascii=False),
        "_reference": reference,
    }


def _rxr_trajectories(root: Path) -> dict[str, list[list[float]]]:
    """RxR：从 *_follower_gt.json.gz 中读取各 episode 的轨迹点。"""
    directory = root if root.is_dir() else root.parent
    result: dict[str, list[list[float]]] = {}
    for path in directory.glob("*_gt.json.gz"):
        try:
            data = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        for key, value in data.items():
            if isinstance(value, dict):
                points = _reference_points(value.get("locations"))
                if points:
                    result[str(key)] = points
    return result


def _observation_dir(root: Path, episode_key: str) -> Path:
    base = root if root.is_dir() else root.parent
    return base / "observations" / episode_key


def _has_depth_frames(root: Path, episode_key: str) -> bool:
    directory = _observation_dir(root, episode_key) / "depth"
    if not directory.exists():
        return False
    return any(directory.iterdir())


# ---------------------------------------------------------------- 数据集 CRUD


def _parse_meta(dataset: Dataset) -> dict[str, Any]:
    try:
        return json.loads(dataset.meta_json or "{}")
    except json.JSONDecodeError:
        return {}


def to_dict(dataset: Dataset) -> dict[str, Any]:
    meta = _parse_meta(dataset)
    return {
        "id": dataset.id,
        "name": dataset.name,
        "version": dataset.version,
        "kind": dataset.kind,
        "root_path": dataset.root_path,
        "instruction_lang": dataset.instruction_lang,
        "scene_count": dataset.scene_count,
        "episode_count": dataset.episode_count,
        "status": dataset.status,
        "last_scan_at": dataset.last_scan_at,
        "meta": meta,
        "note": meta.get("note", ""),
        "created_at": dataset.created_at,
        "updated_at": dataset.updated_at,
    }


def list_datasets(
    db: Session, kind: str | None = None, status: str | None = None, q: str | None = None
) -> list[dict]:
    stmt = select(Dataset).order_by(Dataset.id.desc())
    if kind:
        stmt = stmt.where(Dataset.kind == kind)
    if status:
        stmt = stmt.where(Dataset.status == status)
    if q:
        stmt = stmt.where(or_(Dataset.name.like(f"%{q}%"), Dataset.root_path.like(f"%{q}%")))
    return [to_dict(item) for item in db.scalars(stmt).all()]


def get_dataset(db: Session, dataset_id: int) -> Dataset:
    dataset = db.get(Dataset, dataset_id)
    if dataset is None:
        raise AppError(NOT_FOUND, "数据集不存在")
    return dataset


def create_dataset(db: Session, payload: DatasetCreate, username: str = "") -> Dataset:
    exists = db.scalar(
        select(Dataset).where(Dataset.name == payload.name, Dataset.version == payload.version)
    )
    if exists:
        raise AppError(CONFLICT, "同名同版本的数据集已存在")

    root = Path(payload.root_path).expanduser()
    meta = {
        "scene_root": payload.scene_root,
        "note": payload.note,
        "created_by": username,
        "format": "",
        "files": [],
    }
    dataset = Dataset(
        name=payload.name,
        version=payload.version,
        kind=payload.kind,
        root_path=str(root),
        instruction_lang=payload.instruction_lang,
        scene_count=0,
        episode_count=0,
        status="unknown",
        meta_json=json.dumps(meta, ensure_ascii=False),
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(dataset)
    db.flush()
    return dataset


def update_dataset(db: Session, dataset: Dataset, payload: DatasetUpdate) -> Dataset:
    meta = _parse_meta(dataset)
    if payload.name is not None:
        dataset.name = payload.name
    if payload.version is not None:
        dataset.version = payload.version
    if payload.instruction_lang is not None:
        dataset.instruction_lang = payload.instruction_lang
    if payload.root_path is not None:
        dataset.root_path = str(Path(payload.root_path).expanduser())
        dataset.status = "unknown"
        dataset.episode_count = 0
        dataset.scene_count = 0
    if payload.scene_root is not None:
        meta["scene_root"] = payload.scene_root
    if payload.note is not None:
        meta["note"] = payload.note
    dataset.meta_json = json.dumps(meta, ensure_ascii=False)
    dataset.updated_at = _now()
    return dataset


def delete_dataset(db: Session, dataset: Dataset) -> None:
    referenced = db.scalar(
        select(func.count()).select_from(Split).where(Split.dataset_id == dataset.id)
    )
    if referenced:
        raise AppError(CONFLICT, "该数据集下仍有切分记录，请先删除切分")
    db.delete(dataset)


# ---------------------------------------------------------------- 扫描


def scan_dataset(db: Session, dataset: Dataset) -> dict[str, Any]:
    root = Path(dataset.root_path).expanduser()
    warnings: list[str] = []

    if not root.exists():
        dataset.status = "missing"
        dataset.updated_at = _now()
        raise AppError(NOT_FOUND, f"数据集路径不存在：{root}")

    files = discover_files(root, dataset.kind)
    if not files:
        dataset.status = "invalid"
        dataset.updated_at = _now()
        raise AppError(PARAM_INVALID, "未找到可解析的 episode 文件（*.json / *.jsonl / *.json.gz）")

    raw_episodes: list[dict] = []
    for path in files:
        try:
            raw_episodes.extend(extract_episodes(path))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"{path.name} 解析失败：{exc}")

    rxr_tracks: dict[str, list[list[float]]] = {}
    if dataset.kind == "rxr_ce":
        rxr_tracks = _rxr_trajectories(root)
        if not rxr_tracks:
            warnings.append("未找到 *_follower_gt.json.gz，RxR 轨迹可能为空")

    normalized: list[dict[str, Any]] = []
    skipped = 0
    for raw in raw_episodes:
        item = normalize_episode(raw, dataset.kind)
        if item is None:
            skipped += 1
            continue
        if dataset.kind == "rxr_ce" and item["episode_id"] in rxr_tracks:
            reference = rxr_tracks[item["episode_id"]]
            item["_reference"] = reference
            item["traj_len"] = path_length(reference)
            if not json.loads(item["start_pose_json"]):
                item["start_pose_json"] = json.dumps(pose_from(reference[0]))
            if not json.loads(item["goal_pose_json"]):
                item["goal_pose_json"] = json.dumps(pose_from(reference[-1]))
        item["has_depth"] = 1 if _has_depth_frames(root, item["episode_id"]) else 0
        meta = json.loads(item["meta_json"])
        meta["reference_path"] = _round_points(item.pop("_reference"))
        item["meta_json"] = json.dumps(meta, ensure_ascii=False)
        normalized.append(item)

    if not normalized:
        dataset.status = "invalid"
        dataset.updated_at = _now()
        raise AppError(PARAM_INVALID, "未解析出任何 episode，请检查数据格式")

    existing = {
        row.episode_id: row
        for row in db.scalars(select(Episode).where(Episode.dataset_id == dataset.id)).all()
    }

    inserted = updated = 0
    seen: set[str] = set()
    for item in normalized:
        key = item["episode_id"]
        if key in seen:
            continue
        seen.add(key)
        row = existing.get(key)
        if row is None:
            db.add(
                Episode(
                    dataset_id=dataset.id,
                    episode_id=key,
                    scene_id=item["scene_id"],
                    instruction=item["instruction"],
                    instruction_len=item["instruction_len"],
                    traj_len=item["traj_len"],
                    duration_s=item["duration_s"],
                    start_pose_json=item["start_pose_json"],
                    goal_pose_json=item["goal_pose_json"],
                    has_depth=item["has_depth"],
                    meta_json=item["meta_json"],
                )
            )
            inserted += 1
        else:
            row.scene_id = item["scene_id"]
            row.instruction = item["instruction"]
            row.instruction_len = item["instruction_len"]
            row.traj_len = item["traj_len"]
            row.start_pose_json = item["start_pose_json"]
            row.goal_pose_json = item["goal_pose_json"]
            row.has_depth = item["has_depth"]
            row.meta_json = item["meta_json"]
            updated += 1

    stale_ids = [row.id for key, row in existing.items() if key not in seen]
    for chunk_start in range(0, len(stale_ids), 400):
        chunk = stale_ids[chunk_start : chunk_start + 400]
        for row in db.scalars(select(Episode).where(Episode.id.in_(chunk))).all():
            db.delete(row)

    db.flush()

    scene_count = db.scalar(
        select(func.count(func.distinct(Episode.scene_id))).where(Episode.dataset_id == dataset.id)
    ) or 0
    episode_count = db.scalar(
        select(func.count()).select_from(Episode).where(Episode.dataset_id == dataset.id)
    ) or 0

    dataset.scene_count = scene_count
    dataset.episode_count = episode_count
    dataset.status = "ready" if episode_count else "invalid"
    dataset.last_scan_at = _now()
    dataset.updated_at = _now()

    meta = _parse_meta(dataset)
    meta["format"] = "habitat-episodes" if files[0].suffix != ".jsonl" else "jsonl"
    meta["files"] = [str(path) for path in files]
    meta["last_scan"] = {
        "parsed": len(normalized),
        "skipped": skipped,
        "inserted": inserted,
        "updated": updated,
        "removed": len(stale_ids),
        "warnings": warnings,
    }
    dataset.meta_json = json.dumps(meta, ensure_ascii=False)

    return {
        "dataset_id": dataset.id,
        "files": [path.name for path in files],
        "parsed": len(normalized),
        "skipped": skipped,
        "inserted": inserted,
        "updated": updated,
        "removed": len(stale_ids),
        "scene_count": scene_count,
        "episode_count": episode_count,
        "warnings": warnings,
    }


# ---------------------------------------------------------------- Episode


def _episode_to_brief(row: Episode) -> dict[str, Any]:
    return {
        "id": row.id,
        "episode_key": row.episode_id,
        "scene_id": row.scene_id,
        "instruction": row.instruction,
        "instruction_len": row.instruction_len,
        "traj_len": row.traj_len,
        "duration_s": row.duration_s,
        "has_depth": bool(row.has_depth),
        "start_pose": json.loads(row.start_pose_json or "[]"),
        "goal_pose": json.loads(row.goal_pose_json or "[]"),
    }


def list_episodes(
    db: Session,
    dataset: Dataset,
    q: str | None = None,
    scene: str | None = None,
    min_len: float | None = None,
    max_len: float | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    conditions = [Episode.dataset_id == dataset.id]
    if q:
        conditions.append(Episode.instruction.like(f"%{q}%"))
    if scene:
        conditions.append(Episode.scene_id == scene)
    if min_len is not None:
        conditions.append(Episode.traj_len >= min_len)
    if max_len is not None:
        conditions.append(Episode.traj_len <= max_len)

    total = db.scalar(select(func.count()).select_from(Episode).where(*conditions)) or 0
    rows = db.scalars(
        select(Episode)
        .where(*conditions)
        .order_by(Episode.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [_episode_to_brief(row) for row in rows], total


def get_episode(db: Session, dataset: Dataset, row_id: int) -> Episode:
    row = db.get(Episode, row_id)
    if row is None or row.dataset_id != dataset.id:
        raise AppError(NOT_FOUND, "Episode 不存在")
    return row


def _read_pose_file(path: Path) -> list[list[float]]:
    points: list[list[float]] = []
    if not path.exists():
        return points
    for row in _load_jsonl(path):
        pose = as_point(row.get("position") or row.get("pose"))
        if pose:
            points.append(pose)
    return points


def build_observations(dataset: Dataset, episode: Episode) -> dict[str, Any]:
    """组织多源观测时间轴数据；无帧文件时退化为参考路径。"""
    root = Path(dataset.root_path).expanduser()
    obs_dir = _observation_dir(root, episode.episode_id)
    meta = json.loads(episode.meta_json or "{}")

    rgb_dir = obs_dir / "rgb"
    depth_dir = obs_dir / "depth"
    rgb_files = sorted(rgb_dir.glob("*.jpg")) if rgb_dir.exists() else []
    depth_files = sorted(depth_dir.glob("*.png")) if depth_dir.exists() else []
    pose_points = _read_pose_file(obs_dir / "poses.jsonl")

    reference = _reference_points(
        meta.get("reference_path") or []
    )
    if not reference:
        reference = pose_points

    total = max(len(reference), len(rgb_files), len(depth_files), len(pose_points))
    timeline: list[dict[str, Any]] = []
    for index in range(total):
        pose = pose_points[index] if index < len(pose_points) else (
            reference[index] if index < len(reference) else []
        )
        timeline.append(
            {
                "idx": index,
                "t": round(index * 0.5, 2),
                "pose": pose,
                "rgb": index < len(rgb_files),
                "depth": index < len(depth_files),
                "action": None,
            }
        )

    sensors = {
        "rgb": bool(rgb_files),
        "depth": bool(depth_files),
        "pose": bool(pose_points or reference),
        "action": False,
    }

    return {
        "episode": {
            "id": episode.id,
            "episode_key": episode.episode_id,
            "scene_id": episode.scene_id,
            "instruction": episode.instruction,
            "instruction_len": episode.instruction_len,
            "traj_len": episode.traj_len,
        },
        "sensors": sensors,
        "timeline": timeline,
        "reference_path": project_2d(reference) if reference else [],
        "bounds": bounds(reference) if reference else {},
        "counts": {
            "frames_rgb": len(rgb_files),
            "frames_depth": len(depth_files),
            "poses": len(pose_points or reference),
        },
        "source": "observations" if (rgb_files or depth_files or pose_points) else "reference_path",
    }


def frame_path(dataset: Dataset, episode: Episode, index: int, kind: str = "rgb") -> Path:
    root = Path(dataset.root_path).expanduser()
    obs_dir = _observation_dir(root, episode.episode_id)
    pattern = "*.jpg" if kind == "rgb" else "*.png"
    files = sorted((obs_dir / kind).glob(pattern))
    if index < 0 or index >= len(files):
        raise AppError(NOT_FOUND, "帧序号超出范围")
    return files[index]


def episode_detail(db: Session, dataset: Dataset, row: Episode) -> dict[str, Any]:
    brief = _episode_to_brief(row)
    meta = json.loads(row.meta_json or "{}")
    root = Path(dataset.root_path).expanduser()
    obs_dir = _observation_dir(root, row.episode_id)

    reference = _reference_points(meta.get("reference_path") or [])
    if not reference:
        reference = _read_pose_file(obs_dir / "poses.jsonl")

    brief.update(
        {
            "reference_path": project_2d(reference) if reference else [],
            "sensors": {
                "rgb": (obs_dir / "rgb").exists(),
                "depth": (obs_dir / "depth").exists(),
                "pose": bool(reference),
                "action": (obs_dir / "actions.jsonl").exists(),
            },
            "meta": meta,
        }
    )
    return brief


def scene_options(db: Session, dataset: Dataset, limit: int = 200) -> list[dict]:
    rows = db.execute(
        select(Episode.scene_id, func.count())
        .where(Episode.dataset_id == dataset.id)
        .group_by(Episode.scene_id)
        .order_by(func.count().desc())
        .limit(limit)
    ).all()
    return [{"scene_id": scene, "count": count} for scene, count in rows]


def dataset_stats(db: Session, dataset: Dataset) -> dict[str, Any]:
    rows = db.execute(
        select(
            func.count(),
            func.avg(Episode.instruction_len),
            func.avg(Episode.traj_len),
            func.min(Episode.traj_len),
            func.max(Episode.traj_len),
            func.sum(Episode.has_depth),
        ).where(Episode.dataset_id == dataset.id)
    ).one()

    splits = db.scalars(select(Split).where(Split.dataset_id == dataset.id)).all()
    return {
        "episode_count": rows[0] or 0,
        "avg_instruction_len": round(float(rows[1] or 0), 1),
        "avg_traj_len": round(float(rows[2] or 0), 2),
        "min_traj_len": round(float(rows[3] or 0), 2),
        "max_traj_len": round(float(rows[4] or 0), 2),
        "episodes_with_depth": int(rows[5] or 0),
        "scene_count": dataset.scene_count,
        "splits": len(splits),
    }
