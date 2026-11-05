"""系统设置相关模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SettingItem(BaseModel):
    key: str
    value: str


class SettingsUpdate(BaseModel):
    items: list[SettingItem] = Field(default_factory=list)


class AuditQuery(BaseModel):
    action: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)
