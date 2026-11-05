"""StreamVLN 真实推理适配器。

调用方式与上游 `scripts/run_eval_kaggle.sh` 一致：
    torchrun --nproc_per_node=1 --master_port=<port> <code>/streamvln/streamvln_eval.py \
        --model_path <weights> --eval_split <split> --output_path <raw> --seed <seed> [extra]

运行期持续 tail `<raw>/result.json`（JSONL，一行一条 episode），
解析为标准记录后交给调度器，因此进度是逐条推进的，而不是等进程结束。
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Iterator

from .base import BaseAdapter, EpisodeRecord


class StreamVLNAdapter(BaseAdapter):
    name = "streamvln"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.proc: subprocess.Popen | None = None
        self.result_path: Path | None = None
        self._buffer = ""
        self._offset = 0
        self._seen: set[str] = set()
        self._log_queue: Queue[str] = Queue()
        self._tail: deque[str] = deque(maxlen=40)
        self._reader: threading.Thread | None = None

    # ---------------------------------------------------------------- 准备

    def prepare(self) -> None:
        model = self.ctx.model
        code_path = Path(str(model.get("code_path") or "")).expanduser()
        if not code_path.exists():
            raise RuntimeError(f"代码目录不存在：{code_path}")

        script = code_path / "streamvln" / "streamvln_eval.py"
        if not script.exists():
            raise RuntimeError(f"未找到评测脚本：{script}")

        weights = Path(str(model.get("weights_path") or "")).expanduser()
        if not weights.exists():
            raise RuntimeError(f"权重目录不存在：{weights}")

        launcher = str(model.get("entry") or "torchrun").strip()
        launcher_path = launcher if Path(launcher).is_absolute() else shutil.which(launcher)
        if not launcher_path or not Path(launcher_path).exists():
            raise RuntimeError(f"找不到启动器：{launcher}，请检查模型档案中的入口配置")

        raw_dir = self.ctx.run_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        self.result_path = raw_dir / "result.json"

        command = self._build_command(str(launcher_path), script, weights, raw_dir)
        self.ctx.log("启动命令：" + " ".join(command))

        env = os.environ.copy()
        config = self.ctx.config
        gpu_ids = str(config.get("gpu_ids") or "").strip()
        env["CUDA_VISIBLE_DEVICES"] = gpu_ids or "0"
        env.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")
        env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
        env.setdefault("MAGNUM_LOG", "quiet")
        env.setdefault("HABITAT_SIM_LOG", "quiet")

        self.proc = subprocess.Popen(  # noqa: S603 - 命令由本地配置拼装
            command,
            cwd=str(code_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
            start_new_session=True,
        )
        self._reader = threading.Thread(target=self._read_output, daemon=True)
        self._reader.start()
        self.ctx.log(f"子进程已启动 pid={self.proc.pid}")

    def _build_command(
        self, launcher: str, script: Path, weights: Path, raw_dir: Path
    ) -> list[str]:
        config = self.ctx.config
        eval_split = str(config.get("eval_split") or "val_unseen")
        seed = int(config.get("seed", 42))
        command = [
            launcher,
            "--nproc_per_node=1",
            f"--master_port={config.get('master_port', 29611)}",
            str(script),
            "--model_path",
            str(weights),
            "--eval_split",
            eval_split,
            "--output_path",
            str(raw_dir),
            "--seed",
            str(seed),
        ]

        extra = config.get("adapter", {}).get("extra_args") or []
        if extra:
            command.extend([str(item) for item in extra])
            return command

        command.extend(["--num_history", str(int(config.get("history_len", 8)))])
        command.extend(["--num_future_steps", str(int(config.get("num_future_steps", 4)))])
        if config.get("memory_policy") == "spatial_prune":
            prune_ratio = float(config.get("prune_ratio", 0.0))
            command.extend(["--prune_mode", "voxel"])
            if 0 < prune_ratio < 1:
                command.extend(["--prune_keep_ratio", f"{1 - prune_ratio:.3f}"])
        return command

    def _read_output(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        for line in self.proc.stdout:
            text = line.rstrip()
            if text:
                self._tail.append(text)
                self._log_queue.put(text)

    # ---------------------------------------------------------------- 执行

    def run(self) -> Iterator[EpisodeRecord]:
        if self.proc is None:
            self.prepare()
        assert self.proc is not None

        idle_rounds = 0
        while True:
            if self.ctx.should_cancel():
                self.stop()
                return

            self._flush_logs()

            produced = False
            for payload in self._read_new_records():
                record = self._to_record(payload)
                if record is None or record.episode_key in self._seen:
                    continue
                self._seen.add(record.episode_key)
                produced = True
                yield record

            if self.proc.poll() is not None:
                idle_rounds += 1
                if not produced and idle_rounds >= 2:
                    break
            else:
                idle_rounds = 0

            time.sleep(0.6)

        self._flush_logs()

        if self.proc.returncode not in (0, None):
            tail = "\n".join(list(self._tail)[-12:])
            if "out of memory" in tail.lower():
                raise RuntimeError("推理进程显存不足（OOM）\n" + tail)
            raise RuntimeError(f"推理进程退出码 {self.proc.returncode}\n{tail}")

    def _flush_logs(self) -> None:
        while True:
            try:
                line = self._log_queue.get_nowait()
            except Empty:
                return
            self.ctx.log(line)

    def _read_new_records(self) -> list[dict[str, Any]]:
        """增量读取结果文件，只解析新增的完整行。"""
        if self.result_path is None or not self.result_path.exists():
            return []

        with self.result_path.open("rb") as handle:
            handle.seek(self._offset)
            data = handle.read()
        if not data:
            return []
        self._offset += len(data)

        text = self._buffer + data.decode("utf-8", errors="replace")
        lines = text.split("\n")
        self._buffer = lines.pop()  # 最后一段可能不完整，留到下次拼接

        payloads: list[dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                payloads.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return payloads

    def _to_record(self, payload: dict[str, Any]) -> EpisodeRecord | None:
        episode_key = payload.get("episode_id")
        if episode_key is None:
            return None

        steps = int(payload.get("steps") or 0)
        elapsed = float(payload.get("elapsed_s") or 0.0)
        success = bool(payload.get("success"))
        latency = round(elapsed / steps * 1000, 2) if steps else 0.0

        reason = ""
        if not success:
            max_steps = int(self.ctx.config.get("max_steps", 500))
            reason = "timeout" if steps >= max_steps else "early_stop"

        return EpisodeRecord(
            episode_key=str(episode_key),
            scene_id=str(payload.get("scene_id") or ""),
            success=success,
            spl=float(payload.get("spl") or 0.0),
            ne=float(payload.get("ne") or 0.0),
            os=float(payload.get("os") or 0.0),
            ndtw=float(payload.get("ndtw") or 0.0),
            tl=float(payload.get("tl") or 0.0),
            steps=steps,
            latencies=[latency] if latency else [],
            gpu_mem_peak_mb=int(payload.get("peak_gpu_mem_mb") or 0),
            tokens_peak=int(float(payload.get("mean_prompt_tokens") or 0) * 100),
            ctx_len_peak=0,
            failure_reason=reason,
        )

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
