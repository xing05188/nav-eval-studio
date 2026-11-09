"""历史评测产物导入。

把外部评测产物目录（`<root>/results/<实验名>/streamvln/result.json`，JSONL，一行一条
episode）还原为平台内的评测任务：

1. 按 `(scene_id, episode_id)` 与已登记数据集对齐，只导入命中切分的记录；
2. 为每次评测生成 `custom` 切分，保证任务可回放、可对比；
3. 写入逐 episode 指标与资源采样，聚合指标复用 `task_service.aggregate_metrics`；
4. 原始产物（result.json / eval.log / csv / 自检截图）拷贝到 `storage/runs` 并登记 artifact。

重复导入时按 `config_json.source_dir` 幂等；结果文件仍在写入时任务标记为「运行中」，
并通过 `source_mtime_ns` 做增量同步（追加新 episode、刷新进度与聚合指标），
`force=True` 则删旧重建。
"""

from __future__ import annotations

import json
import re
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.paths import display_path
from ..core.response import NOT_FOUND, PARAM_INVALID, AppError
from ..models import (
    Artifact,
    Dataset,
    Episode,
    EvalTask,
    ModelProfile,
    ResourceSample,
    Split,
    SplitEpisode,
    TaskEpisode,
)
from . import replay_service, task_service

MODALITY_INPUTS = {
    "vision": ["rgb"],
    "vision_geo": ["depth", "rgb"],
    "vision_geo_state": ["depth", "pose", "rgb"],
}

FIGURE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")
KEEP_SUFFIXES = (".csv", ".txt", ".log", ".json")
TIMEOUT_STEPS = 450


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------- 目录发现


def locate_results_dir(root: Path) -> Path:
    """兼容传入项目根目录或 results 目录本身。"""
    if not str(root).strip():
        raise AppError(PARAM_INVALID, "请填写产物根目录")
    if not root.exists():
        raise AppError(NOT_FOUND, f"目录不存在：{root}")
    for candidate in (root / "results", root):
        if candidate.is_dir() and next(candidate.glob("*/streamvln/result.json"), None):
            return candidate
    raise AppError(
        PARAM_INVALID,
        f"{root} 下未找到 <实验名>/streamvln/result.json，请确认是评测产物根目录",
    )


def describe(root: Path | None = None) -> dict[str, Any]:
    """返回导入面板需要的绑定信息与产物统计。"""
    settings = get_settings()
    bound = root or settings.imports.results_root
    data: dict[str, Any] = {
        "root": str(bound),
        "exists": bound.exists(),
        "results_dir": "",
        "experiments": 0,
        "message": "",
    }
    if not bound.exists():
        data["message"] = f"目录不存在：{bound}"
        return data
    try:
        results_dir = locate_results_dir(bound)
    except AppError as exc:
        data["message"] = exc.message
        return data
    data["results_dir"] = str(results_dir)
    data["experiments"] = len(list(results_dir.glob("*/streamvln/result.json")))
    return data


# ---------------------------------------------------------------- 解析与推断


def read_result_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and "episode_id" in item:
            rows.append(item)
    return rows


def infer_config(exp: str, base_split: str, source: Path) -> dict[str, Any]:
    """按实验目录名推断模态/记忆策略/窗口；推断依据统一写入 inferred 字段。"""
    lower = exp.lower()
    if "state" in lower:
        spatial_mode = "text+action"
    elif re.search(r"(^|_)act(_|$)|action", lower):
        spatial_mode = "action"
    elif re.search(r"text|geo|prose|ord", lower):
        spatial_mode = "text"
    else:
        spatial_mode = "off"

    control = "none"
    if re.search(r"(^|_)ph(_|$)", lower):
        control = "placeholder"
    elif re.search(r"(^|_)wr(_|$)", lower):
        control = "wrong"
    elif "rand" in lower:
        control = "random_veto"

    modality = {
        "off": "vision",
        "text": "vision_geo",
        "action": "vision_geo",
        "text+action": "vision_geo_state",
    }[spatial_mode]
    memory_policy = (
        "spatial_prune"
        if "prune" in lower
        else ("feature_cache" if "prefix" in lower else "fixed_window")
    )

    history_len = 8
    match = re.search(r"win(\d+)", lower)
    if match:
        history_len = int(match.group(1))
    slow_update = 4
    match = re.search(r"nf(\d+)", lower)
    if match:
        slow_update = int(match.group(1))

    config: dict[str, Any] = {
        "template_id": None,
        "modality": modality,
        "memory_policy": memory_policy,
        "history_len": history_len,
        "slow_update_interval": slow_update,
        "prune_ratio": 0.0,
        "max_steps": 500,
        "seed": 42,
        "eval_split": base_split,
        "gpu_ids": "",
        "num_future_steps": 4,
        "allowed_inputs": MODALITY_INPUTS[modality],
        "imported": True,
        "source_dir": str(source),
        "inferred": {"spatial_mode": spatial_mode, "spatial_control": control},
    }
    match = re.search(r"chunk(\d+)", lower)
    if match:
        config["action_chunk"] = int(match.group(1))
    return config


