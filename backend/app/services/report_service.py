"""分析报告生成：聚合指标矩阵、消融、显著性与失败归因，输出 Markdown / CSV。

报告文件统一写入 <work_dir>/reports/，并在 artifact 表登记，便于报告中心列举与下载。
"""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.paths import display_path, ensure_within
from ..core.response import NOT_FOUND, PARAM_INVALID, AppError
from ..models import Artifact
from ..schemas.analysis import ReportCreate
from . import analysis_service

MEDIA_TYPES = {
    "md": "text/markdown; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
}

SUPPORTED_INCLUDE = ("summary", "metrics", "ablation", "significance", "longhorizon", "failures")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _format_value(column: dict[str, Any], value: float) -> str:
    if column.get("format") == "percent":
        return f"{value * 100:.2f}%"
    unit = column.get("unit") or ""
    digits = 2 if column["key"] != "gpu_mem_peak_mb" else 0
    return f"{value:.{digits}f}{unit}"


def _format_delta(column: dict[str, Any], delta: float) -> str:
    if column.get("format") == "percent":
        return f"{delta * 100:+.2f}pp"
    unit = column.get("unit") or ""
    return f"{delta:+.2f}{unit}"


def _escape(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def _task_label(row: dict[str, Any]) -> str:
    return f"{row['name']} (#{row['task_id']})"


def _summary_lines(result: dict[str, Any]) -> list[str]:
    rows = result["rows"]
    baseline = next(row for row in rows if row["task_id"] == result["baseline"])
    best_sr = max(rows, key=lambda row: row["values"]["sr"])
    best_spl = max(rows, key=lambda row: row["values"]["spl"])
    best_ne = min(rows, key=lambda row: row["values"]["ne"])

    lines = [
        "## 1. 结论摘要",
        "",
        f"- 参与对比任务 {len(rows)} 个，基线为 **{_task_label(baseline)}**。",
        f"- SR 最高：**{_task_label(best_sr)}**（{_format_value(analysis_service.METRIC_COLUMNS[0], best_sr['values']['sr'])}）。",
        f"- SPL 最高：**{_task_label(best_spl)}**（{best_spl['values']['spl'] * 100:.2f}%）。",
        f"- NE 最低：**{_task_label(best_ne)}**（{best_ne['values']['ne']:.2f}m）。",
    ]

    improved = [
        row
        for row in rows
        if row["task_id"] != baseline["task_id"]
        and row["values"]["sr"] > baseline["values"]["sr"]
    ]
    if improved:
        names = "、".join(f"{row['name']}（+{(row['values']['sr'] - baseline['values']['sr']) * 100:.2f}pp）" for row in improved)
        lines.append(f"- 相对基线 SR 提升的任务：{names}。")
    else:
        lines.append("- 所选任务中未出现相对基线 SR 提升的配置。")

    lines.append("")
    return lines


def _metrics_lines(result: dict[str, Any]) -> list[str]:
    columns = result["columns"]
    rows = result["rows"]
    baseline = result["baseline"]

    header = "| 任务 | 数据集 | 模态 | 记忆策略 | Episodes | " + " | ".join(column["label"] for column in columns) + " |"
    divider = "| --- | --- | --- | --- | ---: | " + " | ".join("---:" for _ in columns) + " |"
    lines = ["## 2. 指标对比矩阵", "", header, divider]

    for row in rows:
        marker = "（基线）" if row["task_id"] == baseline else ""
        values = " | ".join(_format_value(column, row["values"][column["key"]]) for column in columns)
        lines.append(
            f"| {_task_label(row)}{marker} | {row['dataset']} | {row['modality']} | "
            f"{row['memory_policy']} | {row['episodes']} | {values} |"
        )

    lines += ["", "### 2.1 相对基线差值", ""]
    lines.append("| 任务 | " + " | ".join(f"Δ{column['label']}" for column in columns) + " |")
    lines.append("| --- | " + " | ".join("---:" for _ in columns) + " |")
    for row in rows:
        if row["task_id"] == baseline:
            continue
        deltas = " | ".join(
            _format_delta(column, result["delta"][column["key"]].get(str(row["task_id"]), result["delta"][column["key"]].get(row["task_id"], 0)))
            for column in columns
        )
        lines.append(f"| {_task_label(row)} | {deltas} |")
    lines.append("")
    return lines


def _ablation_lines(db: Session, task_ids: list[int]) -> list[str]:
    result = analysis_service.ablation(db, task_ids)
    lines = ["## 3. 模态 × 记忆策略消融", ""]
    if len(result["rows"]) < 2:
        lines += ["所选任务的模态与记忆策略组合不足两组，未形成有效消融对照。", ""]
        return lines

    lines += [
        "| 模态 | 记忆策略 | 任务数 | SR | SPL | NE(m) | nDTW | Latency(ms) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in result["rows"]:
        values = row["values"]
        lines.append(
            f"| {row['modality']} | {row['memory_policy']} | {row['tasks']} | "
            f"{values['sr'] * 100:.2f}% | {values['spl'] * 100:.2f}% | {values['ne']:.2f} | "
            f"{values['ndtw'] * 100:.2f}% | {values['latency_avg_ms']:.1f} |"
        )

    lines += ["", "### 3.1 SR 消融热力表", ""]
    lines.append("| 模态 \\ 记忆策略 | " + " | ".join(result["policies"]) + " |")
    lines.append("| --- | " + " | ".join("---:" for _ in result["policies"]) + " |")
    for modality in result["modalities"]:
        cells = []
        for policy in result["policies"]:
            values = result["matrix"][modality][policy]
            cells.append(f"{values['sr'] * 100:.2f}%" if values else "—")
        lines.append(f"| {modality} | " + " | ".join(cells) + " |")
    lines.append("")
    return lines


def _significance_lines(db: Session, result: dict[str, Any]) -> list[str]:
    rows = result["rows"]
    baseline = result["baseline"]
    base_row = next(row for row in rows if row["task_id"] == baseline)
    lines = ["## 4. 配对 Bootstrap 显著性检验", ""]
    others = [row for row in rows if row["task_id"] != baseline]
    if not others:
        lines += ["仅有一个任务，无法进行配对检验。", ""]
        return lines

    for row in others:
        try:
            test = analysis_service.paired_bootstrap(db, row["task_id"], baseline, iterations=1000, seed=42)
        except AppError as exc:
            lines += [f"**{_task_label(row)} vs {_task_label(base_row)}**：{exc.message}。", ""]
            continue

        lines.append(
            f"**{_task_label(row)} vs {_task_label(base_row)}**（配对 episode {test['episodes']} 条，"
            f"{test['iterations']} 次重采样）"
        )
        lines.append("")
        lines.append("| 指标 | A 均值 | B 均值 | 差值 | 95% CI | p 值 | 结论 |")
        lines.append("| --- | ---: | ---: | ---: | --- | ---: | --- |")
        for key, label, scale in (("success", "SR", 100), ("spl", "SPL", 100), ("ne", "NE(m)", 1)):
            item = test["metrics"][key]
            conclusion = "显著" if item["significant"] else "不显著"
            favor = {"A": "A 更优", "B": "B 更优", "tie": "持平"}[item["favors"]]
            lines.append(
                f"| {label} | {item['mean_a'] * scale:.2f} | {item['mean_b'] * scale:.2f} | "
                f"{item['delta'] * scale:+.2f} | [{item['ci_low'] * scale:.2f}, {item['ci_high'] * scale:.2f}] | "
                f"{item['p_value']:.4f} | {conclusion}，{favor} |"
            )
        lines.append("")
    return lines


def _long_horizon_lines(db: Session, result: dict[str, Any]) -> list[str]:
    baseline = result["baseline"]
    row = next(item for item in result["rows"] if item["task_id"] == baseline)
    data = analysis_service.long_horizon(db, baseline, buckets=5)
    lines = [f"## 5. 长时性能分桶（{_task_label(row)}）", ""]
    buckets = data.get("buckets") or []
    if not buckets:
        lines += ["该任务暂无已完成的 episode。", ""]
        return lines

    lines += [
        "| 步数区间 | Episodes | SR | SPL | NE(m) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for item in buckets:
        lines.append(
            f"| {item['label']} | {item['episodes']} | {item['sr'] * 100:.2f}% | "
            f"{item['spl'] * 100:.2f}% | {item['ne']:.2f} |"
        )
    lines.append("")
    return lines


def _failure_lines(db: Session, result: dict[str, Any], top: int) -> list[str]:
    baseline = result["baseline"]
    row = next(item for item in result["rows"] if item["task_id"] == baseline)
    data = analysis_service.failures(db, baseline, limit=top)
    lines = [f"## 6. 失败归因（{_task_label(row)}）", ""]
    if not data["total_failed"]:
        lines += ["该任务没有失败 episode。", ""]
        return lines

    lines += [f"失败共 {data['total_failed']} 条，归因分布如下：", ""]
    lines += ["| 失败原因 | 数量 | 占比 |", "| --- | ---: | ---: |"]
    for item in data["distribution"]:
        lines.append(f"| {item['label']} | {item['count']} | {item['ratio'] * 100:.1f}% |")

    lines += ["", f"### 6.1 典型失败样本（按 NE 降序，最多 {top} 条）", ""]
    lines += [
        "| Episode | 场景 | 指令 | NE(m) | SPL | 步数 | 原因 |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for sample in data["samples"]:
        lines.append(
            f"| {sample['episode_key']} | {sample['scene_id']} | {_escape(sample['instruction'])} | "
            f"{sample['ne']:.2f} | {sample['spl'] * 100:.2f}% | {sample['steps']} | "
            f"{analysis_service.reason_label(sample['failure_reason'])} |"
        )
    lines.append("")
    return lines


def build_markdown(
    db: Session,
    payload: ReportCreate,
) -> str:
    task_ids = list(dict.fromkeys(int(item) for item in payload.task_ids))
    compare = analysis_service.compare(db, task_ids, baseline_id=payload.baseline_id)
    include = [item for item in (payload.include or []) if item in SUPPORTED_INCLUDE]

    lines = [
        "# 具身导航评测分析报告",
        "",
        f"- 生成时间：{_now()}",
        f"- 任务数量：{len(compare['rows'])}",
        f"- 基线任务：{_task_label(next(row for row in compare['rows'] if row['task_id'] == compare['baseline']))}",
        "- 数据来源：NavEval Studio 评测数据库",
        "",
    ]

    if not include or "summary" in include:
        lines += _summary_lines(compare)
    if not include or "metrics" in include:
        lines += _metrics_lines(compare)
    if "ablation" in include:
        lines += _ablation_lines(db, task_ids)
    if "significance" in include:
        lines += _significance_lines(db, compare)
    if "longhorizon" in include:
        lines += _long_horizon_lines(db, compare)
    if "failures" in include:
        lines += _failure_lines(db, compare, int(payload.top_failures))

    lines += ["---", "", "报告由 NavEval Studio 自动生成，指标口径见系统文档。", ""]
    return "\n".join(lines)


def build_csv(db: Session, payload: ReportCreate) -> str:
    task_ids = list(dict.fromkeys(int(item) for item in payload.task_ids))
    compare = analysis_service.compare(db, task_ids, baseline_id=payload.baseline_id)
    columns = compare["columns"]
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")

    writer.writerow(
        ["task_id", "task_name", "dataset", "modality", "memory_policy", "episodes", "is_baseline"]
        + [column["key"] for column in columns]
        + [f"{column['key']}_delta" for column in columns]
    )
    for row in compare["rows"]:
        is_baseline = "1" if row["task_id"] == compare["baseline"] else "0"
        values = [row["values"][column["key"]] for column in columns]
        deltas = [
            compare["delta"][column["key"]].get(str(row["task_id"]), compare["delta"][column["key"]].get(row["task_id"], 0))
            for column in columns
        ]
        writer.writerow(
            [
                row["task_id"],
                row["name"],
                row["dataset"],
                row["modality"],
                row["memory_policy"],
                row["episodes"],
                is_baseline,
            ]
            + values
            + deltas
        )
    return buffer.getvalue()


def to_dict(artifact: Artifact) -> dict[str, Any]:
    name = artifact.name or ""
    fmt = Path(name).suffix.lstrip(".").lower() or "md"
    return {
        "id": artifact.id,
        "task_id": artifact.task_id,
        "task_ids": _task_ids_from_name(name),
        "kind": artifact.kind,
        "name": name,
        "format": fmt,
        "path": artifact.path,
        "size_bytes": artifact.size_bytes,
        "created_at": artifact.created_at,
        "download_url": f"/api/reports/{artifact.id}/download",
    }


def _task_ids_from_name(name: str) -> list[int]:
    stem = Path(name or "").stem
    for part in stem.split("-"):
        if part.startswith("t") and part[1:]:
            return [int(item) for item in part[1:].split("_") if item.isdigit()]
    return []


def generate(db: Session, payload: ReportCreate) -> dict[str, Any]:
    task_ids = list(dict.fromkeys(int(item) for item in payload.task_ids))
    if not task_ids:
        raise AppError(PARAM_INVALID, "请至少选择一个任务")

    content = build_csv(db, payload) if payload.format == "csv" else build_markdown(db, payload)
    settings = get_settings()
    settings.reports_dir.mkdir(parents=True, exist_ok=True)

    filename = f"report-{_stamp()}-t{'_'.join(str(item) for item in task_ids)}.{payload.format}"
    target = ensure_within(settings.reports_dir, settings.reports_dir / filename)
    encoding = "utf-8-sig" if payload.format == "csv" else "utf-8"
    data = content.encode(encoding)
    target.write_bytes(data)

    artifact = Artifact(
        task_id=task_ids[0],
        kind="report",
        name=filename,
        path=display_path(settings.storage.work_dir, target),
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        created_at=_now(),
    )
    db.add(artifact)
    db.flush()
    return to_dict(artifact)


def list_reports(db: Session, task_id: int | None = None) -> list[dict[str, Any]]:
    artifacts = db.scalars(
        select(Artifact).where(Artifact.kind == "report").order_by(Artifact.id.desc())
    ).all()
    items = []
    settings = get_settings()
    for artifact in artifacts:
        item = to_dict(artifact)
        if task_id and task_id not in item["task_ids"]:
            continue
        item["exists"] = (settings.storage.work_dir / artifact.path).exists()
        items.append(item)
    return items


def resolve(db: Session, artifact_id: int) -> tuple[Artifact, Path]:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None or artifact.kind != "report":
        raise AppError(NOT_FOUND, "报告不存在")
    settings = get_settings()
    target = ensure_within(settings.storage.work_dir, settings.storage.work_dir / artifact.path)
    if not target.exists():
        raise AppError(NOT_FOUND, "报告文件已丢失，请重新生成")
    return artifact, target
