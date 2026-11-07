"""模型预测适配层：把旧脚本 `scripts/dog_sim/vln_policy.py` 的 `VLNPolicy` 搬进平台。

与旧实现的三点差异（docs/08 §9）：
1. **不改工作目录**：旧实现 `os.chdir(REPO_ROOT)` 是进程级的，会打乱平台 `storage/`、
   `config/` 的相对路径。这里把 habitat 配置改成绝对路径传进去，
   `habitat_baselines.get_config()` 用 `dirname(config_path)` 当 hydra 搜索根，绝对路径同样成立。
2. **不 import `vln_policy`**：用 `importlib` 按 `code_path` 显式加载 `streamvln_eval`，
   平台不需要把旧脚本目录放进 PATH/sys.path。`sys.path` 只做 **append**，避免 StreamVLN
   仓库根下的 `config/`、`utils/` 遮蔽平台同名模块。
3. **不长期持有 sim**：`VLNEvaluator.__init__` 只读配置（`get_habitat_config` + sensor 规格），
   不建 `habitat.Env`，所以模型侧与引擎侧的 Simulator 互不干扰，同卡也不会各占一份显存。

对外只暴露 `ModelSession.load() / infer() / reset() / close()` 与状态字段；
`infer()` 返回 Habitat 编码动作（0 停止 / 1 前进 / 2 左转 / 3 右转），字符串映射在 `engine` 侧。
"""

from __future__ import annotations

import argparse
import gc
import importlib.util
import logging
import os
import sys
import threading
import time

import numpy as np

logger = logging.getLogger(__name__)

# ---- 默认参数（与评测节奏对齐，见旧脚本文件头「单位注意」）----
DEFAULT_NUM_FRAMES = 8          # 每 8 次 forward ≈ 32 个环境步做一次历史汇总
DEFAULT_NUM_HISTORY = 8
DEFAULT_NUM_FUTURE_STEPS = 4    # 一次 forward 出几个动作
DEFAULT_MAX_LENGTH = 4096
DEFAULT_OUTPUT_DIR = "/tmp/naveval_policy"
DEFAULT_HABITAT_CONFIG = "config/vln_r2r.yaml"
DEFAULT_SEED = 42
ACTIONS_MIN, ACTIONS_MAX = 0, 3


class PolicyError(RuntimeError):
    """模型侧任何失败都收敛成这个异常，由上层翻译成中文文案。"""


# ---------------------------------------------------------------------------
# 模块装载：显式按 code_path 加载，不依赖 cwd
# ---------------------------------------------------------------------------
def prepare_import_paths(code_path: str) -> str:
    """把 StreamVLN 仓库根与 `streamvln/` 追加进 sys.path（append，不前插）。"""
    root = os.path.abspath(code_path or "")
    if not root or not os.path.isdir(root):
        raise PolicyError(f"模型代码目录不存在：{code_path!r}（请检查模型档案的 code_path）")
    for path in (root, os.path.join(root, "streamvln")):
        if path in sys.path:                 # 挪到末尾，保证平台自身模块优先
            sys.path.remove(path)
        sys.path.append(path)
    return root


def load_evaluator_module(code_path: str):
    """按文件路径加载 `streamvln/streamvln_eval.py`，返回模块对象（进程内只加载一次）。"""
    cached = sys.modules.get("streamvln_eval")
    if cached is not None:
        return cached
    root = prepare_import_paths(code_path)
    entry = os.path.join(root, "streamvln", "streamvln_eval.py")
    if not os.path.isfile(entry):
        raise PolicyError(f"找不到 StreamVLN 评测入口：{entry}")
    spec = importlib.util.spec_from_file_location("streamvln_eval", entry)
    if spec is None or spec.loader is None:
        raise PolicyError(f"无法加载 {entry}")
    module = importlib.util.module_from_spec(spec)
    # 先占位再执行：模块内部有 dataclass / 自引用时会按名字回查 sys.modules
    sys.modules["streamvln_eval"] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop("streamvln_eval", None)
        raise
    return module


