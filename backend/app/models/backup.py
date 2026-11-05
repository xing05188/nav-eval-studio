"""备份库导入来源账本与资料索引映射。"""

from __future__ import annotations

from sqlalchemy import Column, Integer, String, Text

from ..db.base import Base


class BackupAsset(Base):
    __tablename__ = "backup_asset"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_key = Column(String, nullable=False, unique=True)
    root_path = Column(String, nullable=False, default="")
    rel_path = Column(String, nullable=False, default="")
    section = Column(String, nullable=False, default="assets")
    kind = Column(String, nullable=False, default="file")
    name = Column(String, nullable=False, default="")
    size_bytes = Column(Integer, nullable=False, default=0)
    mtime = Column(String, nullable=False, default="")
    signature = Column(String, nullable=False, default="")
    entity_type = Column(String, nullable=False, default="")
    entity_id = Column(Integer)
    status = Column(String, nullable=False, default="new")
    message = Column(Text, nullable=False, default="")
    meta_json = Column(Text, nullable=False, default="{}")
    imported_at = Column(String)
    updated_at = Column(String)
