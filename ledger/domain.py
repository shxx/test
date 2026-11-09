"""数据域裁决模型的输入层：DomainContext / 域谓词 / 白名单 / 筛选签名。

安全边界第一原则（requirement.md §1.3）：
  DomainContext 只能由服务端会话 -> users 当前记录构造。
  客户端传入的 role / domain / d_scope / region_scope / brand_scope 一律忽略。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .errors import ApiError

ROLES = ("HQ", "REGION", "BRAND_BU")

# 客户端不可信参数：一律忽略（DM-04），仅记录以便契约测试断言无效。
CLIENT_DOMAIN_PARAMS = frozenset(
    {"role", "domain", "d_scope", "region_scope", "brand_scope", "domain_type", "domain_scope"}
)

# 筛选白名单：字段 -> v_ledger 列名。未列出的字段一律 400 INVALID_FILTER。
FILTER_FIELDS: dict[str, str] = {
    "province": "province",
    "city": "city",
    "block": "block",
    "operate_type": "operate_type",
    "brand": "brand",
    "region": "region",
    "status": "status",
    "store_id": "store_id",
}

# 排序列白名单（含 DQ 视图列）。tiebreaker 恒为 store_id。
SORT_FIELDS: dict[str, str] = {
    "store_id": "store_id",
    "name": "name",
    "province": "province",
    "city": "city",
    "region": "region",
    "brand": "brand",
    "operate_type": "operate_type",
    "status": "status",
    "rooms": "rooms_v",
    "occ": "occ_v",
    "adr": "adr_v",
    "revpar": "revpar_v",
}

# 大区角色锁定维度（DM-08）
LOCKED_DIMENSION_BY_ROLE = {"REGION": "region"}

# 单值筛选允许的最大长度（防恶意超长构造）
MAX_FILTER_VALUE_LEN = 256


@dataclass(frozen=True)
class DomainContext:
    """服务端唯一权威的域上下文。不可由请求参数构造。"""

    user_id: str
    username: str
    display_name: str
    role: str
    scope: str | None
    role_version: int
    is_admin: bool = False
    geo_whitelist: frozenset[str] = frozenset()
    brand_whitelist: frozenset[str] = frozenset()
    ignored_client_params: tuple[str, ...] = ()
    locked_dimension_ignored: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def domain_type(self) -> str:
        return {"HQ": "all", "REGION": "region", "BRAND_BU": "brand"}[self.role]

    @property
    def label(self) -> str:
        return {"HQ": "总部", "REGION": "大区", "BRAND_BU": "品牌BU"}[self.role]

    def domain_dict(self) -> dict[str, Any]:
        return {"type": self.domain_type, "scope": self.scope}

    def identity(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
            "role_label": self.label,
            "role_version": self.role_version,
            "domain": self.domain_dict(),
            "is_admin": self.is_admin,
        }


def validate_domain(ctx: DomainContext) -> None:
    """默认拒绝：无有效角色 / 域为空 / 域值不在按名称加载的白名单。"""
    if ctx.role not in ROLES:
        raise ApiError("NO_VALID_DOMAIN")
    if ctx.role == "HQ":
        return
    if not ctx.scope or not str(ctx.scope).strip():
        raise ApiError("NO_VALID_DOMAIN")
    if ctx.role == "REGION" and ctx.scope not in ctx.geo_whitelist:
        raise ApiError("NO_VALID_DOMAIN")
    if ctx.role == "BRAND_BU" and ctx.scope not in ctx.brand_whitelist:
        raise ApiError("NO_VALID_DOMAIN")


def domain_predicate(ctx: DomainContext, alias: str = "s") -> tuple[str, dict[str, Any]]:
    """生成域谓词（参数化）。总部也返回 '1=1' 并走同一构造器，避免分支成为绕过口。

    域参数名固定 :d_scope，与用户筛选参数命名空间（:f_*）隔离。
    """
    validate_domain(ctx)
    if ctx.role == "HQ":
        return "1=1", {}
    if ctx.role == "REGION":
        return f"{alias}.region = :d_scope", {"d_scope": ctx.scope}
    # BRAND_BU：用 brand 字段，绝不用 region 中的品牌值（requirement.md §2.2）
    return f"{alias}.brand = :d_scope", {"d_scope": ctx.scope}


def parse_filters(
    ctx: DomainContext,
    raw: Mapping[str, Any],
    *,
    allow: Iterable[str] = (),
) -> tuple[dict[str, str], list[str], list[str], list[str]]:
    """校验筛选白名单、剥离客户端域参数、应用锁定维度策略。

    Returns (filters, ignored_client_params, locked_dimension_ignored, notes)
    - 未知参数 -> 400 INVALID_FILTER（不静默丢弃，便于发现越权构造）
    - 客户端域参数 -> 忽略并记录（DM-04），不改变任何返回集合
    - 大区角色传其他 region 值 -> 忽略并记录（DM-08 设计默认：不报错）
    """
    allowed_extra = set(allow)
    filters: dict[str, str] = {}
    ignored: list[str] = []
    locked_ignored: list[str] = []
    notes: list[str] = []

    for key, value in raw.items():
        if key in CLIENT_DOMAIN_PARAMS:
            ignored.append(key)
            continue
        if key in allowed_extra:
            continue
        if key not in FILTER_FIELDS:
            raise ApiError("INVALID_FILTER", f"未知筛选字段: {key}")
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            raise ApiError("INVALID_FILTER", f"筛选字段 {key} 不接受多值")
        sval = str(value)
        if len(sval) > MAX_FILTER_VALUE_LEN:
            raise ApiError("INVALID_FILTER", f"筛选字段 {key} 值过长")
        filters[key] = sval

    locked = LOCKED_DIMENSION_BY_ROLE.get(ctx.role)
    if locked and locked in filters:
        if filters[locked] != ctx.scope:
            locked_ignored.append(locked)
            notes.append(f"维度 {locked} 已锁定为 {ctx.scope}，客户端值被忽略（DM-08）")
        del filters[locked]

    return filters, ignored, locked_ignored, notes


def filter_predicate(filters: Mapping[str, str], alias: str = "s") -> tuple[str, dict[str, Any]]:
    """把白名单筛选编译为参数化 AND 条件（只允许 AND，只允许收窄）。"""
    clauses: list[str] = []
    params: dict[str, Any] = {}
    for key in sorted(filters):
        col = FILTER_FIELDS[key]
        pname = f"f_{key}"
        clauses.append(f"{alias}.{col} = :{pname}")
        params[pname] = filters[key]
    return (" AND ".join(clauses) if clauses else "1=1"), params


def normalize_signature(
    ctx: DomainContext, filters: Mapping[str, str], data_version: str, *, extra: Any = None
) -> str:
    """§2.4.9 筛选签名：白名单字段字典序 + 值标准化 + sha256。"""
    payload = {
        "domain_type": ctx.domain_type,
        "domain_scope": ctx.scope,
        "filters": {k: str(filters[k]).strip() for k in sorted(filters)},
        "data_version": data_version,
        "extra": extra,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_sort(sort: str | None, order: str | None) -> tuple[str, str]:
    field_name = sort or "store_id"
    if field_name not in SORT_FIELDS:
        raise ApiError("INVALID_FILTER", f"未知排序列: {field_name}")
    direction = (order or "asc").lower()
    if direction not in ("asc", "desc"):
        raise ApiError("INVALID_FILTER", f"未知排序方向: {order}")
    return SORT_FIELDS[field_name], direction.upper()


def parse_paging(page: Any, page_size: Any, settings: Any) -> tuple[int, int]:
    def _int(v: Any, default: int) -> int:
        if v is None or v == "":
            return default
        try:
            return int(v)
        except (TypeError, ValueError):
            raise ApiError("INVALID_FILTER", "分页参数必须为整数")

    p = _int(page, 1)
    ps = _int(page_size, settings.page_size_default)
    if p < 1 or ps < 1 or ps > settings.page_size_max:
        raise ApiError("INVALID_FILTER", "分页参数越界")
    return p, ps
