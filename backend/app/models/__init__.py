"""ORM 映射汇总。

导入本模块即完成所有表的注册，Base.metadata 可直接用于建表或校验。
"""

from .backup import BackupAsset
from .dataset import Dataset, Episode, Split, SplitEpisode
from .system import SchemaVersion, Setting
from .task import Artifact, ConfigTemplate, EvalTask, ModelProfile, ResourceSample, TaskEpisode
from .user import AppUser, AuditLog

__all__ = [
    "BackupAsset",
    "AppUser",
    "AuditLog",
    "Dataset",
    "Episode",
    "Split",
    "SplitEpisode",
    "ConfigTemplate",
    "ModelProfile",
    "EvalTask",
    "TaskEpisode",
    "ResourceSample",
    "Artifact",
    "Setting",
    "SchemaVersion",
]