def failure_reason(success: bool, os_value: float, steps: int) -> str:
    """原始结果没有失败原因字段，按 oracle success 与步数规则推断。"""
    if success:
        return ""
    if steps >= TIMEOUT_STEPS:
        return "timeout"
    if os_value >= 1.0:
        return "early_stop"
    return "goal_unreachable"


def infer_expected(exp: str, matched: int) -> int:
    """按实验目录名推断目标 episode 数；推断不出时以实际匹配数为准。"""
    lower = exp.lower()
    match = re.search(r"(?:^|_)p(\d+)(?:_|$)", lower)
    if match:
        return max(int(match.group(1)), matched)
    if "smoke" in lower:
        return max(3, matched)
    return matched


def is_active(result_file: Path, grace_s: int) -> bool:
    """结果文件近期仍在写入 → 外部评测仍在运行。"""
    return (time.time() - result_file.stat().st_mtime) <= grace_s


def _task_config(task: EvalTask) -> dict[str, Any]:
    try:
        config = json.loads(task.config_json or "{}")
    except json.JSONDecodeError:
        config = {}
    return config if isinstance(config, dict) else {}


# ---------------------------------------------------------------- 对齐


def _episode_index(db: Session) -> tuple[list[Dataset], dict[int, dict[tuple[str, str], int]]]:
    datasets = list(db.scalars(select(Dataset).order_by(Dataset.id)).all())
    maps: dict[int, dict[tuple[str, str], int]] = {}
    for dataset in datasets:
        mapping: dict[tuple[str, str], int] = {}
        for row_id, scene, key in db.execute(
            select(Episode.id, Episode.scene_id, Episode.episode_id).where(
                Episode.dataset_id == dataset.id
            )
        ).all():
            mapping[(scene, str(key))] = row_id
        maps[dataset.id] = mapping
    return datasets, maps


def _match(
    rows: list[dict[str, Any]],
    datasets: list[Dataset],
    maps: dict[int, dict[tuple[str, str], int]],
) -> tuple[Dataset | None, list[tuple[int, dict[str, Any]]]]:
    scores: dict[int, int] = {}
    for row in rows:
        key = (str(row.get("scene_id") or ""), str(row.get("episode_id")))
        for dataset_id, mapping in maps.items():
            if key in mapping:
                scores[dataset_id] = scores.get(dataset_id, 0) + 1
    if not scores:
        return None, []

    dataset_id = max(scores, key=lambda item: (scores[item], -item))
    dataset = next(item for item in datasets if item.id == dataset_id)
    mapping = maps[dataset_id]

    matched: list[tuple[int, dict[str, Any]]] = []
    seen: set[int] = set()
    for row in rows:
        row_id = mapping.get((str(row.get("scene_id") or ""), str(row.get("episode_id"))))
        if row_id is None or row_id in seen:
            continue
        seen.add(row_id)
        matched.append((row_id, row))
    return dataset, matched


def _existing_sources(db: Session) -> dict[str, int]:
    found: dict[str, int] = {}
    for task in db.scalars(select(EvalTask)).all():
        try:
            config = json.loads(task.config_json or "{}")
        except json.JSONDecodeError:
            continue
        if isinstance(config, dict) and config.get("source_dir"):
            found[str(config["source_dir"])] = task.id
    return found


# ---------------------------------------------------------------- 落盘


