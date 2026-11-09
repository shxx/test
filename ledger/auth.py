"""登录、服务端会话与每请求鉴权中间件（FR-01 / AC-08 / ADR-1）。

- 不透明令牌（CSPRNG），服务端只存 sha256(token_hash)
- 会话表绑定 role_version；角色变更后旧令牌立即 ROLE_CHANGED_RELOGIN
- 登录失败统一 401，不区分用户是否存在（不回显枚举信息）
- 域上下文只由 users 当前记录构造，忽略任何客户端 role/domain 参数
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import GEO_NAMES_BY_KIND_SQL
from .domain import DomainContext
from .errors import ApiError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def hash_password(password: str, iterations: int) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, expected_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), expected_hex)
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_whitelists(conn: Any) -> tuple[frozenset[str], frozenset[str]]:
    """按「名称 + kind」加载地域大区白名单，绝不按 ordinal 索引取前五个（DM-07）。

    品牌白名单取 brand 字段实际取值（排除 region 字典中的品牌值，两个不同字段）。
    """
    geo = frozenset(str(r["name"]) for r in conn.execute(GEO_NAMES_BY_KIND_SQL))
    brands = frozenset(
        str(r["brand"])
        for r in conn.execute(
            "SELECT DISTINCT brand FROM stores WHERE brand IS NOT NULL AND brand <> '' "
            "AND brand NOT IN (SELECT name FROM region_dict WHERE kind='BRAND_VALUE')"
        )
    )
    return geo, brands


def build_context(
    user: Any,
    geo_whitelist: frozenset[str],
    brand_whitelist: frozenset[str],
    *,
    ignored_client_params: tuple[str, ...] = (),
    locked_dimension_ignored: tuple[str, ...] = (),
    notes: tuple[str, ...] = (),
) -> DomainContext:
    role = str(user["role"])
    scope = user["region_scope"] if role == "REGION" else (
        user["brand_scope"] if role == "BRAND_BU" else None
    )
    return DomainContext(
        user_id=str(user["user_id"]),
        username=str(user["username"]),
        display_name=str(user["display_name"] or user["username"]),
        role=role,
        scope=None if scope is None else str(scope),
        role_version=int(user["role_version"]),
        is_admin=bool(user["is_admin"]),
        geo_whitelist=geo_whitelist,
        brand_whitelist=brand_whitelist,
        ignored_client_params=ignored_client_params,
        locked_dimension_ignored=locked_dimension_ignored,
        notes=notes,
    )


def _load_user(conn: Any, user_id: str) -> Any:
    return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()


class AuthService:
    def __init__(self, conn: Any, settings: Any):
        self.conn = conn
        self.settings = settings

    def login(self, username: str, password: str) -> dict[str, Any]:
        if not isinstance(username, str) or not isinstance(password, str):
            raise ApiError("AUTH_FAILED")
        user = self.conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        # 恒定时间：用户不存在时也做一次等价哈希运算
        stored = user["password_hash"] if user else hash_password("dummy", self.settings.pbkdf2_iterations)
        ok = verify_password(password, stored)
        if not user or not ok or user["status"] != "ACTIVE":
            raise ApiError("AUTH_FAILED")

        geo, brands = load_whitelists(self.conn)
        ctx = build_context(user, geo, brands)
        # 登录即校验域有效性：无有效角色/域为空 -> 拒绝进入，不返回空台账
        from .domain import validate_domain

        validate_domain(ctx)

        token = secrets.token_urlsafe(self.settings.token_bytes)
        now = _utcnow()
        expires = now + timedelta(seconds=self.settings.session_ttl_seconds)
        self.conn.execute(
            "INSERT INTO sessions(token_hash, user_id, role_snapshot, domain_snapshot, "
            "role_version, issued_at, expires_at, revoked, last_seen_at) "
            "VALUES (?,?,?,?,?,?,?,0,?)",
            (
                token_hash(token), user["user_id"], ctx.role,
                json.dumps(ctx.domain_dict(), ensure_ascii=False), ctx.role_version,
                _iso(now), _iso(expires), _iso(now),
            ),
        )
        self.conn.commit()
        return {
            "token": token,
            "token_type": "Bearer",
            "issued_at": _iso(now),
            "expires_at": _iso(expires),
            "user": ctx.identity(),
        }

    def authenticate(self, token: str | None) -> DomainContext:
        if not token:
            raise ApiError("TOKEN_MISSING")
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE token_hash = ?", (token_hash(token),)
        ).fetchone()
        if row is None:
            raise ApiError("TOKEN_INVALID")
        if bool(row["revoked"]):
            raise ApiError("SESSION_REVOKED")
        now = _utcnow()
        if _parse(row["expires_at"]) <= now:
            raise ApiError("TOKEN_EXPIRED")
        last_seen = _parse(row["last_seen_at"]) if row["last_seen_at"] else None
        if last_seen is not None and (now - last_seen) > timedelta(seconds=self.settings.idle_ttl_seconds):
            raise ApiError("TOKEN_EXPIRED")

        user = _load_user(self.conn, row["user_id"])
        if user is None or user["status"] != "ACTIVE":
            raise ApiError("SESSION_REVOKED")
        # AC-08：每请求实时比对，不使用缓存
        if int(row["role_version"]) != int(user["role_version"]):
            raise ApiError("ROLE_CHANGED_RELOGIN")

        geo, brands = load_whitelists(self.conn)
        ctx = build_context(user, geo, brands)
        from .domain import validate_domain

        validate_domain(ctx)
        self.conn.execute(
            "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
            (_iso(now), token_hash(token)),
        )
        self.conn.commit()
        return ctx

    def logout(self, token: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET revoked = 1 WHERE token_hash = ?", (token_hash(token),)
        )
        self.conn.commit()
