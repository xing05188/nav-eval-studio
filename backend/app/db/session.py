"""数据库引擎与会话。

建库使用 schema.sql 一次性执行，运行时由 SQLAlchemy 管理连接。
SQLite 开启 WAL 与外键约束，超时 30 秒以吸收并发写。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from ..core.config import Settings, get_settings

SCHEMA_FILE = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 1

_engine: Engine | None = None
_session_factory: sessionmaker | None = None


def _schema_applied(db_path: Path) -> bool:
    if not db_path.exists():
        return False
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
            ).fetchone()
            return row is not None
    except sqlite3.DatabaseError:
        return False


def _apply_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(sql)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
            (SCHEMA_VERSION, "initial schema"),
        )
        conn.commit()


def configure(settings: Settings | None = None) -> Engine:
    """构建引擎（幂等）。"""
    global _engine, _session_factory
    settings = settings or get_settings()
    if _engine is not None:
        return _engine

    db_path = settings.storage.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        future=True,
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    _engine = engine
    _session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine


def get_engine() -> Engine:
    if _engine is None:
        return configure()
    return _engine


def get_session_factory() -> sessionmaker:
    if _session_factory is None:
        configure()
    assert _session_factory is not None
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """供服务层使用的会话上下文，异常自动回滚。"""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI 依赖。"""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_database(settings: Settings | None = None) -> bool:
    """建库并执行迁移，返回是否为首次创建。"""
    settings = settings or get_settings()
    settings.ensure_dirs()
    db_path = settings.storage.db_path
    first_time = not _schema_applied(db_path)
    if first_time:
        _apply_schema(db_path)
    configure(settings)
    _migrate()
    return first_time


def _migrate() -> None:
    """按 schema_version 顺序执行补丁脚本（当前仅初始版本）。"""
    migrations_dir = Path(__file__).with_name("migrations")
    if not migrations_dir.exists():
        return

    with session_scope() as session:
        current = session.execute(text("SELECT COALESCE(MAX(version), 0) FROM schema_version")).scalar()

    for script in sorted(migrations_dir.glob("*.sql")):
        try:
            version = int(script.stem.split("_", 1)[0])
        except ValueError:
            continue
        if version <= current:
            continue
        with sqlite3.connect(get_settings().storage.db_path) as conn:
            conn.executescript(script.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
                (version, script.stem),
            )
            conn.commit()


def reset_engine() -> None:
    """测试用：释放引擎，下次访问重新构建。"""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
