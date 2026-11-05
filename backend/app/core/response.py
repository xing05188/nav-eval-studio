"""统一响应结构与业务异常。

所有接口返回 {"code": 0, "message": "ok", "data": ...}；
异常通过 AppError 抛出，由 main.py 的异常处理器转换为对应 HTTP 状态。
"""

from __future__ import annotations

from typing import Any

# 业务错误码
OK = 0
PARAM_INVALID = 1001
UNAUTHORIZED = 1002
FORBIDDEN = 1003
NOT_FOUND = 1004
CONFLICT = 1005
CAUSAL_VIOLATION = 1006
INTERNAL_ERROR = 2001
BACKEND_UNAVAILABLE = 2002

DEFAULT_STATUS = {
    PARAM_INVALID: 400,
    UNAUTHORIZED: 401,
    FORBIDDEN: 403,
    NOT_FOUND: 404,
    CONFLICT: 409,
    CAUSAL_VIOLATION: 422,
    INTERNAL_ERROR: 500,
    BACKEND_UNAVAILABLE: 503,
}


class AppError(Exception):
    """可预期的业务异常。"""

    def __init__(self, code: int, message: str, http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status or DEFAULT_STATUS.get(code, 400)


def ok(data: Any = None, message: str = "ok") -> dict[str, Any]:
    return {"code": OK, "message": message, "data": data}


def fail(code: int, message: str, http_status: int | None = None) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "data": None,
        "http_status": http_status or DEFAULT_STATUS.get(code, 400),
    }


def page(items: list[Any], total: int, page_no: int, page_size: int) -> dict[str, Any]:
    return {
        "items": items,
        "total": total,
        "page": page_no,
        "page_size": page_size,
    }
