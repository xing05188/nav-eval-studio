"""配置加载。

优先级：环境变量 > config/default.yaml > 内置默认值。
所有相对路径以仓库根目录为基准解析，避免工作目录不同导致路径漂移。
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parents[3]
CONFIG_DIR = ROOT_DIR / "config"

DEFAULT_CONFIG: dict[str, Any] = {
    "server": {"host": "0.0.0.0", "port": 8080, "open_browser": False},
    "storage": {
        "work_dir": "./storage",
        "db_path": "./storage/eval.db",
        "artifact_keep_days": 90,
    },
    "scheduler": {
        "max_parallel_tasks": 2,
        "episode_timeout_s": 300,
        "poll_interval_ms": 500,
        "gpu_ids": [],
    },
    "security": {"token_ttl_hours": 12, "pbkdf2_iterations": 200000},
    "logging": {"level": "INFO", "keep_days": 30},
    "demo": {"enabled": True, "sample_results_dir": "./storage/sample_results"},
    "import": {
        "results_root": "",
        "backup_root": "",
        "auto_enabled": True,
        "auto_interval_s": 300,
        "auto_sections": ["datasets", "scenes", "models", "results", "assets"],
        "auto_scan_episodes": True,
        "scan_limit_mb": 32,
        "scan_exclude": ["train", "envdrop", "scalevln"],
        "running_grace_s": 600,
    },
    "sim": {
        "scene_root": "",
        "gpu_ids": [0],
        "tick_hz": 4.0,
        "render_hz": 15.0,
        "stream_hz": 20.0,
        "jpeg_quality": 82,
        "max_clients": 4,
        "idle_timeout_s": 900,
        "free_mem_warn_mb": 4096,
    },
    "policy": {
        "enabled": True,
        "model_profile": "",
        "gpu_id": None,
        "min_free_mem_mb": 12000,
        "num_frames": 8,
        "num_history": 8,
        "num_future_steps": 4,
        "infer_timeout_s": 30,
        "idle_pause_s": 60,
    },
}

ALL_IMPORT_SECTIONS = ("datasets", "scenes", "models", "results", "assets")


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    open_browser: bool = False


@dataclass
class StorageConfig:
    work_dir: Path = ROOT_DIR / "storage"
    db_path: Path = ROOT_DIR / "storage" / "eval.db"
    artifact_keep_days: int = 90


@dataclass
class SchedulerConfig:
    max_parallel_tasks: int = 2
    episode_timeout_s: int = 300
    poll_interval_ms: int = 500
    gpu_ids: list[str] = field(default_factory=list)


@dataclass
class SecurityConfig:
    token_ttl_hours: int = 12
    pbkdf2_iterations: int = 200000


@dataclass
class LoggingConfig:
    level: str = "INFO"
    keep_days: int = 30


@dataclass
class DemoConfig:
    enabled: bool = True
    sample_results_dir: Path = ROOT_DIR / "storage" / "sample_results"


@dataclass
class ImportConfig:
    """历史评测产物与备份库自动导入的默认绑定。"""

    results_root: Path = ROOT_DIR / "storage" / "sample_results"
    backup_root: Path = ROOT_DIR / "storage" / "sample_results"
    auto_enabled: bool = True
    auto_interval_s: int = 300
    auto_sections: list[str] = field(default_factory=lambda: list(ALL_IMPORT_SECTIONS))
    auto_scan_episodes: bool = True
    scan_limit_mb: int = 32
    scan_exclude: list[str] = field(default_factory=lambda: ["train", "envdrop", "scalevln"])
    running_grace_s: int = 600


@dataclass
class SimConfig:
    """交互式仿真：场景根目录与渲染/会话参数（全部有默认值，缺省也能启动）。"""

    scene_root: Path | None = None
    gpu_ids: list[int] = field(default_factory=lambda: [0])
    tick_hz: float = 4.0
    render_hz: float = 15.0
    stream_hz: float = 20.0
    jpeg_quality: int = 82
    max_clients: int = 4
    idle_timeout_s: int = 900
    free_mem_warn_mb: int = 4096


@dataclass
class PolicyConfig:
    """模型驾驶：一次 forward 出几个动作、显存门槛、超时。

    全部有默认值——`enabled: false` 时接口直接拒绝，页面也不会显示入口，
    手动驾驶完全不受影响。
    """

    enabled: bool = True
    model_profile: str = ""
    gpu_id: int | None = None
    min_free_mem_mb: int = 12000
    num_frames: int = 8
    num_history: int = 8
    num_future_steps: int = 4
    infer_timeout_s: float = 30.0
    idle_pause_s: float = 60.0


@dataclass
class Settings:
    """进程内全局配置。"""

    root: Path
    server: ServerConfig
    storage: StorageConfig
    scheduler: SchedulerConfig
    security: SecurityConfig
    logging: LoggingConfig
    demo: DemoConfig
    imports: ImportConfig = field(default_factory=ImportConfig)
    sim: SimConfig = field(default_factory=SimConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    metrics: dict[str, Any] = field(default_factory=dict)
    models: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    # ---- 常用派生路径 ----
    @property
    def runs_dir(self) -> Path:
        return self.storage.work_dir / "runs"

    @property
    def reports_dir(self) -> Path:
        return self.storage.work_dir / "reports"

    @property
    def cache_dir(self) -> Path:
        return self.storage.work_dir / "cache"

    @property
    def logs_dir(self) -> Path:
        return self.storage.work_dir / "logs"

    @property
    def secret_file(self) -> Path:
        return self.storage.work_dir / "secret.key"

    def ensure_dirs(self) -> None:
        for path in (
            self.storage.work_dir,
            self.runs_dir,
            self.reports_dir,
            self.cache_dir,
            self.logs_dir,
            self.storage.db_path.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)


def _deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _resolve(path_value: str | Path) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = (ROOT_DIR / path).resolve()
    return path


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _load_import_config(data: dict[str, Any]) -> ImportConfig:
    """组装导入配置；未单独配置备份根目录时沿用历史产物根目录。"""
    raw = data.get("import", {}) or {}
    fallback = raw.get("results_root") or data["demo"]["sample_results_dir"]
    sections = [str(item) for item in raw.get("auto_sections", ALL_IMPORT_SECTIONS)]
    sections = [item for item in sections if item in ALL_IMPORT_SECTIONS]
    return ImportConfig(
        results_root=_resolve(fallback),
        backup_root=_resolve(raw.get("backup_root") or fallback),
        auto_enabled=bool(raw.get("auto_enabled", True)),
        auto_interval_s=max(10, int(raw.get("auto_interval_s", 300))),
        auto_sections=sections or list(ALL_IMPORT_SECTIONS),
        auto_scan_episodes=bool(raw.get("auto_scan_episodes", True)),
        scan_limit_mb=max(1, int(raw.get("scan_limit_mb", 32))),
        scan_exclude=[str(item).lower() for item in raw.get("scan_exclude", ["train", "envdrop", "scalevln"])],
        running_grace_s=max(30, int(raw.get("running_grace_s", 600))),
    )


def _load_sim_config(data: dict[str, Any]) -> SimConfig:
    """组装仿真配置；场景根目录留空时由 episode 解析按数据集元数据回退。"""
    raw = data.get("sim", {}) or {}
    scene_root = str(raw.get("scene_root") or "").strip()
    gpu_ids: list[int] = []
    for item in raw.get("gpu_ids") or [0]:
        try:
            gpu_ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return SimConfig(
        scene_root=_resolve(scene_root) if scene_root else None,
        gpu_ids=gpu_ids or [0],
        tick_hz=float(raw.get("tick_hz", 4.0)),
        render_hz=float(raw.get("render_hz", 15.0)),
        stream_hz=float(raw.get("stream_hz", 20.0)),
        jpeg_quality=max(40, min(98, int(raw.get("jpeg_quality", 82)))),
        max_clients=max(1, int(raw.get("max_clients", 4))),
        idle_timeout_s=max(0, int(raw.get("idle_timeout_s", 900))),
        free_mem_warn_mb=max(0, int(raw.get("free_mem_warn_mb", 4096))),
    )


def _load_policy_config(data: dict[str, Any]) -> PolicyConfig:
    """组装模型驾驶配置；gpu_id 留空表示自动挑空闲显存最多的一张卡。"""
    raw = data.get("policy", {}) or {}
    gpu_raw = raw.get("gpu_id", None)
    gpu_id: int | None = None
    if gpu_raw is not None and str(gpu_raw).strip() != "":
        try:
            gpu_id = int(gpu_raw)
        except (TypeError, ValueError):
            gpu_id = None
    return PolicyConfig(
        enabled=bool(raw.get("enabled", True)),
        model_profile=str(raw.get("model_profile") or "").strip(),
        gpu_id=gpu_id,
        min_free_mem_mb=max(0, int(raw.get("min_free_mem_mb", 12000))),
        num_frames=max(1, int(raw.get("num_frames", 8))),
        num_history=max(1, int(raw.get("num_history", 8))),
        num_future_steps=max(1, int(raw.get("num_future_steps", 4))),
        infer_timeout_s=float(raw.get("infer_timeout_s", 30)),
        idle_pause_s=float(raw.get("idle_pause_s", 60)),
    )


def load_settings(config_path: str | Path | None = None) -> Settings:
    """读取配置并组装为 Settings。"""
    path = Path(config_path) if config_path else Path(
        os.environ.get("NAVEVAL_CONFIG", CONFIG_DIR / "default.yaml")
    )
    data = _deep_merge(DEFAULT_CONFIG, _load_yaml(path))

    # 环境变量覆盖，便于容器化部署
    if os.environ.get("NAVEVAL_HOST"):
        data["server"]["host"] = os.environ["NAVEVAL_HOST"]
    if os.environ.get("NAVEVAL_PORT"):
        data["server"]["port"] = int(os.environ["NAVEVAL_PORT"])
    if os.environ.get("NAVEVAL_WORK_DIR"):
        data["storage"]["work_dir"] = os.environ["NAVEVAL_WORK_DIR"]
    if os.environ.get("NAVEVAL_IMPORT_ROOT"):
        data["import"]["backup_root"] = os.environ["NAVEVAL_IMPORT_ROOT"]

    storage = data["storage"]
    storage_cfg = StorageConfig(
        work_dir=_resolve(storage["work_dir"]),
        db_path=_resolve(storage["db_path"]),
        artifact_keep_days=int(storage.get("artifact_keep_days", 90)),
    )

    settings = Settings(
        root=ROOT_DIR,
        server=ServerConfig(**data["server"]),
        storage=storage_cfg,
        scheduler=SchedulerConfig(
            max_parallel_tasks=int(data["scheduler"]["max_parallel_tasks"]),
            episode_timeout_s=int(data["scheduler"]["episode_timeout_s"]),
            poll_interval_ms=int(data["scheduler"]["poll_interval_ms"]),
            gpu_ids=[str(item) for item in data["scheduler"].get("gpu_ids", [])],
        ),
        security=SecurityConfig(**data["security"]),
        logging=LoggingConfig(**data["logging"]),
        demo=DemoConfig(
            enabled=bool(data["demo"]["enabled"]),
            sample_results_dir=_resolve(data["demo"]["sample_results_dir"]),
        ),
        imports=_load_import_config(data),
        sim=_load_sim_config(data),
        policy=_load_policy_config(data),
        metrics=_load_yaml(CONFIG_DIR / "metrics.yaml"),
        models=_load_yaml(CONFIG_DIR / "models.yaml"),
        raw=data,
    )
    settings.ensure_dirs()
    return settings


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def set_settings(settings: Settings) -> None:
    """测试与启动脚本可通过该入口注入配置。"""
    global _settings
    _settings = settings
