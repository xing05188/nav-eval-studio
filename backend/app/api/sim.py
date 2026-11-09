"""交互式仿真接口：建会话、读快照、下动作、MJPEG 推流、停止。

鉴权沿用平台的两种范式：
- JSON 读写：`require_roles("admin","operator")`（启动 / 操控 / 停止）
- `<img src>` 拿不到自定义请求头：`/state` 与 `/stream` 用 `get_user_allow_query_token`（`?token=`）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.response import PARAM_INVALID, AppError, ok
from ..db.session import get_db
from ..models import AppUser
from ..services.sim import sim_session
from ..services.sim.constants import ACTION_CODES, ACTION_RESET
from .deps import get_current_user, get_user_allow_query_token, require_roles

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


class OracleToggle(BaseModel):
    enabled: bool = Field(..., description="true=让 oracle 沿最短路径自动走，false=停下")


class PipToggle(BaseModel):
    enabled: bool = Field(..., description="true=在第一视角右上角叠第三视角画中画")


class RobotToggle(BaseModel):
    enabled: bool = Field(..., description="true=在第三视角里显示机器狗模型")


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


@router.post("/oracle")
def set_oracle(payload: OracleToggle, _: AppUser = Depends(WRITE_ROLES)):
    """Oracle 驾驶：沿 navmesh 最短路径自动走，用于和模型/人类轨迹对照。"""
    return ok(sim_session.set_oracle(payload.enabled))


@router.post("/pip")
def set_pip(payload: PipToggle, _: AppUser = Depends(WRITE_ROLES)):
    """第三视角画中画开关（第二路相机在会话启动时按 sim.pip 建好）。"""
    return ok(sim_session.set_pip(payload.enabled))


@router.post("/robot")
def set_robot(payload: RobotToggle, _: AppUser = Depends(WRITE_ROLES)):
    """机器狗模型显隐（模型在会话启动时按 sim.robot_mesh 加载）。"""
    return ok(sim_session.set_robot(payload.enabled))


@router.post("/recordings/export")
def start_export(_: AppUser = Depends(WRITE_ROLES)):
    """把已落盘的帧异步编码成 mp4；进度见 /sim/state 的 `recording.export`。"""
    return ok(sim_session.export_video())


@router.get("/recordings/export")
def export_state(_: AppUser = Depends(get_current_user)):
    return ok(sim_session.recording_state())


@router.get("/recordings/export/file")
def download_export(_: AppUser = Depends(get_user_allow_query_token)):
    """`<a href>` / 前端 blob 都能用：走 `?token=` 这条鉴权通道。"""
    target, filename = sim_session.open_export()
    return FileResponse(target, media_type="video/mp4", filename=filename)


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
