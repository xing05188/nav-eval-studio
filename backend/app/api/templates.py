"""配置模板接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..core.response import ok
from ..db.session import get_db
from ..models import AppUser
from ..schemas.model import TemplateCreate, TemplateUpdate
from ..services import template_service
from .deps import client_ip, get_current_user, require_roles, write_audit

router = APIRouter(prefix="/templates", tags=["templates"])

WRITE_ROLES = require_roles("admin", "operator")


@router.get("")
def list_templates(
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(template_service.list_templates(db))


@router.post("")
def create_template(
    payload: TemplateCreate,
    request: Request,
    user: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    template = template_service.create_template(db, payload)
    write_audit(
        db, user, "template.create", "template", template.id,
        {"name": template.name}, client_ip(request),
    )
    db.commit()
    return ok(template_service.to_dict(template))


@router.patch("/{template_id}")
def update_template(
    template_id: int,
    payload: TemplateUpdate,
    request: Request,
    user: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    template = template_service.get_template(db, template_id)
    template_service.update_template(db, template, payload)
    write_audit(
        db, user, "template.update", "template", template.id,
        payload.model_dump(exclude_unset=True), client_ip(request),
    )
    db.commit()
    return ok(template_service.to_dict(template))


@router.delete("/{template_id}")
def delete_template(
    template_id: int,
    request: Request,
    user: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    template = template_service.get_template(db, template_id)
    template_service.delete_template(db, template)
    write_audit(db, user, "template.delete", "template", template_id, {}, client_ip(request))
    db.commit()
    return ok({"deleted": True})
