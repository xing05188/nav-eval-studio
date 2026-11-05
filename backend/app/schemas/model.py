"""模型档案与配置模板模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    family: Literal["streamvln", "mock", "custom"] = "streamvln"
    code_path: str = Field(default="", max_length=512)
    weights_path: str = Field(default="", max_length=512)
    entry: str = Field(default="", max_length=256)
    default_config: dict[str, Any] = Field(default_factory=dict)
    needs_gpu: bool = True
    allowed_inputs: list[str] = Field(default_factory=lambda: ["rgb", "depth", "pose", "action"])
    description: str = Field(default="", max_length=512)


class ModelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    code_path: str | None = Field(default=None, max_length=512)
    weights_path: str | None = Field(default=None, max_length=512)
    entry: str | None = Field(default=None, max_length=256)
    default_config: dict[str, Any] | None = None
    needs_gpu: bool | None = None
    allowed_inputs: list[str] | None = None
    description: str | None = Field(default=None, max_length=512)


class ModelOut(BaseModel):
    id: int
    name: str
    family: str
    code_path: str
    weights_path: str
    entry: str
    default_config: dict[str, Any] = Field(default_factory=dict)
    needs_gpu: bool
    allowed_inputs: list[str] = Field(default_factory=list)
    status: str
    description: str = ""
    updated_at: str | None = None


class ProbeCheck(BaseModel):
    name: str
    ok: bool
    detail: str = ""


class ProbeResult(BaseModel):
    model_id: int
    status: str
    checks: list[ProbeCheck] = Field(default_factory=list)
    suggestion: str = ""


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    modality: Literal["vision", "vision_geo", "vision_geo_state"] = "vision"
    memory_policy: Literal[
        "fixed_window", "sliding_window", "feature_cache", "spatial_prune", "hybrid"
    ] = "fixed_window"
    params: dict[str, Any] = Field(default_factory=dict)
    description: str = Field(default="", max_length=512)


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    params: dict[str, Any] | None = None
    description: str | None = Field(default=None, max_length=512)


class TemplateOut(BaseModel):
    id: int
    name: str
    modality: str
    memory_policy: str
    params: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    builtin: bool = False