def _copy_artifacts(db: Session, task: EvalTask, exp_dir: Path, result_file: Path) -> int:
    work_dir = get_settings().storage.work_dir
    run_dir = work_dir / "runs" / f"task-{task.id:06d}"
    (run_dir / "raw").mkdir(parents=True, exist_ok=True)
    (run_dir / "attachments").mkdir(parents=True, exist_ok=True)

    created = 0

    def register(source: Path, target: Path, kind: str) -> None:
        nonlocal created
        shutil.copy2(source, target)
        db.add(
            Artifact(
                task_id=task.id,
                kind=kind,
                name=target.name,
                path=display_path(work_dir, target),
                size_bytes=target.stat().st_size,
                created_at=now_str(),
            )
        )
        created += 1

    register(result_file, run_dir / "raw" / "result.json", "log")

    eval_log = exp_dir / "eval.log"
    if eval_log.is_file():
        shutil.copy2(eval_log, run_dir / "run.log")
        register(eval_log, run_dir / "attachments" / "eval.log", "log")

    for extra in sorted(exp_dir.iterdir()):
        if not extra.is_file() or extra.name == "eval.log":
            continue
        if extra.suffix.lower() in KEEP_SUFFIXES:
            register(extra, run_dir / "attachments" / extra.name, "log")
        elif extra.suffix.lower() in FIGURE_SUFFIXES:
            register(extra, run_dir / "attachments" / extra.name, "figure")

    check_dir = exp_dir / "streamvln" / "check_sim_0"
    if check_dir.is_dir():
        for image in sorted(check_dir.iterdir()):
            if image.is_file() and image.suffix.lower() in FIGURE_SUFFIXES:
                register(image, run_dir / "attachments" / f"check_sim_0_{image.name}", "figure")
    return created


def _free_split_name(db: Session, dataset_id: int, base: str) -> str:
    """同一数据集下切分名唯一；被其他任务引用时追加序号，未引用则沿用旧名重建。"""
    name = base[:64]
    suffix = 2
    while True:
        existing = db.scalar(
            select(Split).where(Split.dataset_id == dataset_id, Split.name == name)
        )
        if existing is None:
            return name
        referenced = db.scalar(
            select(func.count()).select_from(EvalTask).where(EvalTask.split_id == existing.id)
        ) or 0
        if not referenced:
            db.execute(delete(SplitEpisode).where(SplitEpisode.split_id == existing.id))
            db.delete(existing)
            db.flush()
            return name
        name = f"{base[:58]}-{suffix}"
        suffix += 1


def _stage_frames(run_dir: Path, source: Path, name: str) -> str:
    """把历史产物里的逐帧元数据复制进任务工作目录，返回可回放的绝对路径。"""
    target_dir = run_dir / "frames"
    target = target_dir / f"{name}.jsonl"
    try:
        if target.is_file() and target.stat().st_size == source.stat().st_size:
            return str(target)
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    except OSError:
        return ""
    return str(target)


def _new_episode_rows(
    task_id: int,
    row_id: int,
    row: dict[str, Any],
    index: int,
    stamp: str,
    *,
    run_dir: Path | None = None,
    frames_dirs: list[Path] | None = None,
) -> tuple[TaskEpisode, ResourceSample | None]:
    """把一条原始结果转换为结果明细与资源采样（新建与增量同步共用）。"""
    success = float(row.get("success") or 0) >= 1.0
    os_value = float(row.get("os") or 0)
    steps = int(row.get("steps") or 0)
    elapsed = row.get("elapsed_s")
    per_step = (float(elapsed) * 1000.0 / steps) if elapsed and steps else 0.0
    gpu = int(float(row.get("peak_gpu_mem_mb") or 0))
    tokens = int(float(row.get("mean_prompt_tokens") or 0))

    # 逐帧回放：历史产物里的 replay_frames/*.jsonl 落到工作目录并写 traj_path
    traj_path = ""
    if run_dir is not None and frames_dirs:
        source = None
        scene_id = str(row.get("scene_id") or "")
        raw_key = row.get("episode_id")
        if raw_key is not None:
            for directory in frames_dirs:
                source = replay_service.locate_frame_file(directory, scene_id, str(raw_key))
                if source is not None:
                    break
        if source is not None:
            name = f"{scene_id}_{raw_key}" if scene_id else str(raw_key)
            traj_path = _stage_frames(run_dir, source, name)

    episode = TaskEpisode(
        task_id=task_id,
        episode_id=row_id,
        status="success" if success else "failed",
        success=1 if success else 0,
        spl=round(float(row.get("spl") or 0), 4),
        ne=round(float(row.get("ne") or 0), 3),
        os=round(os_value, 4),
        ndtw=round(float(row.get("ndtw") or 0), 4),
        tl=round(float(row.get("tl") or 0), 3),
        steps=steps,
        latency_avg_ms=round(per_step, 1),
        latency_p95_ms=0,
        gpu_mem_peak_mb=gpu,
        tokens_peak=tokens,
        ctx_len_peak=0,
        failure_reason=failure_reason(success, os_value, steps),
        manual_reason="",
        traj_path=traj_path,
        log_path="",
        updated_at=stamp,
    )
    sample = (
        ResourceSample(
            task_id=task_id,
            ts=stamp,
            step=index,
            gpu_mem_mb=gpu,
            latency_ms=round(per_step, 1),
            tokens=tokens,
            ctx_len=0,
        )
        if gpu or per_step
        else None
    )
    return episode, sample


