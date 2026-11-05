"""用户与审计日志映射。"""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, String, Text

from ..db.base import Base


class AppUser(Base):
    __tablename__ = "app_user"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, nullable=False, unique=True)
    display_name = Column(String, nullable=False, default="")
    password_hash = Column(String, nullable=False)
    password_salt = Column(String, nullable=False)
    role = Column(String, nullable=False, default="operator")
    enabled = Column(Integer, nullable=False, default=1)
    last_login_at = Column(String)
    created_at = Column(String)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("app_user.id", ondelete="SET NULL"))
    username = Column(String, nullable=False, default="")
    action = Column(String, nullable=False)
    target_type = Column(String, nullable=False, default="")
    target_id = Column(String, nullable=False, default="")
    detail_json = Column(Text, nullable=False, default="{}")
    client_ip = Column(String, nullable=False, default="")
    created_at = Column(String)
