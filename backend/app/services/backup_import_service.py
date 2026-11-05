"""备份库自动导入。

把 StreamVLN 备份仓库（代码 + data/ + results/ + research/ + checkpoints/ 等）中的
各类数据一次性同步到平台，并在启动后持续监视目录变化做增量导入：

1. `datasets`：`<root>/data/datasets/<family>/<split>` 登记为数据集，并解析 episode；
2. `scenes`：`data/scene_datasets/**/*.glb` 场景文件建立索引；
3. `models`：`checkpoints/<权重目录>` 登记/修正模型档案，自动补齐代码与权重路径；
4. `results`：复用 `import_service` 把历史评测产物还原成评测任务；
5. `assets`：配置、脚本、日志、研究文档、结果附件等登记为资料索引。

大文件只登记路径与元信息，不复制进工作目录；所有写入以 `source_key + signature`
做幂等键，`dry_run=True` 时只生成预览，不改任何表。重复导入不会覆盖用户手工登记的数据集。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

import yaml
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.config import ALL_IMPORT_SECTIONS, get_settings
from ..core.response import NOT_FOUND, PARAM_INVALID, AppError
from ..models import BackupAsset, Dataset, EvalTask, ModelProfile
from ..schemas.dataset import DatasetCreate
from ..schemas.model import ModelCreate
from . import dataset_service, import_service, model_service

SECTION_LABELS = {
    "datasets": "数据集",
    "scenes": "场景资源",
    "models": "模型档案",
    "results": "评测结果",
    "assets": "其他资料",
}

SECTION_DESCRIPTIONS = {
    "datasets": "data/datasets 下的 VLN-CE episode 目录，自动登记并解析 episode",
    "scenes": "data/scene_datasets 下的 MP3D/HM3D 场景文件，登记路径与体积",
    "models": "checkpoints 下的权重目录，自动登记或修正模型档案路径",
    "results": "results 下的历史评测产物，还原为可回放的评测任务",
    "assets": "配置、脚本、日志、研究文档、结果附件等资料文件索引",
}

SKIP_PARTS = {
    ".git",
    ".cache",
    "__pycache__",
    ".claude",
    ".ipynb_checkpoints",
    "node_modules",
    "dist",
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".so", ".o", ".a"}
MAX_INDEXED_BINARY = 64 * 1024 * 1024


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- 目录与文件发现


def resolve_root(root_path: str | Path | None = None, *, strict: bool = True) -> Path:
    """未指定根目录时回落到配置中的 backup_root / results_root。"""
    settings = get_settings()
    raw = str(root_path or settings.imports.backup_root or settings.imports.results_root)
    root = Path(raw).expanduser()
    if strict and not root.exists():
        raise AppError(NOT_FOUND, f"备份目录不存在：{root}")
    if strict and not root.is_dir():
        raise AppError(PARAM_INVALID, f"备份路径不是目录：{root}")
    return root


def iter_asset_files(root: Path) -> Iterator[Path]:
    """遍历需要索引的文件；checkpoints 常为软链，单独遍历其直接子目录。"""
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in SKIP_PARTS for part in rel.parts):
            continue
        if path.name in (".gitattributes", ".gitignore"):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        if not path.suffix and path.stat().st_size > 8 * 1024 * 1024:
            # 无扩展名的大二进制（打包代码、micromamba 等）没有检索价值
            continue
        if rel.parts and rel.parts[0] == "checkpoints":
            continue
        yield path

    checkpoints = root / "checkpoints"
    if checkpoints.is_dir():
        for entry in sorted(checkpoints.iterdir()):
            if not entry.is_dir():
                continue
            for path in sorted(entry.iterdir()):
                if not path.is_file() or path.name.startswith("."):
                    continue
                if path.stat().st_size > MAX_INDEXED_BINARY:
                    continue
                yield path


def classify(rel: Path) -> tuple[str, str]:
    """按备份库内相对路径归类，返回 (section, kind)。"""
    parts = rel.parts
    first = parts[0] if parts else ""
    name = rel.name.lower()
    suffix = ".json.gz" if name.endswith(".json.gz") else rel.suffix.lower()

    if first == "data" and len(parts) > 1:
        if parts[1] == "datasets":
            return "datasets", "episode_file"
        if parts[1] == "scene_datasets":
            return "scenes", "scene"
        return "assets", "trajectory"
    if first == "checkpoints":
        return "models", "checkpoint_file"
    if first in ("results", "results_archive_bak"):
        if suffix == ".json":
            return "results", "result"
        return "results", kind_by_suffix(suffix)
    if first == "config":
        return "assets", "config"
    if first == "scripts":
        return "assets", "script"
    if first == "logs":
        return "assets", "log"
    if first in ("llava", "streamvln", "trl", "realworld"):
        return "assets", "source"
    return "assets", kind_by_suffix(suffix)


def kind_by_suffix(suffix: str) -> str:
    if suffix in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        return "figure"
    if suffix in (".csv", ".tsv"):
        return "table"
    if suffix == ".log":
        return "log"
    if suffix in (".md", ".txt", ".pdf", ".tex", ".def"):
        return "doc"
    if suffix in (".yaml", ".yml"):
        return "config"
    if suffix in (".json", ".json.gz", ".jsonl"):
        return "data"
    if suffix in (".py", ".sh"):
        return "script"
    if suffix in (".glb", ".navmesh"):
        return "scene"
    return "file"


def file_signature(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def mtime_str(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")


def directory_signature(root: Path) -> str:
    """轻量目录指纹：文件路径 + 体积 + mtime，用于自动导入的变更检测。"""
    digest = hashlib.sha256()
    if not root.is_dir():
        return ""
    for path in iter_asset_files(root):
        stat = path.stat()
        digest.update(
            f"{path.relative_to(root).as_posix()}|{stat.st_size}|{stat.st_mtime_ns}\n".encode()
        )
    checkpoints = root / "checkpoints"
    if checkpoints.is_dir():
        for entry in sorted(checkpoints.iterdir()):
            digest.update(f"ckpt|{entry.name}|{entry.is_dir()}\n".encode())
    return digest.hexdigest()


# ---------------------------------------------------------------- 候选规格


def _dataset_title(family: str) -> str:
    return {
        "r2r": "R2R-CE",
        "rxr": "RxR-CE",
        "envdrop": "EnvDrop-CE",
        "scalevln": "ScaleVLN-CE",
    }.get(family.lower(), family.replace("_", " ").title() + "-CE")


def _dataset_kind(family: str) -> str:
    if family.lower() == "r2r":
        return "r2r_ce"
    if family.lower() == "rxr":
        return "rxr_ce"
    return "custom"


def _split_label(name: str) -> str:
    return name.replace("_p", "-p")


def _episode_files(directory: Path, kind: str) -> list[Path]:
    try:
        return dataset_service.discover_files(directory, kind)
    except OSError:
        return []


def dataset_specs(root: Path) -> list[dict[str, Any]]:
    """发现备份库内所有可作为数据集登记的目录。"""
    base = root / "data" / "datasets"
    if not base.is_dir():
        return []
    specs: list[dict[str, Any]] = []
    for family_dir in sorted(base.iterdir()):
        if not family_dir.is_dir():
            continue
        family = family_dir.name
        kind = _dataset_kind(family)
        children = [item for item in sorted(family_dir.iterdir()) if item.is_dir()]
        for child in children:
            files = _episode_files(child, kind)
            if not files:
                continue
            specs.append(_make_dataset_spec(root, child, family, kind, child.name, files))
        own_files = _episode_files(family_dir, kind)
        if own_files:
            specs.append(
                _make_dataset_spec(root, family_dir, family, kind, family_dir.name, own_files)
            )
    return specs


def _make_dataset_spec(
    root: Path,
    directory: Path,
    family: str,
    kind: str,
    split_name: str,
    files: list[Path],
) -> dict[str, Any]:
    size = sum(path.stat().st_size for path in files)
    latest = max((path.stat().st_mtime_ns for path in files), default=0)
    title = _dataset_title(family)
    label = _split_label(split_name)
    name = f"{title} {label}" if label != family else title
    return {
        "section": "datasets",
        "key": f"entity:datasets:{directory.relative_to(root).as_posix()}",
        "rel": directory.relative_to(root).as_posix(),
        "path": directory,
        "name": name[:64],
        "version": "v1",
        "kind": kind,
        "files": [path.name for path in files],
        "size_bytes": size,
        "signature": f"{size}:{latest}:{len(files)}",
        "scene_root": str(root / "data" / "scene_datasets"),
    }


def model_specs(root: Path) -> list[dict[str, Any]]:
    """发现权重目录；目录内须有 config.json 或分片权重。"""
    checkpoints = root / "checkpoints"
    if not checkpoints.is_dir():
        return []
    specs: list[dict[str, Any]] = []
    for directory in sorted(checkpoints.iterdir()):
        if not directory.is_dir():
            continue
        if not (directory / "config.json").is_file() and not any(
            directory.glob("*.safetensors")
        ):
            continue
        files = [path for path in directory.iterdir() if path.is_file()]
        size = sum(path.stat().st_size for path in files)
        latest = max((path.stat().st_mtime_ns for path in files), default=0)
        rel = directory.relative_to(root).as_posix()
        specs.append(
            {
                "section": "models",
                "key": f"entity:models:{rel}",
                "rel": rel,
                "path": directory,
                "name": directory.name,
                "size_bytes": size,
                "signature": f"{size}:{latest}:{len(files)}",
            }
        )
    return specs


def result_roots(root: Path) -> list[Path]:
    """兼容历史产物目录与归档目录。"""
    candidates = (root / "results", root / "results_archive_bak")
    return [
        candidate
        for candidate in candidates
        if candidate.is_dir() and next(candidate.glob("*/streamvln/result.json"), None)
    ]


def scene_files(root: Path) -> list[Path]:
    base = root / "data" / "scene_datasets"
    if not base.is_dir():
        return []
    return sorted(path for path in base.rglob("*.glb") if path.is_file())


# ---------------------------------------------------------------- 索引与账本


def asset_to_dict(row: BackupAsset) -> dict[str, Any]:
    return {
        "id": row.id,
        "source_key": row.source_key,
        "root_path": row.root_path,
        "rel_path": row.rel_path,
        "section": row.section,
        "kind": row.kind,
        "name": row.name,
        "size_bytes": row.size_bytes,
        "mtime": row.mtime,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "status": row.status,
        "message": row.message,
        "imported_at": row.imported_at,
        "updated_at": row.updated_at,
    }


def _asset_index(db: Session, root: Path) -> dict[str, BackupAsset]:
    rows = db.scalars(
        select(BackupAsset).where(BackupAsset.root_path == str(root))
    ).all()
    return {row.source_key: row for row in rows}


def _upsert_entity(
    db: Session,
    root: Path,
    *,
    source_key: str,
    section: str,
    rel: str,
    name: str,
    signature: str,
    status: str,
    message: str,
    entity_type: str = "",
    entity_id: int | None = None,
    size_bytes: int = 0,
    kind: str = "directory",
    detail: dict[str, Any] | None = None,
) -> None:
    row = db.scalar(select(BackupAsset).where(BackupAsset.source_key == source_key))
    if row is None:
        row = BackupAsset(source_key=source_key, imported_at=now_str())
        db.add(row)
    row.root_path = str(root)
    row.rel_path = rel
    row.section = section
    row.kind = kind
    row.name = name[:255]
    row.signature = signature
    row.size_bytes = size_bytes
    row.entity_type = entity_type
    row.entity_id = entity_id
    row.status = status
    row.message = message[:500]
    row.meta_json = json.dumps(detail or {}, ensure_ascii=False)
    row.updated_at = now_str()


def _index_assets(
    db: Session,
    root: Path,
    sections: list[str],
    dry_run: bool,
) -> dict[str, dict[str, int]]:
    """把资料文件登记到 backup_asset；返回各类别新增/变更/未变化计数。"""
    counts = {
        section: {"new": 0, "changed": 0, "unchanged": 0, "total": 0}
        for section in sections
    }
    index = _asset_index(db, root)
    seen: set[str] = set()
    pending = 0

    for path in iter_asset_files(root):
        rel_path = path.relative_to(root)
        section, kind = classify(rel_path)
        if section not in counts:
            continue
        rel = rel_path.as_posix()
        source_key = f"file:{rel}"
        seen.add(source_key)
        signature = file_signature(path)
        counts[section]["total"] += 1
        previous = index.get(source_key)

        if previous and previous.signature == signature:
            counts[section]["unchanged"] += 1
            if previous.status == "missing" and not dry_run:
                previous.status = "imported"
                previous.message = "源文件已恢复"
                previous.updated_at = now_str()
            continue
        bucket = "changed" if previous else "new"
        counts[section][bucket] += 1
        if dry_run:
            continue
        row = previous or BackupAsset(source_key=source_key, imported_at=now_str())
        if previous is None:
            db.add(row)
        row.root_path = str(root)
        row.rel_path = rel
        row.section = section
        row.kind = kind
        row.name = path.name[:255]
        row.size_bytes = path.stat().st_size
        row.mtime = mtime_str(path)
        row.signature = signature
        row.status = "imported"
        row.message = ""
        row.updated_at = now_str()
        pending += 1
        if pending % 200 == 0:
            db.commit()

    if not dry_run:
        for source_key, row in index.items():
            if (
                source_key.startswith("file:")
                and source_key not in seen
                and row.section in counts
                and row.status != "missing"
            ):
                row.status = "missing"
                row.message = "源文件已不存在"
                row.updated_at = now_str()
        db.commit()
    return counts


# ---------------------------------------------------------------- 数据集导入


def _find_dataset(db: Session, spec: dict[str, Any], record: BackupAsset | None) -> Dataset | None:
    if record is not None and record.entity_id:
        found = db.get(Dataset, record.entity_id)
        if found is not None:
            return found
    target = str(spec["path"])
    rows = db.scalars(select(Dataset)).all()
    for row in rows:
        if str(Path(row.root_path).expanduser()) == target:
            return row
    return None


def _scan_dataset(
    db: Session,
    dataset_id: int,
    spec: dict[str, Any],
    scan_episodes: bool,
    limit_mb: int,
    allow: bool,
) -> tuple[str, str]:
    """扫描 episode；失败时只保留已登记的数据集，不让单项失败影响整批。"""
    if not scan_episodes:
        return "registered", "已登记路径，未解析 episode（自动扫描已关闭）"
    if not allow:
        return "registered", "训练/大规模轨迹数据仅登记路径，可在数据集页手动扫描"
    size_mb = spec["size_bytes"] / 1048576
    if size_mb > limit_mb:
        return (
            "registered",
            f"episode 文件 {size_mb:.1f} MB 超过 {limit_mb} MB，仅登记路径，可在数据集页手动扫描",
        )
    try:
        dataset = db.get(Dataset, dataset_id)
        summary = dataset_service.scan_dataset(db, dataset)
        db.commit()
        return "scanned", f"解析 {summary['episode_count']} 条 episode / {summary['scene_count']} 个场景"
    except Exception as exc:  # noqa: BLE001 - 单个数据集扫描失败不应中断整批
        db.rollback()
        return "registered", f"路径已登记，扫描失败：{str(exc)[:200]}"


def _import_datasets(
    db: Session,
    root: Path,
    specs: list[dict[str, Any]],
    *,
    dry_run: bool,
    force: bool,
    scan_episodes: bool,
    limit_mb: int,
    scan_exclude: list[str],
) -> list[dict[str, Any]]:
    index = _asset_index(db, root)
    items: list[dict[str, Any]] = []

    for spec in specs:
        record = index.get(spec["key"])
        dataset = _find_dataset(db, spec, record)
        item: dict[str, Any] = {
            "section": "datasets",
            "key": spec["key"],
            "name": spec["name"],
            "path": str(spec["path"]),
            "rel_path": spec["rel"],
            "size_bytes": spec["size_bytes"],
            "entity_type": "dataset",
            "entity_id": dataset.id if dataset else None,
            "files": spec["files"],
            "kind": spec["kind"],
            "status": "",
            "message": "",
        }

        unchanged = (
            record is not None
            and record.signature == spec["signature"]
            and dataset is not None
            and not force
        )
        if unchanged:
            item.update(status="skipped", message="已导入且源文件未变化")
            items.append(item)
            continue
        if dry_run:
            item.update(
                status="ready" if dataset is None else "changed",
                message="待登记数据集" if dataset is None else "源目录有变化，待同步",
            )
            items.append(item)
            continue

        try:
            if dataset is None:
                dataset = dataset_service.create_dataset(
                    db,
                    DatasetCreate(
                        name=spec["name"],
                        version=spec["version"],
                        kind=spec["kind"],  # type: ignore[arg-type]
                        root_path=str(spec["path"]),
                        scene_root=spec["scene_root"],
                        note="由备份库自动导入登记",
                    ),
                    username="backup-import",
                )
                db.flush()
                created = True
            else:
                created = False

            meta = json.loads(dataset.meta_json or "{}")
            meta["source_key"] = spec["key"]
            meta["backup_root"] = str(root)
            meta.setdefault("scene_root", spec["scene_root"])
            meta["imported_by"] = "backup-import"
            dataset.meta_json = json.dumps(meta, ensure_ascii=False)
            dataset.updated_at = now_str()
            db.commit()
            dataset_id = dataset.id

            if created or force:
                rel_lower = spec["rel"].lower()
                allow = not any(token in rel_lower for token in scan_exclude)
                status, message = _scan_dataset(
                    db, dataset_id, spec, scan_episodes, limit_mb, allow
                )
            else:
                status, message = "updated", "已补齐备份库来源信息，未重复解析 episode"

            item.update(entity_id=dataset_id, status=status, message=message)
            _upsert_entity(
                db,
                root,
                source_key=spec["key"],
                section="datasets",
                rel=spec["rel"],
                name=spec["name"],
                signature=spec["signature"],
                status=status,
                message=message,
                entity_type="dataset",
                entity_id=dataset_id,
                size_bytes=spec["size_bytes"],
                detail={
                    "files": spec["files"],
                    "kind": spec["kind"],
                    "scene_root": spec["scene_root"],
                },
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001 - 单项失败不影响后续数据集
            db.rollback()
            item.update(status="failed", message=str(exc)[:300])
        items.append(item)
    return items


# ---------------------------------------------------------------- 场景与模型导入


def _scene_items(
    root: Path, index: dict[str, BackupAsset], dry_run: bool
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in scene_files(root):
        rel = path.relative_to(root).as_posix()
        source_key = f"file:{rel}"
        record = index.get(source_key)
        size = path.stat().st_size
        unchanged = (
            record is not None
            and record.signature == file_signature(path)
            and record.status != "missing"
        )
        status = "skipped" if unchanged else ("ready" if dry_run else "created")
        items.append(
            {
                "section": "scenes",
                "key": source_key,
                "name": path.stem,
                "path": str(path),
                "rel_path": rel,
                "size_bytes": size,
                "entity_type": "",
                "entity_id": None,
                "kind": "scene",
                "status": status,
                "message": {
                    "skipped": "场景索引已存在",
                    "ready": "待登记场景索引",
                    "created": "已登记场景索引",
                }[status],
            }
        )
    return items


def detect_launcher() -> str:
    """探测真实可用的 torchrun；适配器按 torchrun 的参数格式构造命令。"""
    candidates = [
        shutil.which("torchrun"),
        str(Path(sys.executable).with_name("torchrun")),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    return "torchrun"


def _eval_default_config(
    root: Path, source_key: str, checkpoint_dir: Path | None = None
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "num_history": 8,
        "num_future_steps": 4,
        "slow_update_interval": 4,
        "prune_ratio": 0.35,
        "max_steps": 500,
        "seed": 42,
        "imported": True,
        "source_key": source_key,
    }
    yaml_path = root / "config" / "vln_r2r.yaml"
    if yaml_path.is_file():
        config["habitat_config_path"] = str(yaml_path)
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            habitat = data.get("habitat") or {}
            environment = habitat.get("environment") or {}
            simulator = habitat.get("simulator") or {}
            if environment.get("max_episode_steps"):
                config["max_steps"] = int(environment["max_episode_steps"])
            if simulator.get("forward_step_size"):
                config["forward_step_size"] = float(simulator["forward_step_size"])
        except (OSError, ValueError, TypeError, yaml.YAMLError):
            pass

    if checkpoint_dir is not None:
        weights_config = checkpoint_dir / "config.json"
        if weights_config.is_file():
            try:
                data = json.loads(weights_config.read_text(encoding="utf-8"))
                config["checkpoint_config"] = {
                    key: data[key]
                    for key in (
                        "model_type",
                        "architectures",
                        "mm_vision_tower",
                        "hidden_size",
                        "num_hidden_layers",
                        "torch_dtype",
                    )
                    if isinstance(data, dict) and data.get(key) is not None
                }
            except (OSError, json.JSONDecodeError):
                pass
    return config


def _pick_model_profile(db: Session, spec: dict[str, Any]) -> ModelProfile | None:
    """优先修正路径失效的 StreamVLN 档案，避免与手工登记的模型重复。"""
    profiles = db.scalars(
        select(ModelProfile)
        .where(ModelProfile.family == "streamvln")
        .order_by(ModelProfile.id)
    ).all()
    for profile in profiles:
        weights = str(Path(profile.weights_path).name) if profile.weights_path else ""
        if weights == spec["name"]:
            return profile
    for profile in profiles:
        if not profile.weights_path or not Path(profile.weights_path).expanduser().exists():
            return profile
    return None


def _import_models(
    db: Session,
    root: Path,
    specs: list[dict[str, Any]],
    *,
    dry_run: bool,
    force: bool,
) -> list[dict[str, Any]]:
    index = _asset_index(db, root)
    launcher = detect_launcher()
    items: list[dict[str, Any]] = []

    for spec in specs:
        record = index.get(spec["key"])
        profile = None
        if record is not None and record.entity_id:
            profile = db.get(ModelProfile, record.entity_id)
        if profile is None:
            profile = _pick_model_profile(db, spec)

        item: dict[str, Any] = {
            "section": "models",
            "key": spec["key"],
            "name": spec["name"],
            "path": str(spec["path"]),
            "rel_path": spec["rel"],
            "size_bytes": spec["size_bytes"],
            "entity_type": "model",
            "entity_id": profile.id if profile else None,
            "kind": "checkpoint",
            "status": "",
            "message": "",
        }

        unchanged = (
            record is not None
            and record.signature == spec["signature"]
            and profile is not None
            and str(Path(profile.weights_path).expanduser()) == str(spec["path"])
            and profile.entry == launcher
            and profile.status == "available"
            and not force
        )
        if unchanged:
            item.update(status="skipped", message="模型档案已自动配置，权重与启动器均未变化")
            items.append(item)
            continue
        if dry_run:
            item.update(
                status="ready" if profile is None else "changed",
                message="待自动登记模型档案" if profile is None else "待自动配置启动器/路径/参数",
            )
            items.append(item)
            continue

        try:
            config = _eval_default_config(root, spec["key"], spec["path"])
            config["checkpoint"] = spec["name"]
            config["launcher"] = launcher
            if profile is None:
                short = spec["name"].replace("StreamVLN_Video_", "StreamVLN-")
                profile = model_service.create_model(
                    db,
                    ModelCreate(
                        name=short[:64],
                        family="streamvln",
                        code_path=str(root),
                        weights_path=str(spec["path"]),
                        entry=launcher,
                        default_config=config,
                        needs_gpu=True,
                        allowed_inputs=["rgb", "depth", "pose", "action"],
                        description="由备份库 checkpoints 目录自动配置",
                    ),
                )
                action = "created"
            else:
                profile.code_path = str(root)
                profile.weights_path = str(spec["path"])
                profile.entry = launcher
                profile.default_config_json = json.dumps(config, ensure_ascii=False)
                profile.updated_at = now_str()
                action = "updated"
            db.flush()
            probe = model_service.probe_model(db, profile)
            profile_id = profile.id
            message = (
                f"{'已自动登记' if action == 'created' else '已自动配置'}代码/权重/"
                f"启动器/默认参数，探测状态 {probe['status']}；启动器 {launcher}"
            )
            item.update(entity_id=profile_id, status=action, message=message)
            _upsert_entity(
                db,
                root,
                source_key=spec["key"],
                section="models",
                rel=spec["rel"],
                name=spec["name"],
                signature=spec["signature"],
                status=action,
                message=message,
                entity_type="model",
                entity_id=profile_id,
                size_bytes=spec["size_bytes"],
                detail={
                    "status": probe["status"],
                    "checks": probe["checks"],
                    "checkpoint": spec["name"],
                    "launcher": launcher,
                },
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001 - 单项失败不影响后续模型
            db.rollback()
            item.update(status="failed", message=str(exc)[:300])
        items.append(item)
    return items


# ---------------------------------------------------------------- 评测结果导入


def _import_results(
    db: Session,
    root: Path,
    *,
    dry_run: bool,
    force: bool,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for results_dir in result_roots(root):
        try:
            summary = import_service.import_results(
                db, str(results_dir), force=force, dry_run=dry_run
            )
        except AppError as exc:
            items.append(
                {
                    "section": "results",
                    "key": f"entity:results:{results_dir.name}",
                    "name": results_dir.name,
                    "path": str(results_dir),
                    "rel_path": results_dir.name,
                    "size_bytes": 0,
                    "entity_type": "",
                    "entity_id": None,
                    "kind": "results_dir",
                    "status": "failed",
                    "message": exc.message[:300],
                }
            )
            continue
        for entry in summary["items"]:
            path = Path(entry["path"])
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                rel = path.as_posix()
            items.append(
                {
                    "section": "results",
                    "key": f"entity:results:{rel}",
                    "name": entry["experiment"],
                    "path": entry["path"],
                    "rel_path": rel,
                    "size_bytes": 0,
                    "entity_type": "task" if entry.get("task_id") else "",
                    "entity_id": entry.get("task_id"),
                    "kind": "experiment",
                    "records": entry["records"],
                    "matched": entry["matched"],
                    "dataset": entry["dataset"],
                    "status": entry["status"],
                    "message": entry["message"],
                }
            )
    return items


# ---------------------------------------------------------------- 对外入口


def describe(db: Session, root_path: str | None = None) -> dict[str, Any]:
    """导入面板概览：绑定目录、各类别候选数量、库内已有对象数量。"""
    root = resolve_root(root_path, strict=False)
    data: dict[str, Any] = {
        "root": str(root),
        "exists": root.is_dir(),
        "message": "" if root.is_dir() else f"目录不存在：{root}",
        "sections": [],
        "counts": {},
    }
    if not root.is_dir():
        return data

    datasets = dataset_specs(root)
    models = model_specs(root)
    scenes = scene_files(root)
    results = sum(len(list(item.glob("*/streamvln/result.json"))) for item in result_roots(root))
    found = {
        "datasets": len(datasets),
        "scenes": len(scenes),
        "models": len(models),
        "results": results,
        "assets": sum(
            1
            for path in iter_asset_files(root)
            if classify(path.relative_to(root))[0] == "assets"
        ),
    }
    imported = dict(
        db.execute(
            select(BackupAsset.section, func.count())
            .where(
                BackupAsset.root_path == str(root),
                BackupAsset.status != "missing",
            )
            .group_by(BackupAsset.section)
        ).all()
    )
    for section in ALL_IMPORT_SECTIONS:
        data["sections"].append(
            {
                "key": section,
                "label": SECTION_LABELS[section],
                "description": SECTION_DESCRIPTIONS[section],
                "found": found[section],
                "indexed": int(imported.get(section, 0)),
            }
        )
    data["counts"] = {
        "datasets": db.scalar(select(func.count()).select_from(Dataset)) or 0,
        "episodes": db.scalar(select(func.sum(Dataset.episode_count))) or 0,
        "models": db.scalar(select(func.count()).select_from(ModelProfile)) or 0,
        "tasks": db.scalar(select(func.count()).select_from(EvalTask)) or 0,
        "assets": db.scalar(select(func.count()).select_from(BackupAsset)) or 0,
    }
    return data


def run_import(
    db: Session,
    root_path: str | None = None,
    *,
    sections: Iterable[str] | None = None,
    dry_run: bool = False,
    force: bool = False,
    scan_episodes: bool | None = None,
    reason: str = "manual",
) -> dict[str, Any]:
    """扫描并导入备份库；dry_run 只预览，不写任何表。"""
    settings = get_settings()
    root = resolve_root(root_path)
    requested = [str(item) for item in (sections or [])]
    selected = [item for item in requested if item in ALL_IMPORT_SECTIONS]
    if not selected:
        selected = list(settings.imports.auto_sections)
    should_scan = (
        settings.imports.auto_scan_episodes if scan_episodes is None else bool(scan_episodes)
    )
    started = time.monotonic()
    started_at = now_str()
    items: list[dict[str, Any]] = []
    index = _asset_index(db, root)

    if "datasets" in selected:
        items.extend(
            _import_datasets(
                db,
                root,
                dataset_specs(root),
                dry_run=dry_run,
                force=force,
                scan_episodes=should_scan,
                limit_mb=settings.imports.scan_limit_mb,
                scan_exclude=settings.imports.scan_exclude,
            )
        )
    if "scenes" in selected:
        items.extend(_scene_items(root, index, dry_run))
    if "models" in selected:
        items.extend(
            _import_models(
                db, root, model_specs(root), dry_run=dry_run, force=force
            )
        )
    if "results" in selected:
        items.extend(_import_results(db, root, dry_run=dry_run, force=force))

    asset_counts = _index_assets(db, root, selected, dry_run)

    counters = {"created": 0, "updated": 0, "skipped": 0, "unmatched": 0, "failed": 0}
    status_alias = {
        "created": "created",
        "scanned": "created",
        "registered": "created",
        "changed": "updated",
        "updated": "updated",
        "imported": "skipped",
        "skipped": "skipped",
        "failed": "failed",
        "unmatched": "unmatched",
        "ready": "created",
    }
    section_counts: dict[str, dict[str, int]] = {}
    for item in items:
        bucket = status_alias.get(item["status"], "created")
        counters[bucket] += 1
        stat = section_counts.setdefault(
            item["section"],
            {"items": 0, "created": 0, "updated": 0, "skipped": 0, "unmatched": 0, "failed": 0},
        )
        stat["items"] += 1
        stat[bucket] += 1

    if not dry_run:
        db.commit()
    return {
        "root": str(root),
        "reason": reason,
        "dry_run": dry_run,
        "force": force,
        "sections": selected,
        "started_at": started_at,
        "finished_at": now_str(),
        "duration_s": round(time.monotonic() - started, 2),
        "scanned": len(items),
        **counters,
        "section_counts": section_counts,
        "asset_counts": asset_counts,
        "items": items,
    }


def list_assets(
    db: Session,
    *,
    section: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    conditions = []
    if section:
        conditions.append(BackupAsset.section == section)
    if kind:
        conditions.append(BackupAsset.kind == kind)
    if status:
        conditions.append(BackupAsset.status == status)
    if q:
        conditions.append(
            or_(BackupAsset.rel_path.like(f"%{q}%"), BackupAsset.name.like(f"%{q}%"))
        )
    total = db.scalar(
        select(func.count()).select_from(BackupAsset).where(*conditions)
    ) or 0
    rows = db.scalars(
        select(BackupAsset)
        .where(*conditions)
        .order_by(BackupAsset.section, BackupAsset.rel_path)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return [asset_to_dict(row) for row in rows], total
