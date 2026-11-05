"""历史评测产物与备份库自动导入请求模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ResultImportRequest(BaseModel):
    root_path: str | None = Field(default=None, max_length=512)
    dry_run: bool = False
    force: bool = False


class BackupImportRequest(BaseModel):
    """备份库导入；sections 为空表示按配置导入全部类别。"""

    root_path: str | None = Field(default=None, max_length=512)
    sections: list[str] = Field(default_factory=list, max_length=8)
    dry_run: bool = False
    force: bool = False
    scan_episodes: bool | None = None


class BackupAutoConfig(BaseModel):
    """运行时自动导入开关；未提供的字段保持原值。"""

    enabled: bool | None = None
    interval_s: int | None = Field(default=None, ge=10, le=86400)
    root_path: str | None = Field(default=None, max_length=512)
    sections: list[str] | None = Field(default=None, max_length=8)