def _import_one(
    db: Session,
    *,
    exp: str,
    exp_dir: Path,
    result_file: Path,
    rows: list[dict[str, Any]],
    dataset: Dataset,
    matched: list[tuple[int, dict[str, Any]]],
    model: ModelProfile,
    running: bool,
    expected: int,
) -> EvalTask:
    base_split = dataset.name.split(" ", 1)[1] if " " in dataset.name else "val_unseen"
    split_name = _free_split_name(db, dataset.id, f"import-{exp}")

    split = Split(
        dataset_id=dataset.id,
        name=split_name,
        kind="custom",
        base_split=base_split,
        seed=42,
        episode_count=len(matched),
        filter_json=json.dumps(
            {"imported": True, "source_dir": str(exp_dir)}, ensure_ascii=False
        ),
        created_at=now_str(),
    )
    db.add(split)
    db.flush()
    db.execute(
        SplitEpisode.__table__.insert(),
        [
            {"split_id": split.id, "episode_id": row_id, "ordinal": index}
            for index, (row_id, _) in enumerate(matched)
        ],
    )

    finished = datetime.fromtimestamp(result_file.stat().st_mtime)
    total_elapsed = sum(float(row["elapsed_s"]) for row in rows if row.get("elapsed_s"))
    started = finished - timedelta(seconds=total_elapsed) if total_elapsed else finished
    stamp = finished.strftime("%Y-%m-%d %H:%M:%S")
    config = infer_config(exp, base_split, exp_dir)
    config["source_mtime_ns"] = result_file.stat().st_mtime_ns
    config["expected"] = expected

    task = EvalTask(
        name=exp,
        dataset_id=dataset.id,
        split_id=split.id,
        model_profile_id=model.id,
        config_json=json.dumps(config, ensure_ascii=False),
        status="running" if running else "succeeded",
        priority=5,
        progress_done=len(matched),
        progress_total=expected if running else len(matched),
        metrics_json="{}",
        error_msg="",
        gpu_ids="",
        created_by=1,
        queued_at=started.strftime("%Y-%m-%d %H:%M:%S"),
        started_at=started.strftime("%Y-%m-%d %H:%M:%S"),
        finished_at=None if running else stamp,
        duration_s=round(total_elapsed, 1) if total_elapsed else None,
        note=(
            f"导入自历史产物 {exp_dir}；原始记录 {len(rows)} 条，"
            f"对齐 {dataset.name} 后 {len(matched)} 条。"
            + (
                f"结果文件仍在写入，目标 {expected} 条，状态标记为运行中。"
                if running
                else ""
            )
            + "模态/策略/窗口按目录名规则推断，原始结果未记录 nDTW/TL，对应指标按 0 处理。"
        ),
    )
    db.add(task)
    db.flush()

    run_dir = get_settings().runs_dir / f"task-{task.id:06d}"
    frames_dirs = replay_service.frame_dirs(exp_dir)
    for index, (row_id, row) in enumerate(matched, start=1):
        episode, sample = _new_episode_rows(
            task.id, row_id, row, index, stamp, run_dir=run_dir, frames_dirs=frames_dirs
        )
        db.add(episode)
        if sample is not None:
            db.add(sample)

    db.flush()
    _copy_artifacts(db, task, exp_dir, result_file)
    task_service.aggregate_metrics(db, task)
    return task


