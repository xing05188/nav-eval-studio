"""路径安全。

软件允许用户登记任意本地数据集路径，但所有运行时产物必须落在工作目录内。
对外暴露的相对路径统一通过 safe_join 解析，防止 .. 穿越。
"""

from __future__ import annotations

from pathlib import Path

from .response import PARAM_INVALID, AppError


def ensure_within(base: Path, target: Path | str) -> Path:
    """确认 target 位于 base 之内，返回绝对路径。"""
    base_resolved = base.resolve()
    candidate = Path(target)
    if not candidate.is_absolute():
        candidate = base_resolved / candidate
    resolved = candidate.resolve()
    if resolved != base_resolved and base_resolved not in resolved.parents:
        raise AppError(PARAM_INVALID, f"路径越界：{target}")
    return resolved


def safe_join(base: Path, *parts: str) -> Path:
    relative = Path(*[str(part) for part in parts if str(part)])
    return ensure_within(base, base / relative)


def task_dir(work_dir: Path, task_id: int) -> Path:
    directory = work_dir / "runs" / f"task-{task_id:06d}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def task_artifact_path(work_dir: Path, task_id: int, *parts: str) -> Path:
    directory = task_dir(work_dir, task_id)
    target = safe_join(directory, *parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def display_path(base: Path, target: Path | str) -> str:
    """转为前端可展示的相对路径，越界时返回原字符串。"""
    try:
        return str(Path(target).resolve().relative_to(base.resolve()))
    except ValueError:
        return str(target)
