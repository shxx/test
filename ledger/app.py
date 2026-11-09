"""HTTP 接入层：路由、统一响应/错误信封、脱敏序列化层。

- 所有读接口（IF-3~IF-7）经 AuthMiddleware 取 DomainContext，再构造 Repository
- 负向契约（§3.5）：全量字典 / 无分页全量 / 全量下载 / 角色切换端点显式 404
- 统一序列化层施加 redact_metrics（NFR-05），台账/KPI/详情/导出同源
"""
from __future__ import annotations

import json
import re
import traceback
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import quote

from .auth import AuthService
from .config import Settings
from .domain import DomainContext
from .errors import ApiError, envelope, new_trace_id
from .repository import Repository
from .services import AdminService, AuditService, ExportService, KpiService, LedgerService, MetaService

# 显式不提供（design.md §3.5）；即使被路由模式误匹配也一律 404
DENY_PATHS = frozenset({
    "/api/v1/stores/all",
    "/api/v1/exports/all",
    "/api/v1/auth/switch-role",
    "/api/v1/stores/export",
})
DENY_PREFIXES = ("/api/v1/dict", "/api/v1/competitors", "/api/v1/map", "/api/v1/blocks/all")

REDACT_KEYS = frozenset({
    "rooms", "occ", "adr", "revpar", "rooms_v", "occ_v", "adr_v", "revpar_v",
    "revpar_median", "weighted",
})


@dataclass
class Response:
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def json_body(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


def _redact(value: Any) -> Any:
    """统一序列化层：脱敏展示版把所有经营指标字段置空。"""
    if isinstance(value, dict):
        return {k: (None if k in REDACT_KEYS else _redact(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    return value


class App:
    def __init__(self, conn: Any, settings: Settings | None = None):
        self.conn = conn
        self.settings = settings or Settings()
        self.auth = AuthService(conn, self.settings)
        self.audit = AuditService(conn, self.settings)

    # ---------- 统一响应 ----------
    def _ok(self, data: Any, status: int = 200, *, extra_meta: Mapping[str, Any] | None = None) -> Response:
        meta = {"data_version": self.settings.data_version, "as_of_date": self.settings.as_of_date}
        if extra_meta:
            meta.update(dict(extra_meta))
        payload = _redact(data) if self.settings.redact_metrics else data
        body = envelope(payload, meta=meta)
        return Response(status, {"Content-Type": "application/json; charset=utf-8"},
                        json.dumps(body, ensure_ascii=False).encode("utf-8"))

    def _err(self, err: ApiError, trace_id: str) -> Response:
        body = envelope(error=err, trace_id=trace_id)
        return Response(err.status, {"Content-Type": "application/json; charset=utf-8"},
                        json.dumps(body, ensure_ascii=False).encode("utf-8"))

    # ---------- 请求入口 ----------
    def handle(
        self,
        method: str,
        path: str,
        query: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        body: bytes = b"",
    ) -> Response:
        trace_id = new_trace_id()
        q = _flatten(query or {})
        h = {k.lower(): v for k, v in (headers or {}).items()}
        try:
            return self._route(method.upper(), path.rstrip("/") or "/", q, h, body, trace_id)
        except ApiError as e:
            return self._err(e, trace_id)
        except Exception:
            # 不向客户端泄露堆栈/凭据
            if self.settings.log_tracebacks:
                traceback.print_exc()
            return self._err(ApiError("INTERNAL_ERROR"), trace_id)

    def _route(self, method, path, q, h, body, trace_id) -> Response:
        if path == "/healthz":
            if method != "GET":
                raise ApiError("METHOD_NOT_ALLOWED")
            return self._ok({"status": "ok"})

        if path in DENY_PATHS or any(path.startswith(p) for p in DENY_PREFIXES):
            raise ApiError("NOT_FOUND")

        # 无鉴权端点
        if path == "/api/v1/auth/login":
            if method != "POST":
                raise ApiError("METHOD_NOT_ALLOWED")
            payload = _json_body(body)
            return self._ok(self.auth.login(payload.get("username"), payload.get("password")))

        if path == "/api/v1/auth/logout":
            if method != "POST":
                raise ApiError("METHOD_NOT_ALLOWED")
            token = _bearer(h)
            self.auth.authenticate(token)
            self.auth.logout(token)
            return Response(204, {}, b"")

        # 以下端点全部要求有效会话 + 有效域
        ctx = self.auth.authenticate(_bearer(h))
        repo = Repository(self.conn, ctx, self.settings)
        services = self._services(repo, ctx)

        if path == "/api/v1/me/domain":
            if method != "GET":
                raise ApiError("METHOD_NOT_ALLOWED")
            return self._ok(services["meta"].build(ctx))

        if path == "/api/v1/stores":
            if method != "GET":
                raise ApiError("METHOD_NOT_ALLOWED")
            return self._ok(services["ledger"].list_stores(ctx, q))

        m = re.fullmatch(r"/api/v1/stores/([^/]+)", path)
        if m:
            if method != "GET":
                raise ApiError("METHOD_NOT_ALLOWED")
            return self._ok(services["ledger"].detail(ctx, _unquote(m.group(1))))

        if path == "/api/v1/kpi":
            if method != "GET":
                raise ApiError("METHOD_NOT_ALLOWED")
            return self._ok(services["kpi"].compute(ctx, q))

        if path == "/api/v1/exports":
            if method != "POST":
                raise ApiError("METHOD_NOT_ALLOWED")
            payload = _json_body(body)
            filename, content, row_count, signature = services["export"].run(ctx, payload)
            disposition = (
                "attachment; filename=\"store_ledger.csv\"; "
                f"filename*=UTF-8''{quote(filename)}"
            )
            return Response(
                200,
                {
                    "Content-Type": "text/csv; charset=utf-8",
                    "Content-Disposition": disposition,
                    "X-Export-Row-Count": str(row_count),
                    "X-Filter-Signature": signature,
                },
                content,
            )

        m = re.fullmatch(r"/api/v1/admin/users/([^/]+)", path)
        if m:
            if method != "PATCH":
                raise ApiError("METHOD_NOT_ALLOWED")
            payload = _json_body(body)
            return self._ok(services["admin"].change_role(
                ctx, _unquote(m.group(1)), payload.get("role"), payload.get("scope")
            ))

        if path == "/api/v1/admin/audit":
            if method != "GET":
                raise ApiError("METHOD_NOT_ALLOWED")
            return self._ok(services["admin"].audit_query(ctx, q))

        raise ApiError("NOT_FOUND")

    def _services(self, repo: Repository, ctx: DomainContext) -> dict[str, Any]:
        return {
            "meta": MetaService(repo, self.settings),
            "ledger": LedgerService(repo, self.settings, self.audit),
            "kpi": KpiService(repo, self.settings),
            "export": ExportService(repo, self.settings, self.audit),
            "admin": AdminService(self.conn, self.settings, self.audit),
        }


def _flatten(query: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in query.items():
        if isinstance(v, (list, tuple)):
            out[k] = v[0] if len(v) == 1 else list(v)
        else:
            out[k] = v
    return out


def _bearer(headers: Mapping[str, str]) -> str | None:
    raw = headers.get("authorization", "")
    if not raw:
        return None
    parts = raw.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def _json_body(body: bytes) -> dict[str, Any]:
    if not body:
        return {}
    try:
        obj = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ApiError("INVALID_FILTER", "请求体必须为合法 JSON")
    if not isinstance(obj, dict):
        raise ApiError("INVALID_FILTER", "请求体必须为 JSON 对象")
    return obj


def _unquote(s: str) -> str:
    from urllib.parse import unquote
    return unquote(s)
