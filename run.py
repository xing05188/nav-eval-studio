#!/usr/bin/env python3
"""码极客具身导航评测与诊断软件 V1.0 启动入口。

用法：
    python run.py                     # 默认 127.0.0.1:8080
    python run.py --port 9000
    python run.py --no-browser --reload
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="码极客具身导航评测与诊断软件 V1.0")
    parser.add_argument("--host", default=None, help="监听地址，默认取配置文件")
    parser.add_argument("--port", type=int, default=None, help="监听端口，默认取配置文件")
    parser.add_argument("--config", default=None, help="配置文件路径")
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    parser.add_argument("--reload", action="store_true", help="开发模式，代码变更自动重载")
    return parser.parse_args()


def open_browser_later(url: str, delay: float = 1.5) -> None:
    def _open() -> None:
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - 无图形环境时忽略
            pass

    threading.Thread(target=_open, daemon=True).start()


def main() -> None:
    args = parse_args()
    if args.config:
        os.environ["NAVEVAL_CONFIG"] = str(Path(args.config).resolve())

    # 读取配置需要先导入；bootstrap 在模块导入时完成
    from backend.app.core.config import load_settings, set_settings

    settings = load_settings(args.config)
    set_settings(settings)

    host = args.host or settings.server.host
    port = args.port or settings.server.port
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"

    if not args.no_browser and settings.server.open_browser and not args.reload:
        open_browser_later(url)

    print("=" * 64)
    print(" 码极客具身导航评测与诊断软件 V1.0")
    print(f" 访问地址：{url}")
    print(f" 接口文档：{url}/docs")
    print(f" 工作目录：{settings.storage.work_dir}")
    print("=" * 64)

    import uvicorn

    uvicorn.run(
        "backend.app.main:app",
        host=host,
        port=port,
        reload=args.reload,
        log_level=settings.logging.level.lower(),
        # 默认 5 s 太短：页面静一会儿后浏览器复用刚被服务端关掉的连接，
        # POST /api/sim/actions 会报 ERR_INVALID_HTTP_RESPONSE（浏览器不会重试 POST）
        timeout_keep_alive=30,
    )


if __name__ == "__main__":
    main()
