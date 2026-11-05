"""数据集、Episode、切分与导出相关模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    version: str = Field(default="", max_length=32)
    kind: Literal["r2r_ce", "rxr_ce", "custom"] = "r2r_ce"
    root_path: str = Field(min_length=1, max_length=512)
    instruction_lang: str = Field(default="en", max_length=16)
    scene_root: str = Field(default="", max_length=512)
    note: str = Field(default="", max_length=512)


class DatasetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    version: str | None = Field(default=None, max_length=32)
    instruction_lang: str | None = Field(default=None, max_length=16)
    root_path: str | None = Field(default=None, max_length=512)
    scene_root: str | None = Field(default=None, max_length=512)
    note: str | None = Field(default=None, max_length=512)


class DatasetOut(BaseModel):
    id: int
    name: str
    version: str
    kind: str
    root_path: str
    instruction_lang: str
    scene_count: int
    episode_count: int
    status: str
    last_scan_at: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    note: str = ""
    created_at: str | None = None
    updated_at: str | None = None


class EpisodeBrief(BaseModel):
    id: int
    episode_key: str
    scene_id: str
    instruction: str
    instruction_len: int
    traj_len: float
    duration_s: float
    has_depth: bool
    start_pose: list[float] = Field(default_factory=list)
    goal_pose: list[float] = Field(default_factory=list)


class EpisodeDetail(EpisodeBrief):
    reference_path: list[list[float]] = Field(default_factory=list)
    sensors: dict[str, bool] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)


class SplitCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: Literal["full", "smoke", "subset", "custom"] = "subset"
    base_split: str = Field(default="val_unseen", max_length=32)
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    count: int | None = Field(default=None, ge=1, le=20000)
    filters: dict[str, Any] = Field(default_factory=dict)


class SplitOut(BaseModel):
    id: int
    dataset_id: int
    name: str
    kind: str
    base_split: str
    seed: int
    episode_count: int
    filters: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


class CausalExportRequest(BaseModel):
    split_id: int | None = None
    episode_row_ids: list[int] = Field(default_factory=list)
    cutoff: int | None = Field(default=None, ge=1, le=5000)
    limit: int | None = Field(default=None, ge=1, le=5000)
