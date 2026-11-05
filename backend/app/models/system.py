"""系统设置与架构版本映射。"""

from __future__ import annotations

from sqlalchemy import Column, Integer, String

from ..db.base import Base


class Setting(Base):
    __tablename__ = "setting"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=False, default="")
    updated_at = Column(String)


class SchemaVersion(Base):
    __tablename__ = "schema_version"

    version = Column(Integer, primary_key=True)
    applied_at = Column(String)
    description = Column(String, nullable=False, default="")
