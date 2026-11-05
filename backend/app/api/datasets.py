"""数据集、Episode 与观测数据接口。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..core.paths import safe_join
from ..core.response import AppError, NOT_FOUND, ok, page
from ..db.session import get_db
from ..models import AppUser
from ..schemas.dataset import (
    CausalExportRequest,
    DatasetCreate,
    DatasetUpdate,
    SplitCreate,
)
from ..services import dataset_service, quality_service, split_service
from .deps import (
    client_ip,
    get_current_user,
    get_user_allow_query_token,
    require_roles,
    write_audit,
)

router = APIRouter(prefix="/datasets", tags=["datasets"])

WRITE_ROLES = require_roles("admin", "operator")


@router.get("")
def list_datasets(
    kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(dataset_service.list_datasets(db, kind=kind, status=status, q=q))


@router.post("")
def create_dataset(
    payload: DatasetCreate,
    request: Request,
    user: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    dataset = dataset_service.create_dataset(db, payload, username=user.username)
    write_audit(
        db,
        user,
        "dataset.create",
        "dataset",
        dataset.id,
        {"name": dataset.name, "kind": dataset.kind, "root_path": dataset.root_path},
        client_ip(request),
    )
    db.commit()
    return ok(dataset_service.to_dict(dataset))


@router.get("/{dataset_id}")
def get_dataset(
    dataset_id: int,
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dataset = dataset_service.get_dataset(db, dataset_id)
    data = dataset_service.to_dict(dataset)
    data["stats"] = dataset_service.dataset_stats(db, dataset)
    data["scenes"] = dataset_service.scene_options(db, dataset)
    data["splits"] = split_service.list_splits(db, dataset)
    data["exports"] = split_service.recent_exports(dataset)
    return ok(data)


@router.patch("/{dataset_id}")
def update_dataset(
    dataset_id: int,
    payload: DatasetUpdate,
    request: Request,
    user: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    dataset = dataset_service.get_dataset(db, dataset_id)
    dataset_service.update_dataset(db, dataset, payload)
    write_audit(
        db, user, "dataset.update", "dataset", dataset.id,
        payload.model_dump(exclude_unset=True), client_ip(request),
    )
    db.commit()
    return ok(dataset_service.to_dict(dataset))


@router.delete("/{dataset_id}")
def delete_dataset(
    dataset_id: int,
    request: Request,
    user: AppUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    dataset = dataset_service.get_dataset(db, dataset_id)
    dataset_service.delete_dataset(db, dataset)
    write_audit(db, user, "dataset.delete", "dataset", dataset_id, {}, client_ip(request))
    db.commit()
    return ok({"deleted": True})


@router.post("/{dataset_id}/scan")
def scan_dataset(
    dataset_id: int,
    request: Request,
    user: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    dataset = dataset_service.get_dataset(db, dataset_id)
    summary = dataset_service.scan_dataset(db, dataset)
    write_audit(db, user, "dataset.scan", "dataset", dataset_id, summary, client_ip(request))
    db.commit()
    return ok(summary)


@router.get("/{dataset_id}/episodes")
def list_episodes(
    dataset_id: int,
    q: str | None = Query(default=None),
    scene: str | None = Query(default=None),
    min_len: float | None = Query(default=None),
    max_len: float | None = Query(default=None),
    page_no: int = Query(default=1, ge=1, alias="page"),
    page_size: int = Query(default=20, ge=1, le=200),
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dataset = dataset_service.get_dataset(db, dataset_id)
    items, total = dataset_service.list_episodes(
        db,
        dataset,
        q=q,
        scene=scene,
        min_len=min_len,
        max_len=max_len,
        page=page_no,
        page_size=page_size,
    )
    return ok(page(items, total, page_no, page_size))


@router.get("/{dataset_id}/episodes/{row_id}")
def get_episode(
    dataset_id: int,
    row_id: int,
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dataset = dataset_service.get_dataset(db, dataset_id)
    episode = dataset_service.get_episode(db, dataset, row_id)
    return ok(dataset_service.episode_detail(db, dataset, episode))


@router.get("/{dataset_id}/episodes/{row_id}/observations")
def get_observations(
    dataset_id: int,
    row_id: int,
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dataset = dataset_service.get_dataset(db, dataset_id)
    episode = dataset_service.get_episode(db, dataset, row_id)
    return ok(dataset_service.build_observations(dataset, episode))


@router.get("/{dataset_id}/episodes/{row_id}/frame/{index}")
def get_frame(
    dataset_id: int,
    row_id: int,
    index: int,
    kind: str = Query(default="rgb", pattern="^(rgb|depth)$"),
    _: AppUser = Depends(get_user_allow_query_token),
    db: Session = Depends(get_db),
):
    dataset = dataset_service.get_dataset(db, dataset_id)
    episode = dataset_service.get_episode(db, dataset, row_id)
    path = dataset_service.frame_path(dataset, episode, index, kind)
    media = "image/jpeg" if kind == "rgb" else "image/png"
    return FileResponse(path, media_type=media)


@router.post("/{dataset_id}/validate")
def validate_dataset(
    dataset_id: int,
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dataset = dataset_service.get_dataset(db, dataset_id)
    return ok(quality_service.validate_dataset(db, dataset))


@router.get("/{dataset_id}/splits")
def list_splits(
    dataset_id: int,
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    dataset = dataset_service.get_dataset(db, dataset_id)
    return ok(split_service.list_splits(db, dataset))


@router.post("/{dataset_id}/splits")
def create_split(
    dataset_id: int,
    payload: SplitCreate,
    request: Request,
    user: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    dataset = dataset_service.get_dataset(db, dataset_id)
    split = split_service.create_split(db, dataset, payload)
    write_audit(
        db, user, "split.create", "split", split.id,
        {"name": split.name, "kind": split.kind, "episodes": split.episode_count},
        client_ip(request),
    )
    db.commit()
    return ok(split_service.to_dict(split))


@router.post("/{dataset_id}/export-causal")
def export_causal(
    dataset_id: int,
    payload: CausalExportRequest,
    request: Request,
    user: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    dataset = dataset_service.get_dataset(db, dataset_id)
    result = split_service.export_causal(db, dataset, payload)
    write_audit(db, user, "dataset.export_causal", "dataset", dataset_id, result, client_ip(request))
    db.commit()
    return ok(result)


@router.get("/{dataset_id}/exports/{filename}")
def download_export(
    dataset_id: int,
    filename: str,
    _: AppUser = Depends(get_current_user),
):
    directory = split_service.export_root() / f"dataset-{dataset_id:04d}"
    target = safe_join(directory, filename)
    if not target.exists() or not target.is_file():
        raise AppError(NOT_FOUND, "导出文件不存在")
    return FileResponse(target, media_type="application/x-ndjson", filename=Path(target).name)
