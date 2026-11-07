"""交互式仿真接口：建会话、读快照、下动作、MJPEG 推流、停止。

鉴权沿用平台的两种范式：
- JSON 读写：`require_roles("admin","operator")`（启动 / 操控 / 停止）
- `<img src>` 拿不到自定义请求头：`/state` 与 `/stream` 用 `get_user_allow_query_token`（`?token=`）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.response import PARAM_INVALID, AppError, ok
from ..db.session import get_db
from ..models import AppUser
from ..services.sim import sim_session
from ..services.sim.constants import ACTION_CODES, ACTION_RESET
from .deps import get_user_allow_query_token, require_roles

router = APIRouter(prefix="/sim", tags=["sim"])

WRITE_ROLES = require_roles("admin", "operator")

VALID_ACTIONS = sorted({*ACTION_CODES, ACTION_RESET})


class SessionCreate(BaseModel):
    episode_id: int = Field(..., ge=1, description="episode 主键")
    gpu_id: int | None = Field(default=None, ge=0, description="指定 GPU，缺省取 sim.gpu_ids[0]")


class ActionCreate(BaseModel):
    action: str = Field(..., description="forward | left | right | stop | reset")


class PolicyStart(BaseModel):
    model_id: int | None = Field(default=None, ge=1, description="模型档案 id，缺省取第一个 streamvln 档案")
    gpu_id: int | None = Field(default=None, ge=0, description="模型推理用的 GPU，缺省取 policy.gpu_id")


class PolicyPause(BaseModel):
    paused: bool = Field(..., description="true=暂停模型驾驶，false=恢复")


@router.post("/sessions")
def create_session(
    payload: SessionCreate,
    _: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    return ok(sim_session.start(db, payload.episode_id, payload.gpu_id))


@router.get("/state")
def read_state(_: AppUser = Depends(get_user_allow_query_token)):
    return ok(sim_session.state())


@router.post("/actions")
def apply_action(payload: ActionCreate, _: AppUser = Depends(WRITE_ROLES)):
    action = (payload.action or "").strip().lower()
    if action not in VALID_ACTIONS:
        raise AppError(
            PARAM_INVALID,
            f"不支持的动作：{payload.action}（可选 {'/'.join(VALID_ACTIONS)}）",
            http_status=400,
        )
    return ok(sim_session.act(action))


@router.get("/stream")
async def stream(request: Request, _: AppUser = Depends(get_user_allow_query_token)):
    viewer = sim_session.open_stream()
    if viewer is None:
        raise AppError(PARAM_INVALID, "当前没有运行中的仿真会话", http_status=409)
    engine, ticket = viewer
    return StreamingResponse(
        sim_session.iter_mjpeg(request, engine, ticket),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/policy")
def start_policy(
    payload: PolicyStart,
    _: AppUser = Depends(WRITE_ROLES),
    db: Session = Depends(get_db),
):
    """启用模型驾驶：立即返回 `status=loading`，权重在后台线程加载（约 13 s）。"""
    return ok(sim_session.start_policy(db, payload.model_id, payload.gpu_id))


@router.delete("/policy")
def stop_policy(_: AppUser = Depends(WRITE_ROLES)):
    """停用模型驾驶并释放显存。"""
    return ok(sim_session.stop_policy())


@router.post("/policy/pause")
def pause_policy(payload: PolicyPause, _: AppUser = Depends(WRITE_ROLES)):
    return ok(sim_session.set_policy_paused(payload.paused))


@router.delete("/sessions/{session_id}")
def stop_session(
    session_id: str,
    _: AppUser = Depends(WRITE_ROLES),
):
    return ok(sim_session.stop(session_id))
