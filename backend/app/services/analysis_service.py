"""指标分析与诊断服务。

包含四类分析：
1. 多任务指标矩阵与基线差值
2. 按「模态组合 × 记忆策略」聚合的消融矩阵
3. 同一 episode 集合上的配对 bootstrap 显著性检验
4. 长时性能分桶与失败归因
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Iterable

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.response import PARAM_INVALID, AppError
from ..models import Dataset, Episode, EvalTask, TaskEpisode

METRIC_COLUMNS = [
    {"key": "sr", "label": "SR", "better": "higher", "format": "percent", "unit": ""},
    {"key": "spl", "label": "SPL", "better": "higher", "format": "percent", "unit": ""},
    {"key": "ne", "label": "NE", "better": "lower", "format": "number", "unit": "m"},
    {"key": "os", "label": "OS", "better": "higher", "format": "percent", "unit": ""},
    {"key": "ndtw", "label": "nDTW", "better": "higher", "format": "percent", "unit": ""},
    {"key": "tl", "label": "TL", "better": "lower", "format": "number", "unit": "m"},
    {"key": "latency_avg_ms", "label": "Latency", "better": "lower", "format": "number", "unit": "ms"},
    {"key": "gpu_mem_peak_mb", "label": "VRAM", "better": "lower", "format": "number", "unit": "MB"},
]

DEFAULT_METRICS = {"sr": 0.0, "spl": 0.0, "ne": 0.0, "os": 0.0, "ndtw": 0.0, "tl": 0.0,
                   "latency_avg_ms": 0.0, "gpu_mem_peak_mb": 0.0}

FAILURE_LABELS = {
    "timeout": "超时",
    "collision": "碰撞",
    "off_track": "偏离轨迹",
    "loop": "原地打转",
    "stuck": "卡死",
    "early_stop": "提前停止",
    "goal_unreachable": "目标不可达",
    "parse_error": "动作解析失败",
    "oom": "显存不足",
    "unknown": "未知",
}


def reason_label(reason: str) -> str:
    return FAILURE_LABELS.get(reason, reason or "未知")


def _loads(text: str | None, default: Any) -> Any:
    try:
        return json.loads(text or "")
    except (json.JSONDecodeError, TypeError):
        return default


def _loads_dict(text: str | None) -> dict[str, Any]:
    value = _loads(text, {})
    return value if isinstance(value, dict) else {}


def _get_tasks(db: Session, task_ids: Iterable[int]) -> list[EvalTask]:
    ids = list(dict.fromkeys(int(item) for item in task_ids))
    if not ids:
        raise AppError(PARAM_INVALID, "请至少选择一个任务")
    rows = db.scalars(select(EvalTask).where(EvalTask.id.in_(ids))).all()
    if len(rows) != len(ids):
        raise AppError(PARAM_INVALID, "部分任务不存在")
    order = {task_id: index for index, task_id in enumerate(ids)}
    return sorted(rows, key=lambda task: order[task.id])


def _task_row(db: Session, task: EvalTask) -> dict[str, Any]:
    metrics = {**DEFAULT_METRICS, **_loads_dict(task.metrics_json)}
    config = _loads_dict(task.config_json)
    dataset = db.get(Dataset, task.dataset_id)
    return {
        "task_id": task.id,
        "name": task.name,
        "status": task.status,
        "dataset": dataset.name if dataset else "",
        "modality": config.get("modality", "vision"),
        "memory_policy": config.get("memory_policy", "fixed_window"),
        "history_len": config.get("history_len"),
        "seed": config.get("seed"),
        "episodes": int(metrics.get("episodes") or 0),
        "values": {column["key"]: round(float(metrics.get(column["key"]) or 0), 4) for column in METRIC_COLUMNS},
    }


def list_candidates(db: Session, limit: int = 200) -> list[dict[str, Any]]:
    """可选任务列表：只保留已有指标聚合结果的任务，供分析页下拉框使用。"""
    tasks = db.scalars(
        select(EvalTask)
        .where(EvalTask.status.in_(("succeeded", "failed", "canceled")))
        .order_by(EvalTask.id.desc())
        .limit(max(1, min(int(limit), 500)))
    ).all()
    rows = [_task_row(db, task) for task in tasks]
    return [row for row in rows if row["episodes"] > 0]


def compare(db: Session, task_ids: list[int], baseline_id: int | None = None) -> dict[str, Any]:
    tasks = _get_tasks(db, task_ids)
    rows = [_task_row(db, task) for task in tasks]

    baseline = baseline_id or rows[0]["task_id"]
    if baseline not in {row["task_id"] for row in rows}:
        baseline = rows[0]["task_id"]

    delta: dict[str, dict[int, float]] = {column["key"]: {} for column in METRIC_COLUMNS}
    base_row = next(row for row in rows if row["task_id"] == baseline)
    for row in rows:
        for column in METRIC_COLUMNS:
            key = column["key"]
            delta[key][row["task_id"]] = round(
                row["values"][key] - base_row["values"][key], 4
            )

    return {
        "columns": METRIC_COLUMNS,
        "rows": rows,
        "baseline": baseline,
        "delta": delta,
    }


def ablation(db: Session, task_ids: list[int]) -> dict[str, Any]:
    tasks = _get_tasks(db, task_ids)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for task in tasks:
        row = _task_row(db, task)
        groups[(row["modality"], row["memory_policy"])].append(row)

    rows = []
    for (modality, policy), items in sorted(groups.items()):
        values = {
            column["key"]: round(
                float(np.mean([item["values"][column["key"]] for item in items])), 4
            )
            for column in METRIC_COLUMNS
        }
        rows.append(
            {
                "modality": modality,
                "memory_policy": policy,
                "tasks": len(items),
                "task_names": [item["name"] for item in items],
                "values": values,
            }
        )

    modalities = sorted({row["modality"] for row in rows})
    policies = sorted({row["memory_policy"] for row in rows})
    matrix = {
        modality: {
            policy: next(
                (
                    row["values"]
                    for row in rows
                    if row["modality"] == modality and row["memory_policy"] == policy
                ),
                None,
            )
            for policy in policies
        }
        for modality in modalities
    }

    return {
        "columns": METRIC_COLUMNS,
        "modalities": modalities,
        "policies": policies,
        "matrix": matrix,
        "rows": rows,
    }


def _episode_pairs(db: Session, task_a: EvalTask, task_b: EvalTask) -> dict[str, Any]:
    def load(task: EvalTask) -> dict[str, dict[str, float]]:
        rows = db.execute(
            select(Episode.episode_id, TaskEpisode.success, TaskEpisode.spl, TaskEpisode.ne)
            .join(Episode, Episode.id == TaskEpisode.episode_id)
            .where(
                TaskEpisode.task_id == task.id,
                TaskEpisode.status.in_(("success", "failed")),
            )
        ).all()
        return {
            str(key): {"success": float(success), "spl": float(spl), "ne": float(ne)}
            for key, success, spl, ne in rows
        }

    data_a = load(task_a)
    data_b = load(task_b)
    keys = sorted(set(data_a) & set(data_b))
    if len(keys) < 5:
        raise AppError(
            PARAM_INVALID,
            f"两个任务共同完成的 episode 仅 {len(keys)} 条，不足以做配对检验（至少 5 条）",
        )
    return {"keys": keys, "a": data_a, "b": data_b}


def paired_bootstrap(
    db: Session,
    task_a_id: int,
    task_b_id: int,
    iterations: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    if task_a_id == task_b_id:
        raise AppError(PARAM_INVALID, "请选择两个不同的任务")
    iterations = max(200, min(int(iterations), 5000))

    tasks = _get_tasks(db, [task_a_id, task_b_id])
    task_a, task_b = tasks[0], tasks[1]
    pairs = _episode_pairs(db, task_a, task_b)
    keys = pairs["keys"]
    data_a, data_b = pairs["a"], pairs["b"]

    rng = np.random.default_rng(seed)
    index = rng.integers(0, len(keys), size=(iterations, len(keys)))

    results: dict[str, Any] = {}
    for metric, better in (("success", "higher"), ("spl", "higher"), ("ne", "lower")):
        values_a = np.array([data_a[key][metric] for key in keys], dtype=float)
        values_b = np.array([data_b[key][metric] for key in keys], dtype=float)
        mean_a = float(values_a.mean())
        mean_b = float(values_b.mean())
        observed = mean_a - mean_b

        samples = values_a[index].mean(axis=1) - values_b[index].mean(axis=1)
        low, high = np.percentile(samples, [2.5, 97.5])

        # 以观测差值中心化后做双侧检验，最小 p 值受重采样次数约束
        centered = samples - observed
        p_value = float((np.abs(centered) >= abs(observed) - 1e-12).mean())
        p_value = round(min(1.0, max(p_value, 1.0 / iterations)), 4)

        results[metric] = {
            "mean_a": round(mean_a, 4),
            "mean_b": round(mean_b, 4),
            "delta": round(observed, 4),
            "ci_low": round(float(low), 4),
            "ci_high": round(float(high), 4),
            "p_value": p_value,
            "significant": p_value < 0.05,
            "better": better,
            "favors": (
                "A" if (observed > 0) == (better == "higher") and abs(observed) > 1e-9
                else "B" if abs(observed) > 1e-9
                else "tie"
            ),
        }

    return {
        "episodes": len(keys),
        "iterations": iterations,
        "seed": seed,
        "task_a": {"id": task_a.id, "name": task_a.name},
        "task_b": {"id": task_b.id, "name": task_b.name},
        "metrics": results,
    }


def long_horizon(db: Session, task_id: int, buckets: int = 5) -> dict[str, Any]:
    task = db.get(EvalTask, task_id)
    if task is None:
        raise AppError(PARAM_INVALID, "任务不存在")

    rows = db.execute(
        select(TaskEpisode.steps, TaskEpisode.success, TaskEpisode.spl, TaskEpisode.ne)
        .where(
            TaskEpisode.task_id == task_id,
            TaskEpisode.status.in_(("success", "failed")),
        )
    ).all()
    if not rows:
        return {"task_id": task_id, "task_name": task.name, "buckets": []}

    max_steps = max(int(row[0]) for row in rows)
    max_steps = max(max_steps, buckets * 5)
    edges = [round(max_steps * i / buckets) for i in range(buckets + 1)]
    edges[0] = 0

    buckets_data = []
    for index in range(buckets):
        low, high = edges[index], edges[index + 1]
        if index == buckets - 1:
            subset = [row for row in rows if low <= int(row[0]) <= high]
        else:
            subset = [row for row in rows if low <= int(row[0]) < high]
        if not subset:
            continue
        total = len(subset)
        buckets_data.append(
            {
                "label": f"{low}-{high}",
                "low": low,
                "high": high,
                "episodes": total,
                "sr": round(sum(int(row[1]) for row in subset) / total, 4),
                "spl": round(float(np.mean([float(row[2]) for row in subset])), 4),
                "ne": round(float(np.mean([float(row[3]) for row in subset])), 3),
            }
        )

    return {
        "task_id": task_id,
        "task_name": task.name,
        "max_steps": max_steps,
        "buckets": buckets_data,
    }


def failures(db: Session, task_id: int, limit: int = 20) -> dict[str, Any]:
    task = db.get(EvalTask, task_id)
    if task is None:
        raise AppError(PARAM_INVALID, "任务不存在")

    distribution_rows = db.execute(
        select(TaskEpisode.failure_reason, TaskEpisode.manual_reason)
        .where(TaskEpisode.task_id == task_id, TaskEpisode.status == "failed")
    ).all()

    counter: dict[str, int] = defaultdict(int)
    for reason, manual in distribution_rows:
        counter[manual or reason or "unknown"] += 1

    samples = db.execute(
        select(TaskEpisode, Episode)
        .join(Episode, Episode.id == TaskEpisode.episode_id)
        .where(TaskEpisode.task_id == task_id, TaskEpisode.status == "failed")
        .order_by(TaskEpisode.ne.desc())
        .limit(limit)
    ).all()

    sample_items = [
        {
            "episode_row_id": row.id,
            "episode_key": episode.episode_id,
            "scene_id": episode.scene_id,
            "instruction": episode.instruction,
            "ne": round(row.ne, 3),
            "spl": round(row.spl, 4),
            "steps": row.steps,
            "failure_reason": row.manual_reason or row.failure_reason or "unknown",
        }
        for row, episode in samples
    ]

    total_failed = sum(counter.values())
    return {
        "task_id": task_id,
        "task_name": task.name,
        "total_failed": total_failed,
        "distribution": [
            {
                "reason": reason,
                "label": reason_label(reason),
                "count": count,
                "ratio": round(count / total_failed, 4) if total_failed else 0,
            }
            for reason, count in sorted(counter.items(), key=lambda item: item[1], reverse=True)
        ],
        "samples": sample_items,
    }
