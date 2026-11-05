"""模型档案接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..core.response import ok
from ..db.session import get_db
from ..models import AppUser
from ..schemas.model import ModelCreate, ModelUpdate
from ..services import model_service
from .deps import client_ip, get_current_user, require_roles, write_audit

router = APIRouter(prefix="/models", tags=["models"])

WRITE_ROLES = require_roles("admin", "operator")


@router.get("")
def list_models(
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(model_service.list_models(db))


@router.post("")
def create_model(
    payload: ModelCreate,
    request: Request,
    user: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    profile = model_service.create_model(db, payload)
    write_audit(
        db, user, "model.create", "model", profile.id,
        {"name": profile.name, "family": profile.family}, client_ip(request),
    )
    db.commit()
    return ok(model_service.to_dict(profile))


@router.patch("/{model_id}")
def update_model(
    model_id: int,
    payload: ModelUpdate,
    request: Request,
    user: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    profile = model_service.get_model(db, model_id)
    model_service.update_model(db, profile, payload)
    write_audit(
        db, user, "model.update", "model", profile.id,
        payload.model_dump(exclude_unset=True), client_ip(request),
    )
    db.commit()
    return ok(model_service.to_dict(profile))


@router.delete("/{model_id}")
def delete_model(
    model_id: int,
    request: Request,
    user: AppUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    profile = model_service.get_model(db, model_id)
    model_service.delete_model(db, profile)
    write_audit(db, user, "model.delete", "model", model_id, {}, client_ip(request))
    db.commit()
    return ok({"deleted": True})


@router.post("/{model_id}/probe")
def probe_model(
    model_id: int,
    user: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    profile = model_service.get_model(db, model_id)
    result = model_service.probe_model(db, profile)
    write_audit(db, user, "model.probe", "model", model_id, {"status": result["status"]})
    db.commit()
    return ok(result)
