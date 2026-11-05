"""应用入口：装配路由、异常处理与静态资源。"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import (
    analysis,
    audit,
    auth,
    datasets,
    imports,
    models,
    overview,
    replay,
    reports,
    splits,
    system,
    tasks,
    templates,
    users,
)
from .core.config import get_settings
from .core.events import BUS
from .core.logging import setup_logging
from .core.response import (
    INTERNAL_ERROR,
    NOT_FOUND,
    PARAM_INVALID,
    UNAUTHORIZED,
    AppError,
)
from .core.security import init_secret, set_iterations
from .db.seed import seed_all
from .db.session import init_database, session_scope
from .services.backup_auto_importer import get_auto_importer
from .services.scheduler import get_scheduler

logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

PLACEHOLDER_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>具身导航多模态流式评测与诊断软件 V1.0</title>
<style>body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:#0f172a;color:#e2e8f0;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.box{max-width:640px;padding:40px;border:1px solid #1e293b;border-radius:14px;background:#111c33}
h1{font-size:20px;margin:0 0 12px}p{color:#94a3b8;line-height:1.8;margin:6px 0}
code{background:#1e293b;padding:2px 6px;border-radius:4px;color:#7dd3fc}</style></head>
<body><div class="box"><h1>具身导航多模态流式评测与诊断软件 V1.0</h1>
<p>服务端已启动，前端构建产物尚未生成。</p>
<p>开发模式：<code>cd frontend &amp;&amp; npm install &amp;&amp; npm run dev</code></p>
<p>生产模式：<code>cd frontend &amp;&amp; npm run build</code> 后刷新本页。</p>
<p>接口文档：<a style="color:#7dd3fc" href="/docs">/docs</a></p></div></body></html>"""


def bootstrap() -> None:
    """初始化配置、日志、密钥与数据库，并写入种子数据。"""
    settings = get_settings()
    setup_logging(settings)
    init_secret(settings.secret_file)
    set_iterations(settings.security.pbkdf2_iterations)
    first_time = init_database(settings)
    with session_scope() as session:
        summary = seed_all(session, settings)
    logger.info(
        "初始化完成 first_time=%s 种子=%s 工作目录=%s",
        first_time,
        summary,
        settings.storage.work_dir,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    BUS.bind_loop(asyncio.get_running_loop())
    scheduler = get_scheduler()
    await scheduler.start()
    app.state.scheduler = scheduler
    auto_importer = get_auto_importer()
    await auto_importer.start()
    app.state.backup_auto_importer = auto_importer
    logger.info("服务已启动")
    yield
    await auto_importer.shutdown()
    await scheduler.shutdown()
    logger.info("服务已停止")


def create_app() -> FastAPI:
    bootstrap()

    app = FastAPI(
        title="具身导航多模态流式评测与诊断软件",
        version="1.0.0",
        description="NavEval Studio 服务端接口",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for module in (
        auth,
        users,
        system,
        overview,
        audit,
        datasets,
        splits,
        imports,
        models,
        templates,
        tasks,
        analysis,
        reports,
        replay,
    ):
        app.include_router(module.router, prefix="/api")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "version": "1.0.0"}

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={"code": exc.code, "message": exc.message, "data": None},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(part) for part in first.get("loc", [])[1:]) or "参数"
        return JSONResponse(
            status_code=400,
            content={
                "code": PARAM_INVALID,
                "message": f"{field}: {first.get('msg', '参数不合法')}",
                "data": {"errors": exc.errors()},
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = UNAUTHORIZED if exc.status_code == 401 else NOT_FOUND
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": code if exc.status_code < 500 else INTERNAL_ERROR,
                     "message": str(exc.detail), "data": None},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常 %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"code": INTERNAL_ERROR, "message": "服务内部错误", "data": None},
        )

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    index_file = FRONTEND_DIST / "index.html"
    assets_dir = FRONTEND_DIST / "assets"

    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    if index_file.exists():

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            candidate = (FRONTEND_DIST / full_path).resolve()
            if (
                full_path
                and FRONTEND_DIST.resolve() in candidate.parents
                and candidate.is_file()
            ):
                return FileResponse(candidate)
            return FileResponse(index_file)

    else:

        @app.get("/", include_in_schema=False)
        async def placeholder():
            return HTMLResponse(PLACEHOLDER_HTML)


app = create_app()
