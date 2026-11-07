"""场景与传感器的构建。

**本模块只能在引擎线程里被 import/调用**：`habitat_sim` 是原生扩展，顶层 import 会让
没有装 habitat 的机器连平台都起不来，所以函数内部懒加载。
"""

from __future__ import annotations

import logging
import time

from . import constants as C

logger = logging.getLogger(__name__)


def build_sim(scene_path: str, gpu_id: int = 0):
    """建 Simulator：只挂 head_rgb + head_depth 一路相机（与评测链路对齐）。"""
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

    depth = habitat_sim.CameraSensorSpec()
    depth.uuid = "head_depth"
    depth.sensor_type = habitat_sim.SensorType.DEPTH
    depth.resolution = [C.HEAD_H, C.HEAD_W]
    depth.position = C.HEAD_SENSOR_POS
    depth.hfov = C.HFOV

    agent_cfg.sensor_specifications = [head, depth]

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


def yaw_of(quaternion) -> float:
    """agent 只绕 Y 轴转，直接取 yaw（弧度）。"""
    import math

    return float(2.0 * math.atan2(quaternion.y, quaternion.w))


__all__ = ["build_sim", "yaw_of"]
