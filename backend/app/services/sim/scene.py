"""场景与传感器的构建。

**本模块只能在引擎线程里被 import/调用**：`habitat_sim` 是原生扩展，顶层 import 会让
没有装 habitat 的机器连平台都起不来，所以函数内部懒加载。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from . import constants as C

logger = logging.getLogger(__name__)

_ASSET_DIR = Path(__file__).parent


def resolve_robot_config(robot_mesh: str) -> Path | None:
    """`sim.robot_mesh` → 物体配置文件路径（habitat 的 `*.object_config.json`）。

    - `""` / `none` / `off` → 不显示
    - `go2` → 内置模型（`assets/go2/go2.object_config.json`）
    - 其它：`.object_config.json` 直接用；`.glb` 找同目录同名配置，没有就补一个
    """
    name = (robot_mesh or "").strip()
    if not name or name.lower() in ("none", "off", "false", "0"):
        return None
    if name.lower() == "go2":
        cfg = _ASSET_DIR / C.ROBOT_ASSET_DIR / C.ROBOT_CONFIG_NAME
    else:
        cfg = Path(name).expanduser()
        if cfg.suffix == ".glb":
            if not cfg.exists():
                logger.warning("机器狗模型不存在：%s（本局不显示）", cfg)
                return None
            sibling = cfg.with_suffix(".object_config.json")
            if not sibling.exists():
                sibling.write_text(json.dumps({
                    "render_asset": cfg.name, "mass": 15.0, "scale": [1, 1, 1],
                }), encoding="utf-8")
                logger.warning("没有找到 %s，已按默认参数生成", sibling)
            cfg = sibling
    if not cfg.exists():
        logger.warning("机器狗模型不存在：%s（本局不显示）", cfg)
        return None
    return cfg


def add_robot(sim, config_path: Path, scale: float = 1.0):
    """把机器狗作为静态刚体挂进场景，返回 object（失败返回 None）。

    - `KINEMATIC` + `collidable=False`：只画不参与物理，不会掉地上也不会挡住 agent；
    - 车头朝 -Z（与 habitat 前向一致），所以每帧只要把 agent 的位姿抄过来。
    """
    import habitat_sim
    from _magnum import Vector3

    manager = sim.get_object_template_manager()
    handle = str(config_path)
    if not manager.get_library_has_handle(handle):
        ids = manager.load_configs(str(config_path.parent))
        if not ids:
            logger.warning("机器狗配置加载失败：%s", config_path)
            return None
        handle = manager.get_template_handle_by_id(ids[0])
    obj = sim.get_rigid_object_manager().add_object_by_template_handle(handle)
    obj.motion_type = habitat_sim.physics.MotionType.KINEMATIC
    obj.collidable = False
    if abs(scale - 1.0) > 1e-3:
        obj.scale = Vector3(scale, scale, scale)
    return obj


def build_sim(scene_path: str, gpu_id: int = 0, pip: bool = True):
    """建 Simulator：默认挂 `head_rgb`（第一视角）+ `chase_rgb`（第三视角）。

    以前还挂了一路 `head_depth`，但从来没人读它（模型只吃 RGB），纯粹多花一次渲染：
    实测去掉后渲染帧率从 ~15.6 提到 ~25 fps。需要深度时再按 `SensorType.DEPTH` 加回来即可。

    `pip=True` 时多挂一路 320×240 的俯视相机（`docs/09` #9）：位置在狗身后上方
    （`[0, 1.8, 2.0]`、俯 26°），由 `engine._render` 贴成第一视角右上角的画中画。
    实测在默认 15 fps 上限下开与不开都是 14.4 fps（解除上限后 55 vs 50 fps，差异在噪声内），
    所以默认开着；真不想要就在 `sim.pip: false` 里关掉。

    机器狗网格不在这里建：Simulator 出来之后由 `add_robot` 挂成静态刚体。
    """
    import habitat_sim

    backend = habitat_sim.SimulatorConfiguration()
    backend.scene_id = scene_path
    backend.gpu_device_id = int(gpu_id)

    agent_cfg = habitat_sim.agent.AgentConfiguration()
    agent_cfg.height = C.AGENT_HEIGHT
    agent_cfg.radius = C.AGENT_RADIUS

    head = habitat_sim.CameraSensorSpec()
    head.uuid = "head_rgb"
    head.sensor_type = habitat_sim.SensorType.COLOR
    head.resolution = [C.HEAD_H, C.HEAD_W]
    head.position = C.HEAD_SENSOR_POS
    head.hfov = C.HFOV

    sensors = [head]
    if pip:
        sensors.append(_chase_sensor_spec(habitat_sim))
    agent_cfg.sensor_specifications = sensors

    # action_space 形状与评测 V0 逐位对齐。`stop` 在这里只是形状占位：
    # habitat 没有 stop 运动原语，引擎判停走自己的 _apply 分支，不会调 agent.act("stop")。
    agent_cfg.action_space = {
        "move_forward": habitat_sim.agent.ActionSpec(
            "move_forward", habitat_sim.agent.ActuationSpec(amount=C.FORWARD_STEP)),
        "turn_left": habitat_sim.agent.ActionSpec(
            "turn_left", habitat_sim.agent.ActuationSpec(amount=C.TURN_DEG)),
        "turn_right": habitat_sim.agent.ActionSpec(
            "turn_right", habitat_sim.agent.ActuationSpec(amount=C.TURN_DEG)),
        "stop": habitat_sim.agent.ActionSpec("stop"),
    }

    sim = habitat_sim.Simulator(habitat_sim.Configuration(backend, [agent_cfg]))

    if not sim.pathfinder.is_loaded:
        import habitat_sim.nav as nav

        start = time.time()
        sim.recompute_navmesh(sim.pathfinder, nav.NavMeshSettings())
        logger.info("navmesh 重建完成，用时 %.1fs，场景=%s", time.time() - start, scene_path)
    return sim


def _chase_sensor_spec(habitat_sim):
    """第三视角相机：挂在 agent 身后上方，俯视 34°，画中画用。

    `SensorSpec.orientation` 这个版本是 3 维欧拉角（弧度，agent 局部坐标），
    不是四元数——直接塞 [x,y,z,w] 会 TypeError。实测 [-0.6, 0, 0] 是俯视，
    [0, 0, 0] 会平视天花板。
    """
    import numpy as np

    chase = habitat_sim.CameraSensorSpec()
    chase.uuid = C.PIP_UUID
    chase.sensor_type = habitat_sim.SensorType.COLOR
    chase.resolution = [C.PIP_H, C.PIP_W]
    chase.position = list(C.PIP_POS)
    chase.orientation = np.array(C.PIP_ROT, dtype=np.float32)
    chase.hfov = C.PIP_HFOV
    return chase


def yaw_of(quaternion) -> float:
    """agent 只绕 Y 轴转，直接取 yaw（弧度）。"""
    import math

    return float(2.0 * math.atan2(quaternion.y, quaternion.w))


__all__ = ["build_sim", "yaw_of"]
