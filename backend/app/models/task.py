"""配置模板、模型档案、评测任务、结果明细与产物映射。"""

from __future__ import annotations

from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text

from ..db.base import Base


class ConfigTemplate(Base):
    __tablename__ = "config_template"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    modality = Column(String, nullable=False, default="vision")
    memory_policy = Column(String, nullable=False, default="fixed_window")
    params_json = Column(Text, nullable=False, default="{}")
    description = Column(Text, nullable=False, default="")
    builtin = Column(Integer, nullable=False, default=0)
    created_at = Column(String)


class ModelProfile(Base):
    __tablename__ = "model_profile"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False, unique=True)
    family = Column(String, nullable=False, default="custom")
    code_path = Column(String, nullable=False, default="")
    weights_path = Column(String, nullable=False, default="")
    entry = Column(String, nullable=False, default="")
    default_config_json = Column(Text, nullable=False, default="{}")
    needs_gpu = Column(Integer, nullable=False, default=1)
    allowed_inputs = Column(String, nullable=False, default="rgb,depth,pose,action")
    status = Column(String, nullable=False, default="unknown")
    description = Column(Text, nullable=False, default="")
    created_at = Column(String)
    updated_at = Column(String)


class EvalTask(Base):
    __tablename__ = "eval_task"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    dataset_id = Column(Integer, ForeignKey("dataset.id", ondelete="RESTRICT"), nullable=False)
    split_id = Column(Integer, ForeignKey("split.id", ondelete="RESTRICT"), nullable=False)
    model_profile_id = Column(
        Integer, ForeignKey("model_profile.id", ondelete="RESTRICT"), nullable=False
    )
    config_json = Column(Text, nullable=False, default="{}")
    status = Column(String, nullable=False, default="queued")
    priority = Column(Integer, nullable=False, default=5)
    progress_done = Column(Integer, nullable=False, default=0)
    progress_total = Column(Integer, nullable=False, default=0)
    metrics_json = Column(Text, nullable=False, default="{}")
    error_msg = Column(Text, nullable=False, default="")
    gpu_ids = Column(String, nullable=False, default="")
    pid = Column(Integer)
    created_by = Column(Integer, ForeignKey("app_user.id", ondelete="SET NULL"))
    queued_at = Column(String)
    started_at = Column(String)
    finished_at = Column(String)
    duration_s = Column(Float)
    note = Column(Text, nullable=False, default="")


class TaskEpisode(Base):
    __tablename__ = "task_episode"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("eval_task.id", ondelete="CASCADE"), nullable=False)
    episode_id = Column(Integer, ForeignKey("episode.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False, default="pending")
    success = Column(Integer, nullable=False, default=0)
    spl = Column(Float, nullable=False, default=0)
    ne = Column(Float, nullable=False, default=0)
    os = Column(Float, nullable=False, default=0)
    ndtw = Column(Float, nullable=False, default=0)
    tl = Column(Float, nullable=False, default=0)
    steps = Column(Integer, nullable=False, default=0)
    latency_avg_ms = Column(Float, nullable=False, default=0)
    latency_p95_ms = Column(Float, nullable=False, default=0)
    gpu_mem_peak_mb = Column(Integer, nullable=False, default=0)
    tokens_peak = Column(Integer, nullable=False, default=0)
    ctx_len_peak = Column(Integer, nullable=False, default=0)
    failure_reason = Column(String, nullable=False, default="")
    manual_reason = Column(String, nullable=False, default="")
    traj_path = Column(String, nullable=False, default="")
    log_path = Column(String, nullable=False, default="")
    updated_at = Column(String)


class ResourceSample(Base):
    __tablename__ = "resource_sample"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("eval_task.id", ondelete="CASCADE"), nullable=False)
    ts = Column(String)
    step = Column(Integer, nullable=False, default=0)
    gpu_mem_mb = Column(Integer, nullable=False, default=0)
    latency_ms = Column(Float, nullable=False, default=0)
    tokens = Column(Integer, nullable=False, default=0)
    ctx_len = Column(Integer, nullable=False, default=0)


class Artifact(Base):
    __tablename__ = "artifact"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("eval_task.id", ondelete="CASCADE"), nullable=False)
    episode_id = Column(Integer, ForeignKey("task_episode.id", ondelete="CASCADE"))
    kind = Column(String, nullable=False, default="trajectory")
    name = Column(String, nullable=False, default="")
    path = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False, default=0)
    sha256 = Column(String, nullable=False, default="")
    created_at = Column(String)
