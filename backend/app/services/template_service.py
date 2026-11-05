"""配置模板服务。"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.response import CONFLICT, NOT_FOUND, AppError
from ..models import ConfigTemplate
from ..schemas.model import TemplateCreate, TemplateUpdate

MODALITY_INPUTS = {
    "vision": ["rgb"],
    "vision_geo": ["rgb", "depth"],
    "vision_geo_state": ["rgb", "depth", "pose"],
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def to_dict(template: ConfigTemplate) -> dict:
    try:
        params = json.loads(template.params_json or "{}")
    except json.JSONDecodeError:
        params = {}
    return {
        "id": template.id,
        "name": template.name,
        "modality": template.modality,
        "memory_policy": template.memory_policy,
        "params": params,
        "description": template.description,
        "builtin": bool(template.builtin),
    }


def list_templates(db: Session) -> list[dict]:
    rows = db.scalars(
        select(ConfigTemplate).order_by(ConfigTemplate.builtin.desc(), ConfigTemplate.id)
    ).all()
    return [to_dict(row) for row in rows]


def get_template(db: Session, template_id: int) -> ConfigTemplate:
    template = db.get(ConfigTemplate, template_id)
    if template is None:
        raise AppError(NOT_FOUND, "配置模板不存在")
    return template


def create_template(db: Session, payload: TemplateCreate) -> ConfigTemplate:
    if db.scalar(select(ConfigTemplate).where(ConfigTemplate.name == payload.name)):
        raise AppError(CONFLICT, "模板名称已存在")
    template = ConfigTemplate(
        name=payload.name,
        modality=payload.modality,
        memory_policy=payload.memory_policy,
        params_json=json.dumps(payload.params, ensure_ascii=False),
        description=payload.description,
        builtin=0,
        created_at=_now(),
    )
    db.add(template)
    db.flush()
    return template


def update_template(db: Session, template: ConfigTemplate, payload: TemplateUpdate) -> ConfigTemplate:
    if payload.name and payload.name != template.name:
        if db.scalar(select(ConfigTemplate).where(ConfigTemplate.name == payload.name)):
            raise AppError(CONFLICT, "模板名称已存在")
        template.name = payload.name
    if payload.params is not None:
        template.params_json = json.dumps(payload.params, ensure_ascii=False)
    if payload.description is not None:
        template.description = payload.description
    return template


def delete_template(db: Session, template: ConfigTemplate) -> None:
    if template.builtin:
        raise AppError(CONFLICT, "内置模板不可删除，可复制后修改")
    db.delete(template)
