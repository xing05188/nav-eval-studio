"""数据集、Episode 与切分映射。"""

from __future__ import annotations

from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text

from ..db.base import Base


class Dataset(Base):
    __tablename__ = "dataset"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    version = Column(String, nullable=False, default="")
    kind = Column(String, nullable=False, default="r2r_ce")
    root_path = Column(String, nullable=False)
    instruction_lang = Column(String, nullable=False, default="en")
    scene_count = Column(Integer, nullable=False, default=0)
    episode_count = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="unknown")
    last_scan_at = Column(String)
    meta_json = Column(Text, nullable=False, default="{}")
    created_at = Column(String)
    updated_at = Column(String)


class Episode(Base):
    __tablename__ = "episode"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(Integer, ForeignKey("dataset.id", ondelete="CASCADE"), nullable=False)
    episode_id = Column(String, nullable=False)
    scene_id = Column(String, nullable=False, default="")
    instruction = Column(Text, nullable=False, default="")
    instruction_len = Column(Integer, nullable=False, default=0)
    traj_len = Column(Float, nullable=False, default=0)
    duration_s = Column(Float, nullable=False, default=0)
    start_pose_json = Column(Text, nullable=False, default="[]")
    goal_pose_json = Column(Text, nullable=False, default="[]")
    has_depth = Column(Integer, nullable=False, default=0)
    meta_json = Column(Text, nullable=False, default="{}")


class Split(Base):
    __tablename__ = "split"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(Integer, ForeignKey("dataset.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    kind = Column(String, nullable=False, default="subset")
    base_split = Column(String, nullable=False, default="val_unseen")
    seed = Column(Integer, nullable=False, default=42)
    episode_count = Column(Integer, nullable=False, default=0)
    filter_json = Column(Text, nullable=False, default="{}")
    created_at = Column(String)


class SplitEpisode(Base):
    __tablename__ = "split_episode"

    split_id = Column(
        Integer, ForeignKey("split.id", ondelete="CASCADE"), primary_key=True, nullable=False
    )
    episode_id = Column(
        Integer, ForeignKey("episode.id", ondelete="CASCADE"), primary_key=True, nullable=False
    )
    ordinal = Column(Integer, nullable=False, default=0)
