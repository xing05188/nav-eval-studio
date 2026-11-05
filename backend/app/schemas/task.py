"""评测任务相关模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    dataset_id: int
    split_id: int
    model_profile_id: int
    template_id: int | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=5, ge=1, le=9)
    gpu_ids: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=512)


class TaskBrief(BaseModel):
    id: int
    name: str
    status: str
    dataset_id: int
    dataset_name: str = ""
    split_id: int
    split_name: str = ""
    model_profile_id: int
    model_name: str = ""
    progress_done: int = 0
    progress_total: int = 0
    metrics: dict[str, Any] = Field(default_factory=dict)
    error_msg: str = ""
    queued_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_s: float | None = None
    note: str = ""


class TaskEpisodeOut(BaseModel):
    id: int
    episode_key: str
    scene_id: str
    instruction: str = ""
    status: str
    success: bool = False
    spl: float = 0
    ne: float = 0
    os: float = 0
    ndtw: float = 0
    tl: float = 0
    steps: int = 0
    latency_avg_ms: float = 0
    gpu_mem_peak_mb: int = 0
    failure_reason: str = ""
    manual_reason: str = ""


class TaskControlResponse(BaseModel):
    task_id: int
    status: str
    message: str = ""


class TaskLogResponse(BaseModel):
    lines: list[str] = Field(default_factory=list)
    total_lines: int = 0