def _refresh_raw(db: Session, task: EvalTask, result_file: Path) -> None:
    """增量同步时覆盖工作目录内的原始结果副本，保持 artifact 可回放。"""
    raw = get_settings().runs_dir / f"task-{task.id:06d}" / "raw" / "result.json"
    if not raw.parent.is_dir():
        return
    shutil.copy2(result_file, raw)
    artifact = db.scalar(
        select(Artifact).where(Artifact.task_id == task.id, Artifact.name == "result.json")
    )
    if artifact is not None:
        artifact.size_bytes = raw.stat().st_size


def _sync_one(
    db: Session,
    *,
    task: EvalTask,
    exp_dir: Path,
    result_file: Path,
    rows: list[dict[str, Any]],
    matched: list[tuple[int, dict[str, Any]]],
    running: bool,
    expected: int,
) -> dict[str, Any]:
    """增量同步：追加新完成的 episode，刷新进度、状态与聚合指标。"""
    config = _task_config(task)
    config["source_mtime_ns"] = result_file.stat().st_mtime_ns
    config["expected"] = expected
    task.config_json = json.dumps(config, ensure_ascii=False)

    finished = datetime.fromtimestamp(result_file.stat().st_mtime)
    stamp = finished.strftime("%Y-%m-%d %H:%M:%S")
    total_elapsed = sum(float(row["elapsed_s"]) for row in rows if row.get("elapsed_s"))

    known = {
        row.episode_id
        for row in db.scalars(select(TaskEpisode).where(TaskEpisode.task_id == task.id)).all()
    }
    added = 0
    run_dir = get_settings().runs_dir / f"task-{task.id:06d}"
    frames_dirs = replay_service.frame_dirs(exp_dir)
    for index, (row_id, row) in enumerate(matched, start=1):
        if row_id in known:
            continue
        episode, sample = _new_episode_rows(
            task.id, row_id, row, index, stamp, run_dir=run_dir, frames_dirs=frames_dirs
        )
        db.add(episode)
        if sample is not None:
            db.add(sample)
        added += 1
    db.flush()

    split = db.get(Split, task.split_id)
    if split is not None:
        linked = {
            row.episode_id
            for row in db.scalars(
                select(SplitEpisode).where(SplitEpisode.split_id == split.id)
            ).all()
        }
        new_links = []
        for row_id, _ in matched:
            if row_id not in linked:
                new_links.append(
                    {
                        "split_id": split.id,
                        "episode_id": row_id,
                        "ordinal": len(linked) + len(new_links),
                    }
                )
        if new_links:
            db.execute(SplitEpisode.__table__.insert(), new_links)
        split.episode_count = len(linked) + len(new_links)

    task.progress_done = len(matched)
    task.progress_total = expected if running else len(matched)
    task.status = "running" if running else "succeeded"
    task.finished_at = None if running else stamp
    task.duration_s = round(total_elapsed, 1) if total_elapsed else None
    task.note = (
        f"导入自历史产物 {exp_dir}；已同步 {len(matched)} / "
        f"{expected if running else len(matched)} 条"
        + ("，结果仍在写入，状态标记为运行中。" if running else "，结果已停止写入。")
    )
    db.flush()
    _refresh_raw(db, task, result_file)
    metrics = task_service.aggregate_metrics(db, task)
    return {"added": added, "status": task.status, "metrics": metrics}


# ---------------------------------------------------------------- 对外入口


