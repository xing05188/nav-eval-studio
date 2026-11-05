"""备份库自动导入守护。

应用启动后自动同步一次备份库，之后按配置间隔计算目录指纹；目录发生变化时
执行增量导入（服务层按 source_key + signature 幂等，已导入的对象会跳过）。

运行时开关保存在 `setting` 表，修改后立即生效，无需重启服务：
`backup_auto_enabled` / `backup_auto_interval_s` / `backup_import_root` / `backup_auto_sections`。
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import ALL_IMPORT_SECTIONS, get_settings
from ..db.session import session_scope
from ..models import EvalTask, Setting
from . import backup_import_service

logger = logging.getLogger(__name__)

STARTUP_DELAY_S = 3
CHECK_INTERVAL_S = 5
ERROR_RETRY_S = 15
ACTIVE_POLL_S = 60

SETTING_MAP = {
    "enabled": "backup_auto_enabled",
    "interval_s": "backup_auto_interval_s",
    "root": "backup_import_root",
    "sections": "backup_auto_sections",
}


def load_auto_config() -> dict[str, Any]:
    """读取自动导入配置：YAML 为默认值，setting 表为运行时覆盖。"""
    settings = get_settings()
    config: dict[str, Any] = {
        "enabled": settings.imports.auto_enabled,
        "interval_s": settings.imports.auto_interval_s,
        "root": str(settings.imports.backup_root),
        "sections": list(settings.imports.auto_sections),
        "scan_limit_mb": settings.imports.scan_limit_mb,
    }
    with session_scope() as db:
        rows = {row.key: row.value for row in db.scalars(select(Setting)).all()}

    if "backup_auto_enabled" in rows:
        config["enabled"] = rows["backup_auto_enabled"] == "1"
    if "backup_auto_interval_s" in rows:
        try:
            config["interval_s"] = max(10, int(rows["backup_auto_interval_s"]))
        except ValueError:
            pass
    if rows.get("backup_import_root"):
        config["root"] = rows["backup_import_root"]
    if "backup_auto_sections" in rows:
        sections = [item.strip() for item in rows["backup_auto_sections"].split(",") if item.strip()]
        config["sections"] = [item for item in sections if item in ALL_IMPORT_SECTIONS]
    return config


def update_auto_config(db: Session, payload: Any) -> dict[str, Any]:
    """更新运行时开关，并通知守护任务尽快重新同步。"""
    config = load_auto_config()
    changed: dict[str, Any] = {}

    if payload.enabled is not None:
        config["enabled"] = bool(payload.enabled)
        changed[SETTING_MAP["enabled"]] = "1" if config["enabled"] else "0"
    if payload.interval_s is not None:
        config["interval_s"] = max(10, int(payload.interval_s))
        changed[SETTING_MAP["interval_s"]] = str(config["interval_s"])
    if payload.root_path is not None:
        root = str(Path(payload.root_path).expanduser())
        config["root"] = root
        changed[SETTING_MAP["root"]] = root
    if payload.sections is not None:
        sections = [str(item) for item in payload.sections if item in ALL_IMPORT_SECTIONS]
        config["sections"] = sections
        changed[SETTING_MAP["sections"]] = ",".join(sections)

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for key, value in changed.items():
        row = db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=value, updated_at=stamp))
        else:
            row.value = value
            row.updated_at = stamp
    db.commit()

    importer = get_auto_importer()
    importer.notify_config(config, force=bool(changed))
    return importer.status()


def count_running_tasks() -> int:
    """存在外部运行中的导入任务时，需要更频繁地刷新进度与状态时效。"""
    with session_scope() as db:
        return (
            db.scalar(
                select(func.count()).select_from(EvalTask).where(EvalTask.status == "running")
            )
            or 0
        )


def _slim(summary: dict[str, Any]) -> dict[str, Any]:
    """状态接口只保留汇总，避免携带上百条明细。"""
    return {
        "root": summary.get("root"),
        "dry_run": summary.get("dry_run"),
        "sections": summary.get("sections"),
        "scanned": summary.get("scanned"),
        "created": summary.get("created"),
        "updated": summary.get("updated"),
        "skipped": summary.get("skipped"),
        "unmatched": summary.get("unmatched"),
        "failed": summary.get("failed"),
        "duration_s": summary.get("duration_s"),
        "finished_at": summary.get("finished_at"),
        "section_counts": summary.get("section_counts"),
        "asset_counts": summary.get("asset_counts"),
    }


class BackupAutoImporter:
    """单例守护任务；文件与数据库操作一律放到线程中执行，不阻塞事件循环。"""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        # 单例可能在同步接口的工作线程里首次构造，Lock 必须延迟到事件循环中创建
        self._lock: asyncio.Lock | None = None
        self._force_next = True
        self._last_run_ts = 0.0
        self._config: dict[str, Any] = {}
        self._state: dict[str, Any] = {
            "running": False,
            "last_run_at": "",
            "last_reason": "",
            "last_error": "",
            "last_signature": "",
            "last_summary": None,
            "total_runs": 0,
        }

    async def start(self) -> None:
        if self._lock is None:
            self._lock = asyncio.Lock()
        try:
            # 先同步一次配置，状态接口在守护首轮轮询前就能返回真实开关值
            self._config = await asyncio.to_thread(load_auto_config)
        except Exception as exc:  # noqa: BLE001 - 启动失败不应阻断服务
            logger.warning("备份库自动导入配置读取失败：%s", exc)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="backup-auto-import")
            logger.info("备份库自动导入守护已启动")

    async def shutdown(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    def notify_config(self, config: dict[str, Any], *, force: bool = False) -> None:
        self._config = dict(config)
        if force:
            self._force_next = True
            self._last_run_ts = 0.0

    def status(self) -> dict[str, Any]:
        config = self._config or {
            "enabled": get_settings().imports.auto_enabled,
            "interval_s": get_settings().imports.auto_interval_s,
            "root": str(get_settings().imports.backup_root),
            "sections": list(get_settings().imports.auto_sections),
        }
        elapsed = time.monotonic() - self._last_run_ts if self._last_run_ts else 0
        remaining = max(0, int(config.get("interval_s", 300)) - elapsed)
        next_run_at = (
            (datetime.now() + timedelta(seconds=remaining)).strftime("%Y-%m-%d %H:%M:%S")
            if config.get("enabled") and self._state["last_run_at"]
            else ""
        )
        return {
            **config,
            **self._state,
            "last_signature": self._state["last_signature"][:12],
            "next_run_at": next_run_at,
            "active": bool(self._task and not self._task.done()),
        }

    async def _loop(self) -> None:
        await asyncio.sleep(STARTUP_DELAY_S)
        while True:
            try:
                self._config = await asyncio.to_thread(load_auto_config)
            except Exception as exc:  # noqa: BLE001 - 配置读取失败不应终止守护
                self._state["last_error"] = f"读取配置失败：{str(exc)[:200]}"
                logger.warning("备份库自动导入配置读取失败：%s", exc)
                await asyncio.sleep(ERROR_RETRY_S)
                continue

            if not self._config["enabled"]:
                await asyncio.sleep(CHECK_INTERVAL_S)
                continue

            root = Path(self._config["root"])
            try:
                signature = await asyncio.to_thread(
                    backup_import_service.directory_signature, root
                )
            except OSError as exc:
                self._state["last_error"] = f"扫描目录失败：{str(exc)[:200]}"
                signature = ""
            try:
                running_tasks = await asyncio.to_thread(count_running_tasks)
            except Exception:  # noqa: BLE001 - 状态查询失败不影响主流程
                running_tasks = 0

            interval = (
                min(self._config["interval_s"], ACTIVE_POLL_S)
                if running_tasks
                else self._config["interval_s"]
            )
            elapsed = time.monotonic() - self._last_run_ts if self._last_run_ts else 0
            due = elapsed >= interval
            first_run = not self._state["last_run_at"]
            changed = signature != self._state["last_signature"]
            if first_run or self._force_next or (due and (changed or running_tasks)):
                await self.run_once(
                    "startup" if first_run else ("config" if self._force_next else "change"),
                    signature,
                )
            await asyncio.sleep(CHECK_INTERVAL_S)

    async def run_once(self, reason: str, signature: str) -> None:
        """执行一次同步，供守护循环与手动触发共用。"""
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._state["running"]:
                return
            self._state["running"] = True
            config = dict(self._config)
            try:

                def _work() -> dict[str, Any]:
                    with session_scope() as db:
                        return backup_import_service.run_import(
                            db,
                            config["root"],
                            sections=config["sections"],
                            dry_run=False,
                            force=False,
                            reason=reason,
                        )

                summary = await asyncio.to_thread(_work)
                self._state["last_summary"] = _slim(summary)
                self._state["last_run_at"] = summary["finished_at"]
                self._state["last_reason"] = reason
                self._state["last_error"] = ""
                self._state["last_signature"] = signature
                self._state["total_runs"] += 1
                self._force_next = False
                logger.info(
                    "备份库自动导入完成 reason=%s 扫描=%s 新增=%s 更新=%s 跳过=%s 失败=%s",
                    reason,
                    summary["scanned"],
                    summary["created"],
                    summary["updated"],
                    summary["skipped"],
                    summary["failed"],
                )
            except Exception as exc:  # noqa: BLE001 - 单次失败不应终止守护
                logger.exception("备份库自动导入失败")
                self._state["last_error"] = str(exc)[:300]
                self._state["last_run_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._state["last_reason"] = reason
            finally:
                self._state["running"] = False
                self._last_run_ts = time.monotonic()


_auto_importer: BackupAutoImporter | None = None


def get_auto_importer() -> BackupAutoImporter:
    global _auto_importer
    if _auto_importer is None:
        _auto_importer = BackupAutoImporter()
    return _auto_importer
