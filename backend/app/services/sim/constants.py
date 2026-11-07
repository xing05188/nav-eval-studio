"""交互式仿真的常量：动作码、运动学参数、渲染参数。

数值全部与旧脚本 `scripts/dog_sim/interactive_vln.py` 对齐，
其中 `FORWARD_STEP=0.25 / TURN_DEG=15 / SUCCESS_DIST=3.0 / MAX_EPISODE_STEPS=500`
是自检回归基线的一部分，**不要随手改**。
"""

from __future__ import annotations

# ---- 动作码（与旧脚本 ACT_* 一致）----
ACT_STOP = 0
ACT_FORWARD = 1
ACT_LEFT = 2
ACT_RIGHT = 3

ACT_NAMES = {
    ACT_STOP: "stop",
    ACT_FORWARD: "move_forward",
    ACT_LEFT: "turn_left",
    ACT_RIGHT: "turn_right",
}

ACT_LABELS = {
    ACT_STOP: "停止",
    ACT_FORWARD: "前进",
    ACT_LEFT: "左转",
    ACT_RIGHT: "右转",
}

# 前端传来的字符串 → 动作码；"reset" 走单独的复位命令
ACTION_CODES = {
    "stop": ACT_STOP,
    "forward": ACT_FORWARD,
    "left": ACT_LEFT,
    "right": ACT_RIGHT,
}
ACTION_RESET = "reset"

# 模型给的 Habitat 动作码 → 前端/引擎用的字符串（与 ACTION_CODES 互逆）
CODE_ACTIONS = {code: name for name, code in ACTION_CODES.items()}

# 模型动作队列上限：一次 forward 出 4 个，留 2 轮余量；超出直接丢最旧的，
# 防止模型跑飞后在队列里堆几十步、人按下接管键之后还要"再走一会儿"才停
PENDING_MAX = 8
# 队列连续为空的秒数超过该值 → 推理线程歇一下（省 GPU，也不至于把画面读空转）
PENDING_IDLE_S = 0.5

# ---- 单局规则 ----
SUCCESS_DIST = 3.0        # 默认成功半径（episode.meta_json.goal_radius 优先）
MAX_EPISODE_STEPS = 500
FORWARD_STEP = 0.25       # 每次 move_forward 的位移（米）
TURN_DEG = 15.0           # 每次转向的角度（度）

# ---- 传感器 ----
HEAD_W, HEAD_H, HFOV = 640, 480, 79
HEAD_SENSOR_POS = [0.0, 1.25, 0.0]
AGENT_HEIGHT = 1.5
AGENT_RADIUS = 0.1

# ---- 俯视图 ----
MAP_W, MAP_H = 480, 480
MAP_MARGIN = 18
MAP_BG = (28, 28, 32)
MAP_FLOOR = (70, 78, 86)

# ---- 渲染 / 推流 ----
RENDER_HZ = 15.0          # 无人观看时的渲染上限
STREAM_HZ = 20.0          # 有观众时的渲染上限
JPEG_QUALITY = 82
MAX_TRAIL_POINTS = 4000   # 轨迹点上限，超出后按步长抽稀，避免快照无限增长

# ---- 会话 ----
IDLE_TIMEOUT_S = 900
MAX_CLIENTS = 4
FREE_MEM_WARN_MB = 4096
# 观看连接的心跳超时：浏览器直接关标签页时生成器不保证跑 finally，超时即回收
CLIENT_STALE_S = 60.0