def build_args(
    *,
    model_path: str,
    habitat_config: str,
    num_frames: int = DEFAULT_NUM_FRAMES,
    num_history: int = DEFAULT_NUM_HISTORY,
    num_future_steps: int = DEFAULT_NUM_FUTURE_STEPS,
    max_length: int = DEFAULT_MAX_LENGTH,
    output_path: str = DEFAULT_OUTPUT_DIR,
    seed: int = DEFAULT_SEED,
    gpu: int = 0,
    prune_mode: str = "off",
) -> argparse.Namespace:
    """构造与 `streamvln_eval.py:eval()` 同名的参数表（缺一个字段 `VLNEvaluator` 就会 AttributeError）。

    `prune_mode` **必须显式 "off"**：这是"几何张量不参与计算"的硬不变量。
    本模块喂的 depth 是全零 5D、pose 是 eye(4)，一旦打开剪枝，会被静默跳过或污染体素归属。
    """
    return argparse.Namespace(
        local_rank=0, model_path=model_path, habitat_config_path=habitat_config,
        eval_split="val_seen", eval_role=None, output_path=output_path,
        num_future_steps=num_future_steps, num_frames=num_frames, save_video=False,
        num_history=num_history, seed=seed, cost_csv="", geo_prefix=0, motion_prefix=0,
        action_chunk=0, model_max_length=max_length, world_size=1, rank=0, gpu=gpu,
        port="1111", dist_url="env://", device="cuda", prune_mode=prune_mode,
    )


# ---------------------------------------------------------------------------
# dry-run 替身（无 GPU 也能验证 tokenizer / 视觉处理器 / prompt 拼装）
# ---------------------------------------------------------------------------
class _StubVisionTower:
    def __init__(self, image_processor):
        self.image_processor = image_processor


class _StubInner:
    """承接 `VLNEvaluator` 往 `model.model` 上挂的配置（W13 起会写 prune_cfg）。"""


class _StubModel:
    def __init__(self, image_processor):
        self._tower = _StubVisionTower(image_processor)
        self.model = _StubInner()

    def get_vision_tower(self):
        return self._tower

    def reset_for_env(self, idx):
        return None


