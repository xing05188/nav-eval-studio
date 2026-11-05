"""轨迹回放接口：回放元数据、帧图与可通行区域掩膜。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from ..core.response import ok
from ..db.session import get_db
from ..models import AppUser
from ..services import replay_service
from .deps import get_current_user, get_user_allow_query_token

router = APIRouter(prefix="/replay", tags=["replay"])


@router.get("/{task_id}/{row_id}")
def episode_replay(
    task_id: int,
    row_id: int,
    _: AppUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(replay_service.episode_replay(db, task_id, row_id))


@router.get("/{task_id}/{row_id}/frame/{frame_index}")
def frame_image(
    task_id: int,
    row_id: int,
    frame_index: int,
    _: AppUser = Depends(get_user_allow_query_token),
    db: Session = Depends(get_db),
):
    content, media_type = replay_service.frame_asset(db, task_id, row_id, frame_index)
    if isinstance(content, Path):
        return FileResponse(content, media_type=media_type)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/{task_id}/{row_id}/mask")
def traversable_mask(
    task_id: int,
    row_id: int,
    _: AppUser = Depends(get_user_allow_query_token),
    db: Session = Depends(get_db),
):
    return FileResponse(replay_service.mask_asset(db, task_id, row_id), media_type="image/png")
