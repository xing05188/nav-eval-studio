"""模型档案服务：登记、维护与可用性探测。"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.response import CONFLICT, NOT_FOUND, AppError
from ..models import EvalTask, ModelProfile
from ..schemas.model import ModelCreate, ModelUpdate

ALLOWED_INPUTS = ("rgb", "depth", "pose", "action", "imu", "odometry")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def to_dict(profile: ModelProfile) -> dict:
    try:
        default_config = json.loads(profile.default_config_json or "{}")
    except json.JSONDecodeError:
        default_config = {}
    return {
        "id": profile.id,
        "name": profile.name,
        "family": profile.family,
        "code_path": profile.code_path,
        "weights_path": profile.weights_path,
        "entry": profile.entry,
        "default_config": default_config,
        "needs_gpu": bool(profile.needs_gpu),
        "allowed_inputs": [item for item in (profile.allowed_inputs or "").split(",") if item],
        "status": profile.status,
        "description": profile.description,
        "updated_at": profile.updated_at,
    }


def list_models(db: Session) -> list[dict]:
    rows = db.scalars(select(ModelProfile).order_by(ModelProfile.id)).all()
    return [to_dict(row) for row in rows]


def get_model(db: Session, model_id: int) -> ModelProfile:
    profile = db.get(ModelProfile, model_id)
    if profile is None:
        raise AppError(NOT_FOUND, "模型档案不存在")
    return profile


def create_model(db: Session, payload: ModelCreate) -> ModelProfile:
    if db.scalar(select(ModelProfile).where(ModelProfile.name == payload.name)):
        raise AppError(CONFLICT, "模型名称已存在")

    invalid = [item for item in payload.allowed_inputs if item not in ALLOWED_INPUTS]
    if invalid:
        raise AppError(1001, f"不支持的输入类型：{', '.join(invalid)}")

    profile = ModelProfile(
        name=payload.name,
        family=payload.family,
        code_path=payload.code_path,
        weights_path=payload.weights_path,
        entry=payload.entry,
        default_config_json=json.dumps(payload.default_config, ensure_ascii=False),
        needs_gpu=1 if payload.needs_gpu else 0,
        allowed_inputs=",".join(payload.allowed_inputs),
        status="unknown",
        description=payload.description,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(profile)
    db.flush()
    return profile


def update_model(db: Session, profile: ModelProfile, payload: ModelUpdate) -> ModelProfile:
    if payload.name and payload.name != profile.name:
        exists = db.scalar(select(ModelProfile).where(ModelProfile.name == payload.name))
        if exists:
            raise AppError(CONFLICT, "模型名称已存在")
        profile.name = payload.name
    if payload.code_path is not None:
        profile.code_path = payload.code_path
    if payload.weights_path is not None:
        profile.weights_path = payload.weights_path
    if payload.entry is not None:
        profile.entry = payload.entry
    if payload.default_config is not None:
        profile.default_config_json = json.dumps(payload.default_config, ensure_ascii=False)
    if payload.needs_gpu is not None:
        profile.needs_gpu = 1 if payload.needs_gpu else 0
    if payload.allowed_inputs is not None:
        invalid = [item for item in payload.allowed_inputs if item not in ALLOWED_INPUTS]
        if invalid:
            raise AppError(1001, f"不支持的输入类型：{', '.join(invalid)}")
        profile.allowed_inputs = ",".join(payload.allowed_inputs)
    if payload.description is not None:
        profile.description = payload.description
    profile.status = "unknown"
    profile.updated_at = _now()
    return profile


def delete_model(db: Session, profile: ModelProfile) -> None:
    used = db.scalar(
        select(func.count()).select_from(EvalTask).where(EvalTask.model_profile_id == profile.id)
    )
    if used:
        raise AppError(CONFLICT, "该模型已被评测任务引用，无法删除")
    db.delete(profile)


def _check(name: str, ok: bool, detail: str = "") -> dict:
    return {"name": name, "ok": ok, "detail": detail}


def probe_model(db: Session, profile: ModelProfile) -> dict:
    """检查路径、权重、启动器与 GPU，并回写状态。"""
    checks = [
        _check("输入类型声明", bool((profile.allowed_inputs or "").strip()), profile.allowed_inputs),
    ]

    if profile.family == "mock":
        checks.extend(
            [
                _check("离线演示适配器", True, "无需代码与权重，使用合成结果"),
                _check("GPU", True, "非必需"),
            ]
        )
        profile.status = "available"
        profile.updated_at = _now()
        return {
            "model_id": profile.id,
            "status": "available",
            "checks": checks,
            "suggestion": "可直接创建评测任务，用于无 GPU 环境的流程演示。",
        }

    code_path = Path(profile.code_path).expanduser() if profile.code_path else None
    code_ok = bool(code_path and code_path.exists())
    checks.append(
        _check("代码目录", code_ok, str(code_path) if code_path else "未配置")
    )

    script = code_path / "streamvln" / "streamvln_eval.py" if code_ok else None
    script_ok = bool(script and script.exists())
    checks.append(
        _check("评测脚本", script_ok, str(script) if script else "未找到 streamvln/streamvln_eval.py")
    )

    weights = Path(profile.weights_path).expanduser() if profile.weights_path else None
    weights_ok = bool(weights and weights.exists())
    checks.append(
        _check("权重目录", weights_ok, str(weights) if weights else "未配置")
    )

    launcher = profile.entry.strip() or "torchrun"
    launcher_path = shutil.which(launcher) if not Path(launcher).is_absolute() else launcher
    launcher_ok = bool(launcher_path and Path(launcher_path).exists())
    checks.append(
        _check("启动器", launcher_ok, launcher_path or f"未找到 {launcher}")
    )

    gpu_ok = shutil.which("nvidia-smi") is not None
    checks.append(
        _check("GPU", gpu_ok, "已检测到 nvidia-smi" if gpu_ok else "未检测到 nvidia-smi")
    )

    all_ok = all(item["ok"] for item in checks)
    profile.status = "available" if all_ok else "missing"
    profile.updated_at = _now()

    failed = [item["name"] for item in checks if not item["ok"]]
    suggestion = (
        "配置完整，可以创建评测任务。"
        if all_ok
        else f"请补齐：{'、'.join(failed)}。若暂无 GPU，可先使用 Mock-Demo 模型走通流程。"
    )
    return {
        "model_id": profile.id,
        "status": profile.status,
        "checks": checks,
        "suggestion": suggestion,
    }