# ---------------------------------------------------------------------------
# 单次会话：一个实例独占一份权重
# ---------------------------------------------------------------------------
class ModelSession:
    """一次 forward 出 `num_future_steps` 个动作；**不碰 habitat sim**，只吃 RGB 数组。

    线程约定：`load()` / `close()` 由会话线程调用，`infer()` 由推理线程调用，
    内部加锁保证不会并发进模型（CUDA 上并发推理会把显存顶爆）。
    """

    def __init__(
        self,
        *,
        code_path: str,
        weights_path: str,
        habitat_config: str = DEFAULT_HABITAT_CONFIG,
        device_index: int = 0,
        num_frames: int = DEFAULT_NUM_FRAMES,
        num_history: int = DEFAULT_NUM_HISTORY,
        num_future_steps: int = DEFAULT_NUM_FUTURE_STEPS,
        max_length: int = DEFAULT_MAX_LENGTH,
        dry_run: bool = False,
        seed: int = DEFAULT_SEED,
    ) -> None:
        self.code_path = os.path.abspath(code_path or "")
        self.weights_path = os.path.abspath(weights_path or "")
        self.habitat_config = habitat_config or DEFAULT_HABITAT_CONFIG
        self.device_index = int(device_index)
        self.num_frames = max(1, int(num_frames))
        self.num_history = max(1, int(num_history))
        self.num_future_steps = max(1, int(num_future_steps))
        self.max_length = int(max_length)
        self.dry_run = bool(dry_run)
        self.seed = int(seed)
        self.output_path = DEFAULT_OUTPUT_DIR

        self.args: argparse.Namespace | None = None
        self.model = None
        self.tokenizer = None
        self.ev = None
        self.torch = None

        # 推理态：与旧脚本字段一一对应
        self.past_key_values = None
        self.output_ids = None
        self.time_ids: list[int] = []
        self.step_id = 0
        self.instruction: str | None = None
        self.rgb_list: list = []
        self.intrinsic_list: list = []

        self.load_seconds = 0.0
        self._loaded = False
        self._lock = threading.Lock()

    # -- 生命周期 -----------------------------------------------------------
    def load(self) -> None:
        """加载 tokenizer / 权重 / 评测器；失败抛 `PolicyError`（已带中文原因）。"""
        if self._loaded:
            return
        t0 = time.time()
        try:
            self._load_once()
        except PolicyError:
            self._teardown()
            raise
        except BaseException as exc:  # noqa: BLE001 权重/OOM/依赖问题都要翻译成人话
            self._teardown()
            raise PolicyError(self._explain(exc)) from exc
        self.load_seconds = time.time() - t0
        self._loaded = True
        logger.info(
            "模型已就绪 dry_run=%s 显存卡=%s 用时 %.1fs",
            self.dry_run, self.device_index, self.load_seconds,
        )

    def reset(self) -> None:
        """清 KV / 历史 / 计步；手动接管与换局时调用。"""
        if self.model is None:
            return
        with self._lock:
            if hasattr(self.model, "reset"):
                self.model.reset(1)
            self.model.reset_for_env(0)
            self.past_key_values = None
            self.output_ids = None
            self.time_ids = []
            self.step_id = 0
            self.instruction = None
            self.rgb_list = []
            self.intrinsic_list = []

    def infer(self, rgb_uint8: np.ndarray, instruction: str | None = None) -> list[int]:
        """一次 forward → 动作列表（Habitat 编码）。异常统一抛 `PolicyError`。"""
        if not self._loaded:
            raise PolicyError("模型尚未加载完成")
        with self._lock:
            try:
                acts = self._step(rgb_uint8, instruction)
            except PolicyError:
                raise
            except BaseException as exc:  # noqa: BLE001
                raise PolicyError(self._explain(exc)) from exc
        acts = [int(a) for a in acts if ACTIONS_MIN <= int(a) <= ACTIONS_MAX]
        if not acts:
            acts = [0]
        return acts[: self.num_future_steps]

    def close(self) -> None:
        """释放权重与显存（同进程内可重复调用）。"""
        self._teardown()

    @property
    def loaded(self) -> bool:
        return self._loaded

    # -- 内部 ---------------------------------------------------------------
    def _load_once(self) -> None:
        import torch
        import transformers

        self.torch = torch
        if not self.dry_run:
            if not torch.cuda.is_available():
                raise PolicyError("当前环境不可用 CUDA，无法加载模型权重")
            if self.device_index >= torch.cuda.device_count():
                raise PolicyError(
                    f"GPU{self.device_index} 不存在（当前只可见 {torch.cuda.device_count()} 张卡）")
            # 之后所有 .cuda() / from_pretrained 的默认落点都是这张卡
            torch.cuda.set_device(self.device_index)

        os.makedirs(self.output_path, exist_ok=True)
        self.args = build_args(
            model_path=self.weights_path,
            habitat_config=os.path.abspath(self.habitat_config),
            num_frames=self.num_frames,
            num_history=self.num_history,
            num_future_steps=self.num_future_steps,
            max_length=self.max_length,
            output_path=self.output_path,
            seed=self.seed,
            gpu=self.device_index,
        )
        if not os.path.isdir(self.weights_path):
            raise PolicyError(f"权重目录不存在：{self.weights_path}（请检查模型档案的 weights_path）")

        # 先装载评测模块：它会补齐 sys.path 并 import model 包，真实权重那步依赖它
        ev_mod = load_evaluator_module(self.code_path)

        self.tokenizer = transformers.AutoTokenizer.from_pretrained(
            self.args.model_path, model_max_length=self.args.model_max_length,
            padding_side="right")

        if self.dry_run:
            image_processor = self._dryrun_image_processor(transformers)
            model = _StubModel(image_processor)
            logger.info("dry-run：不加载权重，视觉处理器=%s", type(image_processor).__name__)
        else:
            from model.stream_video_vln import StreamVLNForCausalLM

            cfg = transformers.AutoConfig.from_pretrained(self.args.model_path)
            model = StreamVLNForCausalLM.from_pretrained(
                self.args.model_path, attn_implementation="eager",
                load_in_8bit=True, torch_dtype=torch.bfloat16, config=cfg)
            model.model.num_history = self.args.num_history
            model.requires_grad_(False)
            model.eval()
            logger.info("权重已加载（8bit, bf16）")

        self.ev = ev_mod.VLNEvaluator(
            config_path=self.args.habitat_config_path, split=self.args.eval_split,
            env_num=1, output_path=self.args.output_path, model=model,
            tokenizer=self.tokenizer, epoch=0, args=self.args)
        self.model = model
        # 显式清掉本帧的强引用：实测本帧会被 C 层（pybind/accelerate 的回调注册）长期持有，
        # 帧一旦钉住 f_locals 里的 model，`close()` 之后就永远回收不掉（实测残留 8.7 GB）。
        # 置成 None 后即使帧泄漏，泄漏的也只是几个空引用，权重可以正常释放。
        model = None
        cfg = None
        ev_mod = None
        self.reset()

    @staticmethod
    def _dryrun_image_processor(transformers):
        """真模型的 image_processor 来自视觉塔（LLaVA 惯例 = CLIPImageProcessor, crop 384）。"""
        try:
            from transformers import CLIPImageProcessor

            return CLIPImageProcessor.from_pretrained("google/siglip-so400m-patch14-384")
        except Exception as exc:  # noqa: BLE001 没有缓存时退化为 checkpoint 自带配置
            logger.warning("取 siglip 的 CLIPImageProcessor 失败（%s），退化到 checkpoint 自带配置",
                           type(exc).__name__)
            return transformers.AutoImageProcessor.from_pretrained(self.weights_path)

    def _teardown(self) -> None:
        self._loaded = False
        self.model = None
        self.ev = None
        self.tokenizer = None
        self.past_key_values = None
        self.output_ids = None
        self.time_ids = []
        self.rgb_list = []
        self.intrinsic_list = []
        torch, self.torch = self.torch, None
        if torch is None:
            return
        try:
            # 权重对象之间是循环引用（module ↔ 子模块），只置 None 不会立刻回收，
            # 必须 collect 之后再 empty_cache，显存才会真正还给驱动（P3 验收项 2）。
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # noqa: BLE001 清缓存失败不影响释放
            logger.debug("释放显存失败", exc_info=True)

    # -- 单帧预处理（镜像 streamvln_eval.py:397-409）-------------------------
    def _prep_image(self, rgb_uint8: np.ndarray):
        from PIL import Image

        img = Image.fromarray(rgb_uint8).convert("RGB")
        size = img.size
        tensor = self.ev.image_processor.preprocess(images=img, return_tensors="pt")["pixel_values"][0]
        return tensor, size

    def _prep_intrinsic(self, ori_size):
        """resize/crop 后的内参；`prune_mode="off"` 时它不参与计算，拿不到 crop 也不影响输出。"""
        intrinsic = self.ev.get_intrinsic_matrix(self.ev.sim_sensors_config.rgb_sensor)
        crop = getattr(self.ev.image_processor, "crop_size", None)
        if not crop:
            return intrinsic
        return self.ev.preprocess_instrinsic(intrinsic, ori_size, (crop["width"], crop["height"]))

    # -- 一次推理（逻辑与旧脚本 step() 逐行一致）----------------------------
    def _step(self, rgb_uint8: np.ndarray, instruction: str | None) -> list[int]:
        import torch
        from utils.utils import DEFAULT_MEMORY_TOKEN, DEFAULT_VIDEO_TOKEN

        image, image_size = self._prep_image(rgb_uint8)
        intrinsic = torch.from_numpy(self._prep_intrinsic(image_size)).float()
        self.rgb_list.append(image)
        self.intrinsic_list.append(intrinsic)
        self.time_ids.append(self.step_id)

        if instruction:
            self.instruction = instruction       # 记住，后续步沿用（评测里也是每步重填）
        if self.output_ids is None:
            sources = [dict(x) for x in self.ev.conversation]
            if self.instruction:
                sources[0]["value"] = sources[0]["value"].replace("<instruction>.", self.instruction)
            if self.step_id != 0:
                sources[0]["value"] += f" These are your historical observations {DEFAULT_MEMORY_TOKEN}."
            sources[0]["value"] = sources[0]["value"].replace(DEFAULT_VIDEO_TOKEN + "\n", "")
            sources[0]["value"] = sources[0]["value"].replace(DEFAULT_VIDEO_TOKEN, "")
            add_system = True
        else:
            sources = [{"from": "human", "value": ""}, {"from": "gpt", "value": ""}]
            add_system = False

        input_ids, _ = self.ev.preprocess_qwen([sources], self.tokenizer, True, add_system=add_system)
        if self.output_ids is not None:
            input_ids = torch.cat([self.output_ids, input_ids.to(self.output_ids.device)], dim=1)

        # 视觉槽位：平时只喂当前帧；每 num_frames 次 forward 做一次历史汇总，把采样到的
        # 历史帧一起喂进去。**不能省**：encode_rgbd 在 num_view == 1 时 memory_features 恒为
        # [None]，此刻 prompt 里的 <memory> 会直接 TypeError。
        views, views_intr = [image], [intrinsic]
        if self.step_id != 0 and self.step_id % self.args.num_frames == 0:
            span = self.time_ids[0]
            hist = slice(0, span, max(1, span // (self.args.num_history or 1)))
            views = self.rgb_list[hist] + views
            views_intr = self.intrinsic_list[hist] + views_intr
        n_view = len(views)
        images_t = torch.stack(views).unsqueeze(0)
        intr_t = torch.stack(views_intr).unsqueeze(0)

        if self.dry_run:
            self.step_id += 1
            return [1] * self.num_future_steps

        # 几何张量当前不参与任何计算，前提是 build_args(prune_mode="off")：prune_cfg.enabled=False
        # → encode_rgbd 直接 flatten。形状/数值只为凑过前置检查（详见旧脚本同一段注释）。
        depth = torch.zeros(1, n_view, 1, image_size[1] // 2, image_size[0] // 2)
        pose = torch.eye(4).unsqueeze(0).unsqueeze(0).repeat(1, n_view, 1, 1)

        input_dict = {"images": images_t.to(torch.bfloat16),
                      "depths": depth.to(torch.bfloat16),
                      "poses": pose.to(torch.bfloat16),
                      "intrinsics": intr_t.to(torch.bfloat16),
                      "inputs": input_ids.cuda(), "env_id": 0,
                      "time_ids": [self.time_ids], "task_type": [0]}

        with torch.no_grad():
            outputs = self.model.generate(
                **input_dict, do_sample=False, num_beams=1, max_new_tokens=10000,
                use_cache=True, return_dict_in_generate=True,
                past_key_values=self.past_key_values)
        self.output_ids = outputs.sequences
        self.past_key_values = outputs.past_key_values
        text = self.tokenizer.batch_decode(self.output_ids, skip_special_tokens=False)[0].strip()
        acts = self.ev.parse_actions(text)
        if not acts:
            acts = [0]
        self.step_id += 1
        if self.step_id % self.args.num_frames == 0:      # 与评测一致的 KV 重置节奏
            self.model.reset_for_env(0)
            self.output_ids, self.past_key_values, self.time_ids = None, None, []
        logger.debug("模型输出 %r -> actions %s", text[:60], acts)
        return acts

    @staticmethod
    def _explain(exc: BaseException) -> str:
        name = type(exc).__name__
        text = str(exc) or name
        lowered = text.lower()
        if "out of memory" in lowered or "cuda oom" in lowered:
            return (f"显存不足（{name}）：{text}。请换一张空闲显存更多的卡，"
                    "或把 min_free_mem_mb 调高后再启动。")
        if isinstance(exc, ImportError):
            return (f"模型依赖缺失（{name}）：{text}。"
                    "请确认用 streamvln-kb 环境启动平台（含 torch 2.1.2 / transformers 4.45.1 / bitsandbytes）。")
        if isinstance(exc, FileNotFoundError):
            return f"模型文件缺失（{name}）：{text}。请检查模型档案的 weights_path / code_path。"
        if "bitsandbytes" in lowered or "8bit" in lowered:
            return f"8bit 量化不可用（{name}）：{text}。可先试 load_in_4bit，或换一张卡。"
        return f"模型推理失败（{name}）：{text}"


# ---------------------------------------------------------------------------
# 模型驾驶运行时：推理线程 + 状态机（docs/08 §5）
# ---------------------------------------------------------------------------
PENDING_WATERMARK = 4      # 队列里还有这么多动作时先不再推理，避免把队列塞爆
POLL_S = 0.05              # 推理线程的轮询间隔（队列空/暂停时）


class PolicyRuntime:
    """一个引擎会话配一个运行时；线程只读引擎发布的帧，绝不碰 `sim`。

    状态机：`loading → ready → running ⇄ paused`，异常/结束 → `error` / `paused`。
    """

    def __init__(
        self,
        *,
        engine,
        model_name: str,
        code_path: str,
        weights_path: str,
        gpu_id: int = 0,
        num_frames: int = DEFAULT_NUM_FRAMES,
        num_history: int = DEFAULT_NUM_HISTORY,
        num_future_steps: int = DEFAULT_NUM_FUTURE_STEPS,
        infer_timeout_s: float = 30.0,
        habitat_config: str = DEFAULT_HABITAT_CONFIG,
        dry_run: bool = False,
    ) -> None:
        self.engine = engine
        self.model_name = model_name
        self.gpu_id = int(gpu_id)
        self.infer_timeout_s = float(infer_timeout_s or 30.0)
        self.dry_run = bool(dry_run)
        self.session = ModelSession(
            code_path=code_path, weights_path=weights_path,
            habitat_config=habitat_config, device_index=self.gpu_id,
            num_frames=num_frames, num_history=num_history,
            num_future_steps=num_future_steps, dry_run=self.dry_run,
        )

        self._lock = threading.Lock()
        self._status = "loading"
        self._message = "正在加载模型…"
        self._paused = False
        self._pending_reset = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="sim-policy", daemon=True)

        self.started_at = time.time()
        self.loaded_at = 0.0
        self.load_seconds = 0.0
        self.infer_count = 0
        self.actions_done = 0
        self.last_latency_ms = 0
        self._latency_sum = 0.0
        self._inferring_since = 0.0

    # ---- 外部接口（HTTP / 引擎线程调用）------------------------------------
    def start(self) -> None:
        self._thread.start()

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    def pause(self, message: str = "已接管，模型暂停") -> None:
        """暂停推理（手动接管 / 用户点暂停）。队列由引擎侧清空。"""
        with self._lock:
            if self._status in ("off", "error"):
                return
            was = self._status
            self._paused = True
            self._status = "paused"
            self._message = message
        self._pending_reset = True
        if was == "running":
            logger.info("模型驾驶暂停：%s", message)

    def resume(self) -> None:
        with self._lock:
            if self._status not in ("paused", "ready", "running"):
                raise PolicyError(f"当前状态 {self._status} 不能恢复模型驾驶")
            self._paused = False
            self._status = "running" if self._status == "paused" else self._status
            self._message = ""
        # 画面可能已经变了，旧 KV 继续用会给出不符合当前视角的动作
        self._pending_reset = True

    def close(self) -> None:
        """停线程 + 释放权重。可在任意状态重复调用。"""
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self.session.close()
        with self._lock:
            self._status = "off"
            self._message = ""

    def snapshot(self) -> dict:
        with self._lock:
            avg = (self._latency_sum / self.infer_count) if self.infer_count else 0.0
            inferring = (time.time() - self._inferring_since) if self._inferring_since else 0.0
            return {
                "status": self._status,
                "model": self.model_name,
                "gpu_id": self.gpu_id,
                "paused": self._paused,
                "message": self._message,
                "last_latency_ms": int(self.last_latency_ms),
                "avg_latency_ms": int(avg * 1000),
                "infer_count": self.infer_count,
                "actions_done": self.actions_done,
                "inferring_s": round(inferring, 1),
                "load_seconds": round(self.load_seconds, 1),
            }

    # ---- 推理线程 ---------------------------------------------------------
    def _run(self) -> None:
        try:
            self.session.load()
        except PolicyError as exc:
            self._fail(str(exc))
            return
        except BaseException as exc:  # noqa: BLE001 兜底，线程不能带着异常退出
            logger.exception("模型加载异常")
            self._fail(f"模型加载失败：{type(exc).__name__}: {exc}")
            return
        self.load_seconds = self.session.load_seconds
        self.loaded_at = time.time()
        with self._lock:
            # 加载期间用户就点了暂停：停在 paused，等恢复再推理
            self._status = "paused" if self._paused else "ready"
            self._message = "已暂停" if self._paused else ""
        try:
            self._loop()
        except BaseException as exc:  # noqa: BLE001
            logger.exception("推理线程异常")
            self._fail(f"推理线程异常：{type(exc).__name__}: {exc}")

    def _loop(self) -> None:
        while not self._stop.wait(POLL_S):
            if self._pending_reset:
                self._pending_reset = False
                try:
                    self.session.reset()
                except PolicyError as exc:      # 复位失败不致命，下一轮还能重试
                    logger.warning("模型 KV 复位失败：%s", exc)
            if self._paused:
                continue
            snap = self.engine.snapshot()
            if snap["status"] != "ready":
                continue
            if snap["done"]:
                self.pause("本局已结束，模型暂停")
                continue
            if snap["pending"] >= PENDING_WATERMARK:
                continue                       # 队列还满，先让引擎消化
            rgb, _seq = self.engine.latest_rgb()
            if rgb is None:
                continue
            self._infer_once(rgb)

    def _infer_once(self, rgb) -> None:
        with self._lock:
            self._inferring_since = time.time()
        t0 = time.time()
        try:
            acts = self.session.infer(rgb, self.engine.spec.instruction)
        except PolicyError as exc:
            self._inferring_since = 0.0
            self._fail(str(exc))
            self.engine.clear_pending()
            return
        elapsed = time.time() - t0
        self._inferring_since = 0.0
        if self._paused or self._stop.is_set():
            # 推理期间人接管了：这批动作是对旧画面的判断，直接丢弃并作废 KV
            self._pending_reset = True
            logger.debug("推理完成时已接管，丢弃 %d 个动作", len(acts))
            return
        if elapsed > self.infer_timeout_s:
            self._fail(f"单次推理超时（{elapsed:.0f}s > {self.infer_timeout_s:.0f}s），已切回手动")
            self.engine.clear_pending()
            return

        names = self._to_names(acts)
        accepted = self.engine.submit_model_actions(names) if names else 0
        with self._lock:
            self.infer_count += 1
            self.actions_done += accepted
            self.last_latency_ms = int(elapsed * 1000)
            self._latency_sum += elapsed
            if self._status == "ready":
                self._status = "running"
        logger.debug("模型推理 %.2fs → %s（入队 %d）", elapsed, names, accepted)

    @staticmethod
    def _to_names(acts: list[int]) -> list[str]:
        from . import constants as C     # 延迟导入：避免与 engine 的导入顺序耦合

        return [C.CODE_ACTIONS[a] for a in acts if a in C.CODE_ACTIONS]

    def _fail(self, message: str) -> None:
        logger.warning("模型驾驶失败，自动回手动：%s", message)
        with self._lock:
            self._status = "error"
            self._message = message
            self._paused = True


__all__ = [
    "ModelSession",
    "PolicyError",
    "build_args",
    "load_evaluator_module",
    "prepare_import_paths",
    "PolicyRuntime",
]