def import_results(
    db: Session,
    root_path: str | None = None,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    root = Path(root_path).expanduser() if root_path else settings.imports.results_root
    results_dir = locate_results_dir(root)

    files = sorted(results_dir.glob("*/streamvln/result.json"))
    datasets, maps = _episode_index(db)
    existing = _existing_sources(db)
    model = db.scalar(
        select(ModelProfile).where(ModelProfile.family == "streamvln").order_by(ModelProfile.id)
    ) or db.scalar(select(ModelProfile).order_by(ModelProfile.id))
    if model is None and not dry_run:
        raise AppError(PARAM_INVALID, "尚未登记任何模型档案，无法导入评测产物")

    items: list[dict[str, Any]] = []
    counters = {"created": 0, "updated": 0, "skipped": 0, "failed": 0, "unmatched": 0}
    grace_s = settings.imports.running_grace_s

    for result_file in files:
        exp_dir = result_file.parent.parent
        exp = exp_dir.name
        rows = read_result_rows(result_file)
        item: dict[str, Any] = {
            "experiment": exp,
            "path": str(exp_dir),
            "records": len(rows),
            "matched": 0,
            "dataset": "",
            "task_id": None,
            "status": "",
            "message": "",
        }
        if not rows:
            item.update(status="unmatched", message="没有可解析的 episode 记录")
            counters["unmatched"] += 1
            items.append(item)
            continue

        dataset, matched = _match(rows, datasets, maps)
        item["matched"] = len(matched)
        if dataset is None:
            item.update(status="unmatched", message=f"{len(rows)} 条记录无法与任何数据集对齐")
            counters["unmatched"] += 1
            items.append(item)
            continue
        item["dataset"] = dataset.name

        previous = existing.get(str(exp_dir))
        expected = infer_expected(exp, len(matched))
        running = is_active(result_file, grace_s)
        target_status = "running" if running else "succeeded"

        if previous:
            item["task_id"] = previous
            task = db.get(EvalTask, previous)
            if task is None:
                # 账本指向已删除的任务，按新建处理
                previous = None
            else:
                config = _task_config(task)
                stale = config.get("source_mtime_ns") != result_file.stat().st_mtime_ns
                # 结果文件有新增，或「运行中」已过时效需要转为「已完成」时才同步
                needs_sync = stale or task.status != target_status
                if dry_run:
                    if force or needs_sync:
                        item.update(
                            status="ready",
                            message=(
                                f"待同步 {len(matched)} 条"
                                f"（{'运行中' if running else '已完成'}）"
                            ),
                        )
                    else:
                        item.update(status="imported", message="已导入且结果未变化")
                    items.append(item)
                    continue
                if not force:
                    if not needs_sync:
                        item.update(status="skipped", message="已导入且结果未变化")
                        counters["skipped"] += 1
                        items.append(item)
                        continue
                    try:
                        result = _sync_one(
                            db,
                            task=task,
                            exp_dir=exp_dir,
                            result_file=result_file,
                            rows=rows,
                            matched=matched,
                            running=running,
                            expected=expected,
                        )
                        db.commit()
                        metrics = result["metrics"]
                        item.update(
                            status="updated",
                            message=(
                                f"新增 {result['added']} 条，共 {len(matched)} 条，"
                                f"状态 {'运行中' if running else '已完成'}，"
                                f"SR={metrics.get('sr')}"
                            ),
                        )
                        counters["updated"] += 1
                    except Exception as exc:  # noqa: BLE001 - 单个实验失败不应中断整批
                        db.rollback()
                        item.update(status="failed", message=str(exc)[:300])
                        counters["failed"] += 1
                    items.append(item)
                    continue

        if dry_run:
            item.update(
                status="ready",
                message=(
                    f"待导入 {len(matched)} 条"
                    f"（{'运行中' if running else '已完成'}）"
                ),
            )
            items.append(item)
            continue

        try:
            if previous:
                old = db.get(EvalTask, previous)
                if old is not None:
                    shutil.rmtree(
                        get_settings().runs_dir / f"task-{old.id:06d}", ignore_errors=True
                    )
                    db.delete(old)
                    db.flush()
            task = _import_one(
                db,
                exp=exp,
                exp_dir=exp_dir,
                result_file=result_file,
                rows=rows,
                dataset=dataset,
                matched=matched,
                model=model,
                running=running,
                expected=expected,
            )
            db.commit()
            metrics = json.loads(task.metrics_json or "{}")
            item.update(
                task_id=task.id,
                status="updated" if previous else "created",
                message=(
                    f"SR={metrics.get('sr')} SPL={metrics.get('spl')} "
                    f"NE={metrics.get('ne')} episodes={metrics.get('episodes')}"
                ),
            )
            counters["updated" if previous else "created"] += 1
        except Exception as exc:  # noqa: BLE001 - 单个实验失败不应中断整批
            db.rollback()
            item.update(status="failed", message=str(exc)[:300])
            counters["failed"] += 1
        items.append(item)

    return {
        "root": str(root),
        "results_dir": str(results_dir),
        "dry_run": dry_run,
        "force": force,
        "scanned": len(files),
        **counters,
        "items": items,
    }
