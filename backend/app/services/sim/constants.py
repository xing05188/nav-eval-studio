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
# 浏览器对同一域名最多 6 条 HTTP/1.1 连接，而 MJPEG 那条长连接不释放；
# 刷新/断流重连几次就会把名额占满（第 5 条起 429 → 页面黑屏且无提示）。
# 所以上限放宽到 8，并在超限时踢掉最老的僵尸，而不是把新连接拒之门外。
MAX_CLIENTS = 8
FREE_MEM_WARN_MB = 4096
# 观看连接的心跳超时：只在**成功推出一帧**时刷新，客户端不再读就会自然过期
CLIENT_STALE_S = 15.0
# 一条流连续这么久没有新帧就主动断开：避免"客户端已放弃但生成器还挂着"把名额占死
STREAM_IDLE_S = 8.0

# ---- 第三视角（画中画，docs/09 #9）----
# 第二路相机挂在 agent 身后上方：`orientation` 是 agent 局部坐标下的欧拉角（弧度），
# 实测 [-0.45, 0, 0] 为俯视 26°（正号 / 0 会抬头，看到的是天花板）。
# 机位从最早的 [0,2.6,2.6]/34° 调近到 [0,1.8,2.0]/26°：机器狗从 15×28 px 变成 20×40 px。
PIP_W, PIP_H, PIP_HFOV = 320, 240, 90
PIP_UUID = "chase_rgb"
PIP_POS = [0.0, 1.8, 2.0]        # 前进方向是 -Z，所以 +Z 在狗身后
PIP_ROT = [-0.4538, 0.0, 0.0]
PIP_MARGIN = 8
PIP_LABEL = "3rd view"

# ---- 机器狗网格 ----
# 静态 GLB：由 go2_description 的 URDF 离线转换（Y-up、脚底在 y=0、车头朝 -Z），
# 每帧跟着 agent 位姿摆一下，不参与物理、不挡路。
ROBOT_ASSET_DIR = "assets/go2"       # 相对本包目录
ROBOT_CONFIG_NAME = "go2.object_config.json"
ROBOT_HIDDEN_Y = -1000.0             # 隐藏时挪到地平线以下：引擎没暴露 visible 开关
ROBOT_MAX_YAW_OFFSET = 180.0         # 自定义模型朝向修正的角度上限

# ---- 会话录制（mp4 导出，docs/09 #10）----
RECORD_FPS = 10.0          # 落帧采样率（引擎 15–20 fps，这里按时间抽样）
RECORD_MAX_FRAMES = 6000   # 10 分钟；超出后丢帧，避免单局把磁盘撑爆
VIDEO_FPS = 10             # mp4 标称帧率，与采样率对齐，播放速度才是 1x
