"""统一错误码与统一响应信封（design.md §3.2 / §3.3）。

错误码为契约的一部分。401 与 403 的区分按 requirement.md §6.4；
所有拒绝响应都不回显域外对象字段。
"""
from __future__ import annotations

import uuid
from typing import Any

# code -> (http_status, 客户端提示)
ERROR_CODES: dict[str, tuple[int, str]] = {
    "AUTH_FAILED": (401, "账号或口令错误"),
    "TOKEN_MISSING": (401, "缺少会话令牌，请重新登录"),
    "TOKEN_INVALID": (401, "会话令牌无效，请重新登录"),
    "TOKEN_EXPIRED": (401, "会话已过期，请重新登录"),
    "SESSION_REVOKED": (401, "会话已失效，请重新登录"),
    "ROLE_CHANGED_RELOGIN": (401, "角色已变更，请重新登录"),
    "NO_VALID_DOMAIN": (403, "无有效数据域"),
    "OUT_OF_DOMAIN": (403, "超出数据域"),
    "EXPORT_OUT_OF_DOMAIN": (403, "超出数据域（拒绝整单）"),
    "EXPORT_LIMIT_EXCEEDED": (422, "请收窄口径"),
    "EXPORT_DISABLED": (403, "导出已禁用"),
    "INVALID_FILTER": (400, "筛选条件不合法"),
    "LOCKED_DIMENSION": (400, "已锁定"),
    "ADMIN_FORBIDDEN": (403, "无权限"),
    "NOT_FOUND": (404, "资源不存在"),
    "METHOD_NOT_ALLOWED": (405, "方法不允许"),
    "INTERNAL_ERROR": (500, "服务内部错误"),
}


class ApiError(Exception):
    def __init__(self, code: str, message: str | None = None, *, detail: Any = None):
        if code not in ERROR_CODES:
            code = "INTERNAL_ERROR"
        self.code = code
        self.status, default_msg = ERROR_CODES[code]
        self.message = message or default_msg
        self.detail = detail
        super().__init__(f"{code}: {self.message}")


def new_trace_id() -> str:
    return uuid.uuid4().hex


def envelope(
    data: Any = None,
    *,
    meta: dict[str, Any] | None = None,
    error: ApiError | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "data": None if error else data,
        "meta": meta or {},
        "error": None,
        "trace_id": trace_id or new_trace_id(),
    }
    if error is not None:
        body["error"] = {"code": error.code, "message": error.message}
    return body
