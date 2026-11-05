"""分析、报告相关请求模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BootstrapRequest(BaseModel):
    task_a: int = Field(gt=0)
    task_b: int = Field(gt=0)
    iterations: int = Field(default=1000, ge=200, le=5000)
    seed: int = Field(default=42, ge=0, le=2**31 - 1)


class ReportCreate(BaseModel):
    task_ids: list[int] = Field(min_length=1, max_length=10)
    baseline_id: int | None = None
    format: Literal["md", "csv"] = "md"
    include: list[str] = Field(
        default_factory=lambda: ["summary", "metrics", "ablation", "significance", "longhorizon", "failures"]
    )
    top_failures: int = Field(default=10, ge=1, le=50)
