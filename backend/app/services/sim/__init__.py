"""交互式仿真服务。

对外只暴露 `sim_session` 单例与 `SimSpec`；`engine/scene/topdown` 属于实现细节，
其中 `scene.py` 会 import habitat_sim，**不要在模块顶层 import 本包的子模块**。
"""

from .episode import SimSpec
from .session import SimSession, sim_session

__all__ = ["SimSession", "SimSpec", "sim_session"]
